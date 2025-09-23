"""Drill-down API for incident details."""

from pathlib import Path
from typing import Any

import duckdb
from qck import qck

from aviation_anomaly.config import Config
from aviation_anomaly.data_access import create_configured_connection

# Data directories
H3_DATA_DIR = Path("data/h3")
INCIDENTS_DIR = Path("data/incidents")


def query_h3_cell_summary(
    conn: duckdb.DuckDBPyConnection | None = None,
    h3_cell: str = "",
    resolution: int = 5,
    emergency_type: str | None = None,
    config: Config | None = None,
) -> dict[str, Any] | None:
    """
    Query summary data for a specific H3 cell.

    Args:
        conn: Optional DuckDB connection (will create if not provided)
        h3_cell: H3 cell identifier (string representation of UBIGINT)
        resolution: H3 resolution (3-7)
        emergency_type: Optional filter by emergency type (7500/7600/7700)
        config: Optional configuration object

    Returns:
        Dictionary with cell summary data, or None if cell not found
    """
    # Validate resolution range
    if resolution not in range(3, 8):
        return None

    # Build path to H3 incidents file for this resolution
    h3_file = H3_DATA_DIR / f"h3_incidents_r{resolution}.parquet"

    if not h3_file.exists():
        return None

    # Validate and convert h3_cell to integer
    try:
        h3_cell_int = int(h3_cell)
    except (ValueError, TypeError):
        # Invalid H3 cell format
        return None

    # Load configuration if not provided
    if config is None:
        config = Config()

    # Use provided connection or create a configured one
    if conn is None:
        conn = create_configured_connection(config)
        close_conn = True
    else:
        close_conn = False

    # Prepare SQL parameters
    sql_path = Path(__file__).parent / "sql" / "h3_cell_summary.sql"
    params = {
        "h3_file": str(h3_file),
        "h3_cell": h3_cell_int,
        "emergency_type": emergency_type,
    }

    try:
        # Execute query using qck - returns results directly
        result = qck(str(sql_path), params=params, connection=conn).fetchone()

        if not result:
            return None

        # Return as dictionary with clear field mapping
        return {
            "h3_cell": str(result[0]),  # Convert UBIGINT to string
            "h3_res": result[1],
            "incidents_unique": result[2],
            "incidents_coverage": result[3],
            "unique_flights": result[4],
            "incident_rate": result[5],
            "emergency_types_list": result[6],
            "emergency_type_diversity": result[7],
            "predominant_emergency_type": result[8],
        }

    finally:
        if close_conn:
            conn.close()


def query_h3_cell_incidents(
    conn: duckdb.DuckDBPyConnection | None = None,
    h3_cell: str = "",
    resolution: int = 5,
    emergency_type: str | None = None,
    limit: int = 200,
    offset: int = 0,
    config: Config | None = None,
) -> dict[str, Any]:
    """
    Query individual incidents within an H3 cell.

    Args:
        conn: Optional DuckDB connection (will create if not provided)
        h3_cell: H3 cell identifier
        resolution: H3 resolution (3-7)
        emergency_type: Optional filter by emergency type (7500/7600/7700)
        limit: Maximum number of results (default 200)
        offset: Offset for pagination (default 0)
        config: Optional configuration object

    Returns:
        Dictionary with metadata and incident rows
    """
    # Validate inputs
    if resolution not in range(3, 8):
        return {"meta": {"count": 0}, "rows": []}

    # Validate and convert h3_cell to integer
    try:
        h3_cell_int = int(h3_cell)
    except (ValueError, TypeError):
        return {"meta": {"count": 0}, "rows": []}

    # Build paths to data files
    mapping_file = H3_DATA_DIR / f"incident_h3_mapping_r{resolution}.parquet"

    # Find appropriate incidents file (look for most recent)
    incident_files = sorted(INCIDENTS_DIR.glob("incidents_*.parquet"))
    if not incident_files or not mapping_file.exists():
        return {"meta": {"count": 0}, "rows": []}

    # Use the most recent incidents file
    incidents_file = incident_files[-1]

    # Load configuration if not provided
    if config is None:
        config = Config()

    # Use provided connection or create a configured one
    if conn is None:
        conn = create_configured_connection(config)
        close_conn = True
    else:
        close_conn = False

    # Prepare SQL parameters
    sql_path = Path(__file__).parent / "sql" / "h3_cell_incidents.sql"
    params = {
        "mapping_file": str(mapping_file),
        "incidents_file": str(incidents_file),
        "h3_cell": h3_cell_int,
        "emergency_type": emergency_type,
        "limit": limit,
        "offset": offset,
    }

    try:
        # Execute query using qck - returns all results
        results = qck(str(sql_path), params=params, connection=conn).fetchall()

        # Format results
        rows = []
        for row in results:
            rows.append(
                {
                    "incident_id": row[0],
                    "start_time": row[1],
                    "end_time": row[2],
                    "emergency_type": row[3],
                    "icao24": row[4],
                    "confidence_score": row[5],
                    "duration_seconds": row[6],
                }
            )

        return {
            "meta": {
                "count": len(rows),
                "h3_cell": h3_cell,
                "resolution": resolution,
            },
            "rows": rows,
        }

    finally:
        if close_conn:
            conn.close()
