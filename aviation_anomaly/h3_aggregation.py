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
        segment_file: Path to segment Parquet file (or glob pattern)
        output_file: Path to output aggregation Parquet file
        resolution: H3 resolution (3-7)
        config: Configuration object (optional)
        connection: DuckDB connection to reuse (optional)
    """
    # Check if file exists (skip check for glob patterns)
    segment_str = str(segment_file)
    is_glob_pattern = "*" in segment_str or "?" in segment_str

    if not is_glob_pattern and not segment_file.exists():
        raise FileNotFoundError(f"Segment file not found: {segment_file}")

    if resolution not in range(3, 8):
        raise ValueError(f"Resolution must be between 3 and 7, got {resolution}")

    # Load configuration
    if config is None:
        config = Config.from_file(Path("config.toml"))

    # Atomic write pattern: write to temp file, then rename
    temp_file = output_file.with_suffix(".tmp")

    # Prepare SQL parameters
    sql_path = Path(__file__).parent / "sql" / "h3_aggregation.sql"

    params = {
        "segment_file": str(segment_file),
        "output_file": str(temp_file),  # Write to temp file
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

        # Atomic rename on success
        temp_file.rename(output_file)
        logger.info(f"H3 aggregation complete: {output_file}")
    except Exception as e:
        # Clean up temp file on failure
        if temp_file.exists():
            temp_file.unlink()
        logger.error(f"H3 aggregation failed: {e}")
        raise


def compute_h3_coverage_multi_resolution(
    segment_files: list[Path] | Path,
    output_dir: Path,
    resolutions: list[int] | None = None,
    config: Config | None = None,
) -> dict[int, Path]:
    """
    Compute H3 coverage for multiple resolutions with per-day processing and merge.

    Processes segment files individually (memory-efficient), then merges into final aggregate.
    Uses daily/ subdirectory for per-day outputs, main directory for merged results.

    Args:
        segment_files: Path to segment file or list of segment files
        output_dir: Directory for output files
        resolutions: List of H3 resolutions (default: [3,4,5,6,7])
        config: Configuration object (optional)

    Returns:
        Dictionary mapping resolution to merged output file path
    """
    # Normalize to list
    if isinstance(segment_files, Path):
        segment_files = [segment_files]

    if resolutions is None:
        resolutions = [3, 4, 5, 6, 7]

    if config is None:
        config = Config.from_file(Path("config.toml"))

    output_dir.mkdir(parents=True, exist_ok=True)
    daily_dir = output_dir / "daily"
    daily_dir.mkdir(exist_ok=True)

    # Create single connection for efficiency
    conn = create_configured_connection(config, extensions=["h3"])
    try:
        # Process each segment file to daily/ directory
        for segment_file in segment_files:
            # Extract date from filename (e.g., segments_2025-07-02.parquet → 2025-07-02)
            date_str = segment_file.stem.replace("segments_", "")

            logger.info(f"Processing H3 coverage for {date_str}")

            for res in resolutions:
                daily_output = daily_dir / f"h3_coverage_r{res}_{date_str}.parquet"

                # Check staleness: skip if daily file is newer than segment file
                if daily_output.exists() and daily_output.stat().st_mtime > segment_file.stat().st_mtime:
                    logger.debug(f"Skipping {daily_output.name} (up to date)")
                    continue

                # Generate daily H3 coverage
                compute_h3_coverage(segment_file, daily_output, res, config, connection=conn)
                logger.info(f"Generated {daily_output.name}")

        # Merge daily files into final aggregates
        results = {}
        for res in resolutions:
            output_file = output_dir / f"h3_coverage_r{res}.parquet"
            merge_h3_daily_coverage(daily_dir, output_file, res, config)
            results[res] = output_file
            logger.info(f"Merged H3 coverage for resolution {res}")

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

    # Atomic write pattern
    temp_file = output_file.with_suffix(".tmp")

    # Prepare SQL parameters
    sql_path = Path(__file__).parent / "sql" / "h3_coverage_metrics.sql"

    params = {
        "segment_file": str(segment_file),
        "output_file": str(temp_file),
        "resolution": resolution,
    }

    # Execute SQL pipeline
    conn = create_configured_connection(config, extensions=["h3"])
    try:
        qck(str(sql_path), params=params, connection=conn)
        temp_file.rename(output_file)
        logger.info(f"Coverage metrics computed: {output_file}")
    except Exception:
        if temp_file.exists():
            temp_file.unlink()
        raise
    finally:
        conn.close()


def compute_dual_incident_metrics(
    incidents_files: list[Path] | Path,
    segments_files: list[Path] | Path,
    output_file: Path,
    resolution: int = 5,
    config: Config | None = None,
) -> None:
    """
    Compute dual incident metrics for H3 cells and incident-to-H3 mapping with per-day processing.

    Processes incident/segment file pairs individually, then merges into final aggregates.
    Uses daily/ subdirectory for per-day outputs, main directory for merged results.

    Generates two outputs:
    1. H3 incident metrics (aggregated statistics per cell)
    2. Incident-to-H3 mapping (lookup table for drill-down queries)

    Args:
        incidents_files: Path to incidents file or list of incidents files
        segments_files: Path to segments file or list of segments files
        output_file: Path to output metrics file (merged)
        resolution: H3 resolution (default: 5)
        config: Configuration object (optional)
    """
    # Normalize to lists
    if isinstance(incidents_files, Path):
        incidents_files = [incidents_files]
    if isinstance(segments_files, Path):
        segments_files = [segments_files]

    if len(incidents_files) != len(segments_files):
        raise ValueError(f"Mismatch: {len(incidents_files)} incident files, {len(segments_files)} segment files")

    if config is None:
        config = Config.from_file(Path("config.toml"))

    output_dir = output_file.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    daily_dir = output_dir / "daily"
    daily_dir.mkdir(exist_ok=True)

    # Apply DuckDB configuration
    conn = create_configured_connection(config, extensions=["h3"])

    try:
        # Process each (incident, segment) pair to daily/ directory
        for incidents_file, segments_file in zip(incidents_files, segments_files, strict=False):
            # Extract date from filename
            date_str = incidents_file.stem.replace("incidents_", "")

            logger.info(f"Processing H3 incidents for {date_str}")

            # Generate daily metrics (atomic write pattern)
            daily_metrics_file = daily_dir / f"h3_incidents_r{resolution}_{date_str}.parquet"
            temp_metrics_file = daily_metrics_file.with_suffix(".tmp")

            # Check staleness
            if (
                daily_metrics_file.exists()
                and daily_metrics_file.stat().st_mtime > incidents_file.stat().st_mtime
                and daily_metrics_file.stat().st_mtime > segments_file.stat().st_mtime
            ):
                logger.debug(f"Skipping {daily_metrics_file.name} (up to date)")
            else:
                try:
                    sql_metrics_path = Path(__file__).parent / "sql" / "h3_incident_metrics.sql"
                    params = {
                        "incidents_file": str(incidents_file),
                        "segments_file": str(segments_file),
                        "output_file": str(temp_metrics_file),
                        "resolution": resolution,
                    }
                    qck(str(sql_metrics_path), params=params, connection=conn)
                    temp_metrics_file.rename(daily_metrics_file)
                    logger.info(f"Generated {daily_metrics_file.name}")
                except Exception:
                    if temp_metrics_file.exists():
                        temp_metrics_file.unlink()
                    raise

            # Generate daily mapping (atomic write pattern)
            daily_mapping_file = daily_dir / f"incident_h3_mapping_r{resolution}_{date_str}.parquet"
            temp_mapping_file = daily_mapping_file.with_suffix(".tmp")

            if (
                daily_mapping_file.exists()
                and daily_mapping_file.stat().st_mtime > incidents_file.stat().st_mtime
                and daily_mapping_file.stat().st_mtime > segments_file.stat().st_mtime
            ):
                logger.debug(f"Skipping {daily_mapping_file.name} (up to date)")
            else:
                try:
                    sql_mapping_path = Path(__file__).parent / "sql" / "incident_h3_mapping.sql"
                    mapping_params = {
                        "incidents_file": str(incidents_file),
                        "segments_file": str(segments_file),
                        "output_file": str(temp_mapping_file),
                        "resolution": resolution,
                    }
                    qck(str(sql_mapping_path), params=mapping_params, connection=conn)
                    temp_mapping_file.rename(daily_mapping_file)
                    logger.info(f"Generated {daily_mapping_file.name}")
                except Exception:
                    if temp_mapping_file.exists():
                        temp_mapping_file.unlink()
                    raise

        # Merge daily files into final aggregates
        merge_h3_daily_incidents(daily_dir, output_file, resolution, config)
        logger.info(f"Merged H3 incidents for resolution {resolution}")

        mapping_file = output_dir / f"incident_h3_mapping_r{resolution}.parquet"
        merge_incident_h3_mapping(daily_dir, mapping_file, resolution, config)
        logger.info(f"Merged incident mapping for resolution {resolution}")

    finally:
        conn.close()


def merge_h3_daily_coverage(
    daily_dir: Path,
    output_file: Path,
    resolution: int,
    config: Config | None = None,
) -> None:
    """
    Merge per-day H3 coverage files into final aggregate.

    Reads daily coverage files, sums counts across days, drops lists.
    Lightweight operation: merges ~1.1M aggregated records vs 1.19B raw points.

    Args:
        daily_dir: Directory containing daily H3 coverage files
        output_file: Path to merged output file
        resolution: H3 resolution (3-7)
        config: Configuration object (optional)
    """
    if resolution not in range(3, 8):
        raise ValueError(f"Resolution must be between 3 and 7, got {resolution}")

    if config is None:
        config = Config.from_file(Path("config.toml"))

    # Build glob pattern for daily files
    daily_pattern = daily_dir / f"h3_coverage_r{resolution}_*.parquet"

    # Atomic write pattern
    temp_file = output_file.with_suffix(".tmp")

    # Execute merge SQL
    sql_path = Path(__file__).parent / "sql" / "h3_coverage_merge.sql"
    params = {
        "daily_pattern": str(daily_pattern),
        "output_file": str(temp_file),
        "resolution": resolution,
    }

    conn = create_configured_connection(config, extensions=["h3"])
    try:
        qck(str(sql_path), params=params, connection=conn)
        temp_file.rename(output_file)
        logger.info(f"Merged H3 coverage for resolution {resolution}: {output_file}")
    except Exception:
        if temp_file.exists():
            temp_file.unlink()
        raise
    finally:
        conn.close()


def merge_h3_daily_incidents(
    daily_dir: Path,
    output_file: Path,
    resolution: int,
    config: Config | None = None,
) -> None:
    """
    Merge per-day H3 incident metrics into final aggregate.

    Reads daily incident files, sums counts, merges emergency type lists,
    recalculates MODE for predominant_emergency_type.

    Args:
        daily_dir: Directory containing daily H3 incident files
        output_file: Path to merged output file
        resolution: H3 resolution (3-7)
        config: Configuration object (optional)
    """
    if resolution not in range(3, 8):
        raise ValueError(f"Resolution must be between 3 and 7, got {resolution}")

    if config is None:
        config = Config.from_file(Path("config.toml"))

    # Build glob pattern for daily files
    daily_pattern = daily_dir / f"h3_incidents_r{resolution}_*.parquet"

    # Atomic write pattern
    temp_file = output_file.with_suffix(".tmp")

    # Execute merge SQL
    sql_path = Path(__file__).parent / "sql" / "h3_incidents_merge.sql"
    params = {
        "daily_pattern": str(daily_pattern),
        "output_file": str(temp_file),
        "resolution": resolution,
    }

    conn = create_configured_connection(config, extensions=["h3"])
    try:
        qck(str(sql_path), params=params, connection=conn)
        temp_file.rename(output_file)
        logger.info(f"Merged H3 incidents for resolution {resolution}: {output_file}")
    except Exception:
        if temp_file.exists():
            temp_file.unlink()
        raise
    finally:
        conn.close()


def merge_incident_h3_mapping(
    daily_dir: Path,
    output_file: Path,
    resolution: int,
    config: Config | None = None,
) -> None:
    """
    Merge per-day incident-to-H3 mapping files into final lookup table.

    Deduplicates (incident_id, h3_cell) pairs across all days.

    Args:
        daily_dir: Directory containing daily incident mapping files
        output_file: Path to merged output file
        resolution: H3 resolution (3-7)
        config: Configuration object (optional)
    """
    if resolution not in range(3, 8):
        raise ValueError(f"Resolution must be between 3 and 7, got {resolution}")

    if config is None:
        config = Config.from_file(Path("config.toml"))

    # Build glob pattern for daily files
    daily_pattern = daily_dir / f"incident_h3_mapping_r{resolution}_*.parquet"

    # Atomic write pattern
    temp_file = output_file.with_suffix(".tmp")

    # Execute merge SQL
    sql_path = Path(__file__).parent / "sql" / "incident_mapping_merge.sql"
    params = {
        "daily_pattern": str(daily_pattern),
        "output_file": str(temp_file),
        "resolution": resolution,
    }

    conn = create_configured_connection(config, extensions=["h3"])
    try:
        qck(str(sql_path), params=params, connection=conn)
        temp_file.rename(output_file)
        logger.info(f"Merged incident mapping for resolution {resolution}: {output_file}")
    except Exception:
        if temp_file.exists():
            temp_file.unlink()
        raise
    finally:
        conn.close()


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

    # Atomic write pattern
    temp_file = output_file.with_suffix(".tmp")

    # Prepare SQL parameters
    sql_path = Path(__file__).parent / "sql" / "h3_incident_by_type.sql"

    params = {
        "incidents_file": str(incidents_file),
        "segments_file": str(segments_file),
        "output_file": str(temp_file),
        "resolution": resolution,
    }

    # Execute SQL pipeline
    conn = create_configured_connection(config, extensions=["h3"])
    try:
        qck(str(sql_path), params=params, connection=conn)
        temp_file.rename(output_file)
        logger.info(f"Incidents aggregated by type: {output_file}")
    except Exception:
        if temp_file.exists():
            temp_file.unlink()
        raise
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

    # Atomic write pattern
    temp_file = output_file.with_suffix(".tmp")

    # Prepare SQL parameters
    sql_path = Path(__file__).parent / "sql" / "h3_visibility_filter.sql"

    params = {
        "aggregates_file": str(aggregates_file),
        "output_file": str(temp_file),
        "min_flights": min_flights,
    }

    # Execute SQL pipeline (no H3 extension needed for filtering)
    conn = create_configured_connection(config)
    try:
        qck(str(sql_path), params=params, connection=conn)
        temp_file.rename(output_file)
        logger.info(f"Visibility thresholds applied: {output_file}")
    except Exception:
        if temp_file.exists():
            temp_file.unlink()
        raise
    finally:
        conn.close()
