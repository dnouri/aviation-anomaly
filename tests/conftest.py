"""Shared pytest fixtures and utilities for testing."""

from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import duckdb
import pytest
from qck import qck


@pytest.fixture
def duckdb_conn() -> Generator[duckdb.DuckDBPyConnection]:
    """Provide a DuckDB connection with required extensions loaded.

    This fixture provides an in-memory DuckDB connection with:
    - Spatial extension for geographic functions
    - H3 extension for hexagonal grid operations

    The connection is automatically closed after the test completes.

    Example:
        def test_spatial_query(duckdb_conn):
            result = duckdb_conn.execute("SELECT ST_Point(0, 0)").fetchone()
            assert result is not None
    """
    conn = duckdb.connect(":memory:")

    # Install and load spatial extension
    try:
        conn.execute("INSTALL spatial")
        conn.execute("LOAD spatial")
    except Exception as e:
        pytest.skip(f"Spatial extension not available: {e}")

    # Install and load H3 extension from community repository
    try:
        conn.execute("INSTALL h3 FROM community")
        conn.execute("LOAD h3")
    except Exception as e:
        pytest.fail(f"H3 extension is required but not available: {e}")

    yield conn

    conn.close()


@pytest.fixture
def duckdb_conn_no_extensions() -> Generator[duckdb.DuckDBPyConnection]:
    """Provide a basic DuckDB connection without extensions.

    Use this when you need to test basic SQL functionality
    without spatial or H3 features.
    """
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def sample_flight_data(duckdb_conn: duckdb.DuckDBPyConnection) -> None:
    """Create sample flight data table for testing.

    Creates a 'flights' table with sample data including:
    - icao24: Aircraft identifier
    - time: Unix timestamp
    - lat/lon: Position
    - squawk: Transponder code
    - callsign: Flight callsign
    """
    duckdb_conn.execute("""
        CREATE TABLE flights AS
        SELECT * FROM (VALUES
            ('abc123', 1704067200, 40.7128, -74.0060, '0000', 'UAL123'),
            ('abc123', 1704067260, 40.7328, -73.9860, '0000', 'UAL123'),
            ('abc123', 1704067320, 40.7528, -73.9660, '7700', 'UAL123'),  -- Emergency
            ('def456', 1704067200, 51.5074, -0.1278, '0000', 'BAW456'),
            ('def456', 1704067260, 51.5274, -0.1078, '0000', 'BAW456'),
            ('def456', 1704068460, 51.5474, -0.0878, '0000', 'BAW456')   -- 20+ min gap
        ) AS t(icao24, time, lat, lon, squawk, callsign)
    """)


@pytest.fixture
def test_config_file(tmp_path: Path) -> Path:
    """Create a test configuration file.

    Returns:
        Path to a valid test config.toml file
    """
    config_file = tmp_path / "test_config.toml"
    config_file.write_text("""
[segments]
gap_minutes = 20
min_duration_s = 600
min_distance_km = 30

[incidents]
debounce_minutes = 15
max_duration_cap_s = 5400

[aggregation]
min_flights_threshold = 50
good_coverage_min_flights = 100
good_coverage_min_points = 4
""")
    return config_file


@pytest.fixture
def sql_runner(tmp_path) -> Callable:
    """Provide a function to run SQL files or strings with Jinja2 template support.

    Returns:
        Function that runs SQL and returns results
    """

    def run_sql(
        sql: Path | str, 
        params: dict[str, Any] | None = None, 
        conn: duckdb.DuckDBPyConnection | None = None
    ) -> list[tuple]:
        """Run SQL from a file or string and return results.

        Args:
            sql: Path to SQL file or SQL string (can contain Jinja2 templates)
            params: Optional parameters for template substitution
            conn: Optional DuckDB connection to use (ignored, qck manages its own)

        Returns:
            Query results as list of tuples
        """
        # If it's a Path, check it exists
        if isinstance(sql, Path):
            if not sql.exists():
                raise FileNotFoundError(f"SQL file not found: {sql}")
            sql_input = str(sql)
        else:
            # For SQL strings, write to a temp file so qck can process it
            # qck expects a file path, not a SQL string directly
            temp_sql = tmp_path / f"temp_{hash(sql)}.sql"
            temp_sql.write_text(sql)
            sql_input = str(temp_sql)

        # Use qck to run the SQL with template support
        result = qck(sql_input, params=params or {})

        # Handle different result types
        if result is None:
            # DDL statements like CREATE TABLE return None
            return []
        elif hasattr(result, "fetchall"):
            return result.fetchall()
        elif hasattr(result, "df"):
            # If result is a qck ResultSet, convert DataFrame to tuples
            df = result.df()
            if df is None or df.empty:
                return []
            return [tuple(row) for row in df.itertuples(index=False)]
        else:
            return list(result) if result else []

    return run_sql