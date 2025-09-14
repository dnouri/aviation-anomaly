"""Data access layer for OpenSky Trino queries."""

from typing import Any

import duckdb
from trino.auth import JWTAuthentication
from trino.dbapi import Connection, connect

from aviation_anomaly.auth import get_opensky_token


class TrinoQueryEngine:
    """Engine for executing queries against OpenSky Trino database.
    
    Handles authentication automatically using cached tokens when possible.
    In CI environments, requires OPENSKY_USERNAME and OPENSKY_PASSWORD.
    In interactive mode, prompts for credentials if not available.
    """
    
    def __init__(self):
        """Initialize query engine."""
        self._connection: Connection | None = None
    
    def execute(self, query: str) -> list[tuple[Any, ...]]:
        """Execute SQL query against OpenSky Trino.
        
        Args:
            query: SQL query to execute
            
        Returns:
            Query results as list of tuples (one tuple per row)
            
        Raises:
            Exception: If authentication or query fails
        """
        connection = self._get_connection()
        cursor = connection.cursor()
        cursor.execute(query)
        return cursor.fetchall()
    
    def execute_to_duckdb(self, query: str, table_name: str = "result") -> duckdb.DuckDBPyConnection:
        """Execute query and load results directly into DuckDB.
        
        Args:
            query: SQL query to execute against Trino
            table_name: Name for the table in DuckDB
            
        Returns:
            DuckDB connection with results loaded as a table
        """
        results = self.execute(query)
        
        # Create in-memory DuckDB and load results
        conn = duckdb.connect(":memory:")
        if results:
            conn.register("trino_results", results)
            conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM trino_results")
        
        return conn
    
    def _get_connection(self) -> Connection:
        """Get or create Trino connection.
        
        Returns:
            Active Trino connection
        """
        if self._connection is None:
            self._create_connection()
        
        return self._connection  # type: ignore[return-value]
    
    def _create_connection(self) -> None:
        """Create Trino connection with JWT authentication."""
        # Get token (handles caching, refresh, and prompting)
        token = get_opensky_token()
        
        # Connect to OpenSky Trino
        self._connection = connect(
            host="trino.opensky-network.org",
            port=443,
            auth=JWTAuthentication(token),
            http_scheme="https",
            catalog="minio",
            schema="osky",
            legacy_prepared_statements=True,
            source="aviation-anomaly"
        )
    
    def close(self) -> None:
        """Close the connection if open."""
        if self._connection:
            self._connection.close()
            self._connection = None