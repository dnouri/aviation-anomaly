"""Drill-down API for incident details."""

from pathlib import Path
from typing import Any

import duckdb

# Data directories
H3_DATA_DIR = Path("data/h3")
INCIDENTS_DIR = Path("data/incidents")

# SQL query for cell summary - uses named columns for clarity
CELL_SUMMARY_QUERY = """
    SELECT
        h3_cell,
        h3_res,
        incidents_unique,
        incidents_coverage,
        unique_flights,
        incident_rate,
        emergency_types_list,
        emergency_type_diversity,
        predominant_emergency_type
    FROM '{h3_file}'
    WHERE h3_cell = {h3_cell_int}
"""


def query_h3_cell_summary(
    conn: duckdb.DuckDBPyConnection,
    h3_cell: str,
    resolution: int,
    emergency_type: str | None = None,
) -> dict[str, Any] | None:
    """
    Query summary data for a specific H3 cell.

    Args:
        conn: DuckDB connection
        h3_cell: H3 cell identifier (string representation of UBIGINT)
        resolution: H3 resolution (3-7)
        emergency_type: Optional filter by emergency type (7500/7600/7700)

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

    # Build query
    query = CELL_SUMMARY_QUERY.format(h3_file=h3_file, h3_cell_int=h3_cell_int)

    # Add optional emergency type filter
    if emergency_type:
        query += f" AND '{emergency_type}' = ANY(emergency_types_list)"

    # Execute query
    result = conn.execute(query).fetchone()

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


def query_h3_cell_incidents(
    conn: duckdb.DuckDBPyConnection,
    h3_cell: str,
    resolution: int,
    emergency_type: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Query individual incidents within an H3 cell.

    Args:
        conn: DuckDB connection
        h3_cell: H3 cell identifier
        resolution: H3 resolution (3-7)
        emergency_type: Optional filter by emergency type (7500/7600/7700)
        limit: Maximum number of results (default 200)
        offset: Offset for pagination (default 0)

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

    # Build query to get incident details
    query = f"""
        WITH cell_incidents AS (
            SELECT DISTINCT incident_id
            FROM '{mapping_file}'
            WHERE h3_cell = {h3_cell_int}
        )
        SELECT
            i.incident_id,
            i.start_time,
            i.end_time,
            i.emergency_type,
            i.icao24,
            i.confidence_score,
            i.duration_seconds
        FROM '{incidents_file}' i
        JOIN cell_incidents ci ON i.incident_id = ci.incident_id
    """

    # Add emergency type filter if specified
    if emergency_type:
        query += f" WHERE i.emergency_type = '{emergency_type}'"

    # Add ordering and pagination
    query += f"""
        ORDER BY i.start_time DESC
        LIMIT {limit}
        OFFSET {offset}
    """

    # Execute query
    results = conn.execute(query).fetchall()

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
