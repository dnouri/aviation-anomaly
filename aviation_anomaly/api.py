"""Drill-down API for incident details."""

import csv
import datetime
import io
import re
from pathlib import Path
from typing import Any

import duckdb
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.staticfiles import StaticFiles
from qck import qck

from aviation_anomaly.config import Config
from aviation_anomaly.data_access import create_configured_connection

# Data directories
H3_DATA_DIR = Path("data/h3")
INCIDENTS_DIR = Path("data/incidents")
SEGMENTS_DIR = Path("data/segments")

# Date pattern for excluding test/sample files
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\.parquet$")


def build_adsb_exchange_url(
    icao24: str,
    timestamp: int,
    lat: float,
    lon: float,
    zoom: int = 10,
) -> str:
    """
    Build ADS-B Exchange URL for flight replay.

    Args:
        icao24: Aircraft ICAO24 hex identifier
        timestamp: Unix timestamp of incident start
        lat: Latitude coordinate
        lon: Longitude coordinate
        zoom: Map zoom level (default: 10)

    Returns:
        Full URL to ADS-B Exchange with flight replay parameters
    """
    date_str = datetime.datetime.fromtimestamp(timestamp, tz=datetime.UTC).strftime("%Y-%m-%d")
    return (
        f"https://globe.adsbexchange.com/"
        f"?icao={icao24}"
        f"&showTrace={date_str}"
        f"&timestamp={timestamp}"
        f"&lat={lat}"
        f"&lon={lon}"
        f"&zoom={zoom}"
    )


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
            "unique_segments": result[4],
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

    # Find dated incidents and segments files (exclude test/sample files)
    incident_files = sorted([f for f in INCIDENTS_DIR.glob("incidents_*.parquet") if DATE_PATTERN.search(f.name)])
    segment_files = sorted([f for f in SEGMENTS_DIR.glob("segments_*.parquet") if DATE_PATTERN.search(f.name)])

    if not incident_files or not segment_files or not mapping_file.exists():
        return {"meta": {"count": 0}, "rows": []}

    # Use the most recent dated incidents and segments files
    incidents_file = incident_files[-1]
    segments_file = segment_files[-1]

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
        "segments_file": str(segments_file),
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
                    "start_lat": row[7],
                    "start_lon": row[8],
                    "adsb_exchange_url": build_adsb_exchange_url(
                        icao24=row[4],
                        timestamp=row[1],
                        lat=row[7],
                        lon=row[8],
                    ),
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


def export_h3_incidents_to_csv(
    conn: duckdb.DuckDBPyConnection | None = None,
    h3_cell: str = "",
    resolution: int = 4,
    emergency_type: str | None = None,
    limit: int = 200,
    config: Config | None = None,
) -> str:
    """Export H3 cell incidents to CSV format.

    Args:
        conn: Optional DuckDB connection to reuse
        h3_cell: H3 cell to query
        resolution: H3 resolution (3-7)
        emergency_type: Optional filter for emergency type
        limit: Maximum rows to return (default 200, enforced by SQL)
        config: Optional configuration

    Returns:
        CSV string with incident data, headers included even if no data
    """
    # Get incident data using existing function
    result = query_h3_cell_incidents(
        conn=conn,
        h3_cell=h3_cell,
        resolution=resolution,
        emergency_type=emergency_type,
        limit=limit,
        config=config,
    )

    # Field mapping from API response to CSV columns
    field_mapping = {
        "incident_id": "incident_id",
        "start_time": "start_time",
        "end_time": "end_time",
        "emergency_type": "emergency_type",
        "icao24": "icao24",
        "callsign": "callsign",
        "confidence_score": "confidence_score",
        "confidence_category": "confidence_category",
        "samples_in_emergency": "samples_in_emergency",
        "emergency_duration_s": "duration_seconds",  # API field name differs
        "ground_ratio": "ground_ratio",
    }

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(field_mapping.keys()))
    writer.writeheader()

    # Write data rows if we have results
    if result and result.get("rows"):
        for row in result["rows"]:
            csv_row = {}
            for csv_field, api_field in field_mapping.items():
                csv_row[csv_field] = row.get(api_field, "")
            writer.writerow(csv_row)

    return output.getvalue()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Aviation Anomaly Tracker API",
        description="API for querying aviation emergency incidents aggregated to H3 cells",
        version="0.1.0",
    )

    @app.get("/health")
    def health_check() -> dict[str, str]:
        """Simple health check endpoint."""
        return {"status": "ok"}

    @app.get("/api/h3/summary")
    def get_h3_summary(
        h3_cell: str = Query(..., description="H3 cell identifier"),
        resolution: int = Query(..., ge=3, le=7, description="H3 resolution (3-7)"),
        emergency_type: str | None = Query(None, pattern="^(7500|7600|7700)$", description="Emergency type filter"),
    ) -> dict[str, Any]:
        """Get summary statistics for an H3 cell."""
        result = query_h3_cell_summary(
            h3_cell=h3_cell,
            resolution=resolution,
            emergency_type=emergency_type,
        )

        if result is None:
            raise HTTPException(status_code=404, detail="H3 cell not found")

        return result

    @app.get("/api/h3/incidents")
    def get_h3_incidents(
        h3_cell: str = Query(..., description="H3 cell identifier"),
        resolution: int = Query(..., ge=3, le=7, description="H3 resolution (3-7)"),
        emergency_type: str | None = Query(None, pattern="^(7500|7600|7700)$", description="Emergency type filter"),
        limit: int = Query(200, le=1000, description="Maximum results"),
        offset: int = Query(0, ge=0, description="Pagination offset"),
    ) -> dict[str, Any]:
        """Get individual incidents within an H3 cell."""
        return query_h3_cell_incidents(
            h3_cell=h3_cell,
            resolution=resolution,
            emergency_type=emergency_type,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/h3/incidents.csv")
    def export_incidents_csv(
        h3_cell: str = Query(..., description="H3 cell identifier"),
        resolution: int = Query(..., ge=3, le=7, description="H3 resolution (3-7)"),
        emergency_type: str | None = Query(None, pattern="^(7500|7600|7700)$", description="Emergency type filter"),
        limit: int = Query(200, le=1000, description="Maximum results"),
    ) -> Response:
        """Export incidents as CSV."""
        csv_content = export_h3_incidents_to_csv(
            h3_cell=h3_cell,
            resolution=resolution,
            emergency_type=emergency_type,
            limit=limit,
        )

        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=incidents_h3_{h3_cell}_r{resolution}.csv"},
        )

    # Mount data files for PMTiles access
    tiles_dir = Path("data/tiles/pmtiles")
    if tiles_dir.exists():
        app.mount("/tiles", StaticFiles(directory=str(tiles_dir)), name="tiles")

    # Mount static files last (as fallback for everything else)
    static_dir = Path("static")
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
