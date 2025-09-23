"""H3 aggregation pipeline for flight segments."""

import logging
from pathlib import Path

import duckdb
from qck import qck

from aviation_anomaly.config import Config
from aviation_anomaly.data_access import create_configured_connection

logger = logging.getLogger(__name__)


def compute_h3_coverage(
    segment_file: Path,
    output_file: Path,
    resolution: int,
    config: Config | None = None,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> None:
    """
    Compute H3 coverage from flight segments at a single resolution.

    Args:
        segment_file: Path to segment Parquet file
        output_file: Path to output aggregation Parquet file
        resolution: H3 resolution (3-7)
        config: Configuration object (optional)
        connection: DuckDB connection to reuse (optional)
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
    }

    logger.info(f"Computing H3 coverage at resolution {resolution}")
    logger.info(f"Input: {segment_file}")
    logger.info(f"Output: {output_file}")

    # Execute SQL pipeline
    try:
        if connection:
            qck(str(sql_path), params=params, connection=connection)
        else:
            # Create connection with H3 extension for single use
            conn = create_configured_connection(config, extensions=["h3"])
            try:
                qck(str(sql_path), params=params, connection=conn)
            finally:
                conn.close()
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

    if config is None:
        config = Config.from_file(Path("config.toml"))

    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    # Create single connection for all resolutions
    conn = create_configured_connection(config, extensions=["h3"])
    try:
        for res in resolutions:
            output_file = output_dir / f"h3_coverage_r{res}.parquet"
            compute_h3_coverage(segment_file, output_file, res, config, connection=conn)
            results[res] = output_file
    finally:
        conn.close()

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

    # Prepare SQL parameters
    sql_path = Path(__file__).parent / "sql" / "h3_coverage_metrics.sql"

    params = {
        "segment_file": str(segment_file),
        "output_file": str(output_file),
        "resolution": resolution,
    }

    # Execute SQL pipeline
    conn = create_configured_connection(config, extensions=["h3"])
    try:
        qck(str(sql_path), params=params, connection=conn)
        logger.info(f"Coverage metrics computed: {output_file}")
    finally:
        conn.close()


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

    # Prepare SQL parameters
    sql_path = Path(__file__).parent / "sql" / "h3_incident_metrics.sql"

    params = {
        "incidents_file": str(incidents_file),
        "segments_file": str(segments_file),
        "output_file": str(output_file),
        "resolution": resolution,
    }

    # Apply DuckDB configuration and execute SQL
    conn = create_configured_connection(config, extensions=["h3"])
    qck(str(sql_path), params=params, connection=conn)
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

    # Prepare SQL parameters
    sql_path = Path(__file__).parent / "sql" / "h3_incident_by_type.sql"

    params = {
        "incidents_file": str(incidents_file),
        "segments_file": str(segments_file),
        "output_file": str(output_file),
        "resolution": resolution,
    }

    # Execute SQL pipeline
    conn = create_configured_connection(config, extensions=["h3"])
    try:
        qck(str(sql_path), params=params, connection=conn)
        logger.info(f"Incidents aggregated by type: {output_file}")
    finally:
        conn.close()


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

    # Prepare SQL parameters
    sql_path = Path(__file__).parent / "sql" / "h3_visibility_filter.sql"

    params = {
        "aggregates_file": str(aggregates_file),
        "output_file": str(output_file),
        "min_flights": min_flights,
    }

    # Execute SQL pipeline (no H3 extension needed for filtering)
    conn = create_configured_connection(config)
    try:
        qck(str(sql_path), params=params, connection=conn)
        logger.info(f"Visibility thresholds applied: {output_file}")
    finally:
        conn.close()
