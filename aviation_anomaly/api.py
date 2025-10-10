"""Drill-down API for incident details."""

import csv
import datetime
import io
import re
from pathlib import Path
from typing import Any

import duckdb
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import JSONResponse
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

    # Load configuration if not provided
    if config is None:
        config = Config()

    # Build path to H3 incidents file for this resolution
    h3_file = config.data_dir / "h3" / f"h3_incidents_r{resolution}.parquet"

    if not h3_file.exists():
        return None

    # Validate and convert h3_cell to integer
    try:
        h3_cell_int = int(h3_cell)
    except (ValueError, TypeError):
        # Invalid H3 cell format
        return None

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

    # Load configuration if not provided
    if config is None:
        config = Config()

    # Build paths to data files
    mapping_file = config.data_dir / "h3" / f"incident_h3_mapping_r{resolution}.parquet"

    # Find dated incidents files (exclude test/sample files)
    incidents_dir = config.data_dir / "incidents"
    incident_files = sorted([f for f in incidents_dir.glob("incidents_*.parquet") if DATE_PATTERN.search(f.name)])

    if not incident_files or not mapping_file.exists():
        return {"meta": {"count": 0}, "rows": []}

    # Query ALL dated incidents files using glob pattern.
    # H3 aggregation processes incidents from multiple dates, and the incident-to-H3 mapping
    # references incidents across all date partitions.
    #
    # Design: Incident positions (start_lat, start_lon) are stored directly in incidents table,
    # avoiding segment joins entirely. Segments contain full trajectory arrays (~6K points each)
    # and appear duplicated across multiple date files (same segment_id in 3-5 files with different
    # trajectory subsets). Joining and filtering these at query time is expensive.
    incidents_pattern = str(incidents_dir / "incidents_*.parquet")

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
        "incidents_file": incidents_pattern,
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


def create_app(config: Config | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: Optional configuration object. If not provided, uses defaults.
    """
    # Use provided config or create default
    if config is None:
        config = Config()

    app = FastAPI(
        title="Aviation Anomaly Tracker API",
        description="API for querying aviation emergency incidents aggregated to H3 cells",
        version="0.1.0",
    )

    # Store config in app state for access in routes
    app.state.config = config

    @app.get("/health")
    def health_check() -> Response:
        """
        Health check endpoint with actual verification.

        Verifies:
        - DuckDB connection works
        - Critical data files are accessible

        Returns:
            200 OK if healthy
            503 Service Unavailable if unhealthy
        """
        checks = {}
        all_healthy = True

        # Get configuration from app state
        config = app.state.config

        # Check DuckDB connection
        try:
            conn = create_configured_connection(config)
            conn.execute("SELECT 1").fetchone()
            checks["duckdb"] = "ok"
        except Exception as e:
            checks["duckdb"] = f"error: {str(e)}"
            all_healthy = False

        # Check critical data file exists and is queryable
        h3_file = config.data_dir / "h3" / "h3_incidents_r3.parquet"
        try:
            if not h3_file.exists():
                checks["data_files"] = f"error: {h3_file} not found"
                all_healthy = False
            else:
                # Actually query the file to ensure it's readable
                conn = create_configured_connection(config)
                result = conn.execute(f"SELECT COUNT(*) FROM '{h3_file}'").fetchone()
                checks["data_files"] = f"ok ({result[0]} cells)" if result else "ok"
        except Exception as e:
            checks["data_files"] = f"error: {str(e)}"
            all_healthy = False

        status_code = 200 if all_healthy else 503
        response_body = {
            "status": "healthy" if all_healthy else "unhealthy",
            "checks": checks,
        }

        return JSONResponse(
            content=response_body,
            status_code=status_code,
        )

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
            config=app.state.config,
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
            config=app.state.config,
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
            config=app.state.config,
        )

        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=incidents_h3_{h3_cell}_r{resolution}.csv"},
        )

    # Mount data files for PMTiles access
    tiles_dir = config.data_dir / "tiles" / "pmtiles"
    if tiles_dir.exists():
        app.mount("/tiles", StaticFiles(directory=str(tiles_dir)), name="tiles")

    # Mount static files last (as fallback for everything else)
    static_dir = Path("static")
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


# Create application instance at module level for uvicorn
app = create_app()
