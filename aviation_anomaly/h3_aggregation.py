"""H3 aggregation pipeline for flight segments."""

import logging
from pathlib import Path

import duckdb
from qck import qck

from aviation_anomaly.config import Config

logger = logging.getLogger(__name__)


def compute_h3_coverage(
    segment_file: Path,
    output_file: Path,
    resolution: int,
    config: Config | None = None,
) -> None:
    """
    Compute H3 coverage from flight segments at a single resolution.

    Args:
        segment_file: Path to segment Parquet file
        output_file: Path to output aggregation Parquet file
        resolution: H3 resolution (3-7)
        config: Configuration object (optional)
    """
    if not segment_file.exists():
        raise FileNotFoundError(f"Segment file not found: {segment_file}")

    if resolution not in range(3, 8):
        raise ValueError(f"Resolution must be between 3 and 7, got {resolution}")

    # Load configuration
    if config is None:
        config = Config.from_file(Path("config.toml"))

    # Prepare SQL parameters
    sql_path = Path(__file__).parent / "sql" / "h3_aggregation.sql"

    params = {
        "segment_file": str(segment_file),
        "output_file": str(output_file),
        "resolution": resolution,
        "memory_limit": config.duckdb.memory_limit,
        "threads": config.duckdb.threads,
        "temp_directory": config.duckdb.temp_directory,
    }

    logger.info(f"Computing H3 coverage at resolution {resolution}")
    logger.info(f"Input: {segment_file}")
    logger.info(f"Output: {output_file}")

    # Ensure h3 extension is loaded
    conn = duckdb.connect(":memory:")
    conn.execute("INSTALL h3")
    conn.execute("LOAD h3")
    conn.close()

    # Execute SQL pipeline
    try:
        qck(str(sql_path), params=params)
        logger.info(f"H3 aggregation complete: {output_file}")
    except Exception as e:
        logger.error(f"H3 aggregation failed: {e}")
        raise


def compute_h3_coverage_multi_resolution(
    segment_file: Path,
    output_dir: Path,
    resolutions: list[int] | None = None,
    config: Config | None = None,
) -> dict[int, Path]:
    """
    Compute H3 coverage for multiple resolutions.

    Args:
        segment_file: Path to segment Parquet file
        output_dir: Directory for output files
        resolutions: List of H3 resolutions (default: [3,4,5,6,7])
        config: Configuration object (optional)

    Returns:
        Dictionary mapping resolution to output file path
    """
    if resolutions is None:
        resolutions = [3, 4, 5, 6, 7]

    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    for res in resolutions:
        output_file = output_dir / f"h3_coverage_r{res}.parquet"
        compute_h3_coverage(segment_file, output_file, res, config)
        results[res] = output_file

    return results


def compute_coverage_metrics(
    segment_file: Path,
    output_file: Path,
    resolution: int = 5,
    config: Config | None = None,
) -> None:
    """
    Compute coverage quality metrics including points-per-flight.

    Args:
        segment_file: Path to segment Parquet file
        output_file: Path to output metrics file
        resolution: H3 resolution (default: 5)
        config: Configuration object (optional)
    """
    if not segment_file.exists():
        raise FileNotFoundError(f"Segment file not found: {segment_file}")

    if config is None:
        config = Config.from_file(Path("config.toml"))

    conn = duckdb.connect(":memory:")
    conn.execute("INSTALL h3")
    conn.execute("LOAD h3")
    conn.execute(f"SET memory_limit = '{config.duckdb.memory_limit}'")

    # Compute coverage metrics with points-per-flight
    conn.execute(f"""
        COPY (
            WITH segment_cells AS (
                SELECT
                    segment_id,
                    icao24,
                    point_count,
                    list_distinct(
                        list_transform(
                            points,
                            p -> h3_latlng_to_cell(p.lat, p.lon, {resolution})
                        )
                    ) as h3_cells,
                    len(list_distinct(
                        list_transform(
                            points,
                            p -> h3_latlng_to_cell(p.lat, p.lon, {resolution})
                        )
                    )) as num_cells
                FROM read_parquet('{segment_file}')
                WHERE point_count >= 2
            ),
            cell_coverage AS (
                SELECT
                    UNNEST(h3_cells) as h3_cell,
                    segment_id,
                    point_count,
                    num_cells
                FROM segment_cells
            ),
            coverage_metrics AS (
                SELECT
                    h3_cell,
                    COUNT(DISTINCT segment_id) as unique_segments,
                    -- Points-per-flight metric
                    PERCENTILE_CONT(0.5) WITHIN GROUP (
                        ORDER BY CAST(point_count AS DOUBLE) / num_cells
                    ) as median_points_per_cell,
                    AVG(CAST(point_count AS DOUBLE) / num_cells) as avg_points_per_cell,
                    -- Coverage category based on median points-per-flight
                    CASE
                        WHEN PERCENTILE_CONT(0.5) WITHIN GROUP (
                            ORDER BY CAST(point_count AS DOUBLE) / num_cells
                        ) >= 10 THEN 'excellent'
                        WHEN PERCENTILE_CONT(0.5) WITHIN GROUP (
                            ORDER BY CAST(point_count AS DOUBLE) / num_cells
                        ) >= 6 THEN 'good'
                        WHEN PERCENTILE_CONT(0.5) WITHIN GROUP (
                            ORDER BY CAST(point_count AS DOUBLE) / num_cells
                        ) >= 3 THEN 'limited'
                        ELSE 'poor'
                    END as coverage_category
                FROM cell_coverage
                GROUP BY h3_cell
            )
            SELECT * FROM coverage_metrics
            ORDER BY h3_cell
        ) TO '{output_file}' (FORMAT PARQUET, COMPRESSION 'zstd')
    """)

    conn.close()
    logger.info(f"Coverage metrics computed: {output_file}")


