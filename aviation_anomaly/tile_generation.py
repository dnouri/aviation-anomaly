"""Tile generation for map visualization."""

import json
import logging
from pathlib import Path

import duckdb
from qck import qck

from aviation_anomaly.config import Config
from aviation_anomaly.data_access import create_configured_connection

logger = logging.getLogger(__name__)


def export_h3_to_geojson(
    conn: duckdb.DuckDBPyConnection,
    coverage_table: str,
    incidents_table: str | None,
    output_file: Path,
) -> None:
    """Export H3 cells to GeoJSON format.

    Args:
        conn: DuckDB connection with h3 and spatial extensions loaded
        coverage_table: Name of table/view with H3 coverage data
        incidents_table: Optional name of table with H3 incident data
        output_file: Path to write GeoJSON output
    """
    # Use SQL template with qck
    sql_path = Path(__file__).parent / "sql" / "h3_to_geojson.sql"

    params = {
        "coverage_table": coverage_table,
        "incidents_table": incidents_table if incidents_table else "NULL",
        "has_incidents": incidents_table is not None,
    }

    # Execute query and get result
    result = qck(str(sql_path), params=params, connection=conn)

    # qck returns a DuckDBPyRelation, fetch the first row
    row = result.fetchone() if result else None
    if row and row[0]:
        # Parse the JSON string from DuckDB and write it formatted
        geojson_data = json.loads(row[0])

        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w") as f:
            json.dump(geojson_data, f, indent=2)


def export_h3_files_to_geojson(
    h3_dir: Path,
    output_dir: Path,
    resolutions: list[int] | None = None,
    config: Config | None = None,
) -> None:
    """Export H3 aggregation files to GeoJSON format.

    Args:
        h3_dir: Directory containing H3 aggregation files
        output_dir: Directory to write GeoJSON files
        resolutions: List of resolutions to export (default: 3-7)
        config: Configuration object (optional)
    """
    if resolutions is None:
        resolutions = [3, 4, 5, 6, 7]

    if config is None:
        config = Config()

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create configured connection with extensions
    conn = create_configured_connection(config, extensions=["h3", "spatial"])

    try:
        for res in resolutions:
            logger.info(f"Processing resolution {res}")

            # Check for coverage and incident files
            coverage_file = h3_dir / f"h3_coverage_r{res}.parquet"
            incidents_file = h3_dir / f"h3_incidents_r{res}.parquet"

            if not coverage_file.exists():
                logger.warning(f"Coverage file not found: {coverage_file}")
                continue

            # Create views from parquet files
            conn.execute(f"""
                CREATE OR REPLACE VIEW coverage_r{res} AS
                SELECT * FROM read_parquet('{coverage_file}')
            """)

            if incidents_file.exists():
                conn.execute(f"""
                    CREATE OR REPLACE VIEW incidents_r{res} AS
                    SELECT * FROM read_parquet('{incidents_file}')
                """)
                incidents_table = f"incidents_r{res}"
            else:
                logger.info(f"No incidents file for resolution {res}, exporting coverage only")
                incidents_table = None

            # Export to GeoJSON
            output_file = output_dir / f"h3_r{res}.geojson"
            logger.info(f"Exporting to {output_file}")

            export_h3_to_geojson(
                conn, coverage_table=f"coverage_r{res}", incidents_table=incidents_table, output_file=output_file
            )

            # Get file size and feature count for logging
            file_size_mb = output_file.stat().st_size / (1024 * 1024)
            with open(output_file) as f:
                feature_count = len(json.load(f)["features"])

            logger.info(f"Resolution {res}: {feature_count:,} features, {file_size_mb:.1f} MB")

    finally:
        conn.close()

    logger.info("GeoJSON export complete")