def compute_dual_incident_metrics(
    incidents_file: Path,
    segments_file: Path,
    output_file: Path,
    resolution: int = 5,
    config: Config | None = None,
) -> None:
    """
    Compute dual incident metrics for H3 cells.

    - incidents_unique: Count of unique incidents per cell (for rate calculation)
    - incidents_coverage: Count of all incident observations (for heatmap visualization)

    Args:
        incidents_file: Path to incidents Parquet file
        segments_file: Path to segments Parquet file for flight counts
        output_file: Path to output metrics file
        resolution: H3 resolution (default: 5)
        config: Configuration object (optional)
    """
    if not incidents_file.exists():
        raise FileNotFoundError(f"Incidents file not found: {incidents_file}")
    if not segments_file.exists():
        raise FileNotFoundError(f"Segments file not found: {segments_file}")

    if config is None:
        config = Config.from_file(Path("config.toml"))

    conn = duckdb.connect(":memory:")
    conn.execute("INSTALL h3; LOAD h3")
    conn.execute(f"SET memory_limit = '{config.duckdb.memory_limit}'")
    conn.execute(f"SET threads = {config.duckdb.threads}")

    # Compute dual metrics
    conn.execute(f"""
        COPY (
            -- First, get H3 cells for incidents
            WITH incident_cells AS (
                SELECT
                    i.incident_id,
                    i.icao24,
                    i.squawk_code,
                    h3_latlng_to_cell(p.lat, p.lon, {resolution}) as h3_cell
                FROM (
                    SELECT
                        incident_id,
                        icao24,
                        squawk_code,
                        UNNEST(points) as p
                    FROM read_parquet('{incidents_file}')
                ) i
            ),

            -- Count unique incidents per cell
            incident_unique_counts AS (
                SELECT
                    h3_cell,
                    COUNT(DISTINCT incident_id) as incidents_unique
                FROM incident_cells
                GROUP BY h3_cell
            ),

            -- Count all incident observations (for coverage/heatmap)
            incident_coverage_counts AS (
                SELECT
                    h3_cell,
                    COUNT(*) as incidents_coverage
                FROM incident_cells
                GROUP BY h3_cell
            ),

            -- Get flight counts from segments
            segment_cells AS (
                SELECT
                    s.segment_id,
                    h3_latlng_to_cell(p.lat, p.lon, {resolution}) as h3_cell
                FROM (
                    SELECT segment_id, UNNEST(points) as p
                    FROM read_parquet('{segments_file}')
                ) s
            ),
            flight_counts AS (
                SELECT
                    h3_cell,
                    COUNT(DISTINCT segment_id) as flights
                FROM segment_cells
                GROUP BY h3_cell
            ),

            -- Combine metrics
            combined AS (
                SELECT
                    COALESCE(iu.h3_cell, ic.h3_cell, f.h3_cell) as h3_cell,
                    COALESCE(iu.incidents_unique, 0) as incidents_unique,
                    COALESCE(ic.incidents_coverage, 0) as incidents_coverage,
                    COALESCE(f.flights, 0) as flights,
                    -- Calculate rates (parts per million)
                    CASE
                        WHEN COALESCE(f.flights, 0) > 0
                        THEN (CAST(COALESCE(iu.incidents_unique, 0) AS DOUBLE) / f.flights) * 1000000
                        ELSE 0
                    END as rate_unique_ppm,
                    CASE
                        WHEN COALESCE(f.flights, 0) > 0
                        THEN (CAST(COALESCE(ic.incidents_coverage, 0) AS DOUBLE) / f.flights) * 1000000
                        ELSE 0
                    END as rate_coverage_ppm
                FROM incident_unique_counts iu
                FULL OUTER JOIN incident_coverage_counts ic ON iu.h3_cell = ic.h3_cell
                FULL OUTER JOIN flight_counts f ON COALESCE(iu.h3_cell, ic.h3_cell) = f.h3_cell
            )

            SELECT * FROM combined
            ORDER BY h3_cell
        ) TO '{output_file}' (FORMAT PARQUET, COMPRESSION 'zstd')
    """)

    conn.close()
    logger.info(f"Dual incident metrics computed: {output_file}")


def aggregate_incidents_by_type(
    incidents_file: Path,
    segments_file: Path,
    output_file: Path,
    resolution: int = 5,
    config: Config | None = None,
) -> None:
    """
    Aggregate incidents by squawk type for H3 cells.

    Args:
        incidents_file: Path to incidents Parquet file
        segments_file: Path to segments Parquet file for flight counts
        output_file: Path to output aggregation file
        resolution: H3 resolution (default: 5)
        config: Configuration object (optional)
    """
    if not incidents_file.exists():
        raise FileNotFoundError(f"Incidents file not found: {incidents_file}")
    if not segments_file.exists():
        raise FileNotFoundError(f"Segments file not found: {segments_file}")

    if config is None:
        config = Config.from_file(Path("config.toml"))

    conn = duckdb.connect(":memory:")
    conn.execute("INSTALL h3; LOAD h3")
    conn.execute(f"SET memory_limit = '{config.duckdb.memory_limit}'")

    # Aggregate by squawk type
    conn.execute(f"""
        COPY (
            WITH incident_cells AS (
                SELECT
                    i.incident_id,
                    i.squawk_code,
                    h3_latlng_to_cell(p.lat, p.lon, {resolution}) as h3_cell
                FROM (
                    SELECT
                        incident_id,
                        squawk_code,
                        UNNEST(points) as p
                    FROM read_parquet('{incidents_file}')
                ) i
            ),

            -- Count by type
            type_counts AS (
                SELECT
                    h3_cell,
                    COUNT(DISTINCT CASE WHEN squawk_code = '7500' THEN incident_id END) as incidents_7500,
                    COUNT(DISTINCT CASE WHEN squawk_code = '7600' THEN incident_id END) as incidents_7600,
                    COUNT(DISTINCT CASE WHEN squawk_code = '7700' THEN incident_id END) as incidents_7700,
                    COUNT(DISTINCT incident_id) as incidents_all
                FROM incident_cells
                GROUP BY h3_cell
            )

            SELECT * FROM type_counts
            ORDER BY h3_cell
        ) TO '{output_file}' (FORMAT PARQUET, COMPRESSION 'zstd')
    """)

    conn.close()
    logger.info(f"Incidents aggregated by type: {output_file}")


def apply_visibility_thresholds(
    aggregates_file: Path,
    output_file: Path,
    resolution: int,
    min_flights: int,
    config: Config | None = None,
) -> None:
    """
    Apply visibility thresholds to filter H3 cells.

    Args:
        aggregates_file: Path to aggregates Parquet file
        output_file: Path to filtered output file
        resolution: H3 resolution
        min_flights: Minimum flight threshold
        config: Configuration object (optional)
    """
    if not aggregates_file.exists():
        raise FileNotFoundError(f"Aggregates file not found: {aggregates_file}")

    if config is None:
        config = Config.from_file(Path("config.toml"))

    conn = duckdb.connect(":memory:")
    conn.execute(f"SET memory_limit = '{config.duckdb.memory_limit}'")

    # Apply threshold filtering
    conn.execute(f"""
        COPY (
            SELECT *
            FROM read_parquet('{aggregates_file}')
            WHERE unique_segments >= {min_flights}
            ORDER BY h3_cell
        ) TO '{output_file}' (FORMAT PARQUET, COMPRESSION 'zstd')
    """)

    conn.close()
    logger.info(f"Visibility thresholds applied: {output_file}")
