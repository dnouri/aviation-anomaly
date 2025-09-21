"""
Minimal flight segmentation module.
Executes SQL pipeline for gap-based segmentation directly via qck.
"""

import datetime
import logging
from pathlib import Path
from uuid import uuid4

from qck import qck

from aviation_anomaly.config import Config
from aviation_anomaly.data_access import create_configured_connection
from aviation_anomaly.logging import log_operation

logger = logging.getLogger(__name__)


def segment_day(date: datetime.date, output_dir: Path, config: Config) -> Path:
    """Segment one day of flight data using SQL pipeline.

    Reads raw ADS-B data, detects segments based on time gaps,
    calculates distances, and filters based on config criteria.

    Args:
        date: Date to process
        output_dir: Output directory for segment files
        config: Configuration object with segment parameters

    Returns:
        Path to created segment file

    Raises:
        FileNotFoundError: If input data doesn't exist
    """
    # Generate unique session ID for temp files
    session_id = uuid4().hex[:8]

    # Setup paths
    input_file = Path(f"data/raw/states_{date}.parquet")
    if not input_file.exists():
        raise FileNotFoundError(f"No data for {date}: {input_file}")

    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create temp directory for DuckDB spilling if needed
    temp_dir = Path(config.duckdb.temp_directory)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Output paths (atomic write pattern)
    final_path = output_dir / f"segments_{date}.parquet"
    temp_path = output_dir / f".segments_{session_id}.parquet"

    # SQL parameters (no DuckDB config if using connection)
    params = {
        "input_path": str(input_file),
        "output_path": str(temp_path),
        "gap_threshold": config.segments.gap_minutes * 60,
        "min_duration": config.segments.min_duration_s,
        "min_distance": config.segments.min_distance_km,
    }

    # Create configured DuckDB connection
    conn = create_configured_connection(config)

    try:
        with log_operation(f"segment_{date}", logger):
            logger.info(f"Processing {input_file}")
            logger.info(
                f"Parameters: gap={config.segments.gap_minutes}min, "
                f"duration≥{config.segments.min_duration_s}s, "
                f"distance≥{config.segments.min_distance_km}km"
            )
            logger.info(f"DuckDB config: memory={config.duckdb.memory_limit}, threads={config.duckdb.threads}")

            # Execute the SQL query - writes directly to temp_path via COPY TO
            sql_file = Path(__file__).parent / "sql" / "segment_pipeline.sql"
            qck(str(sql_file), params=params, connection=conn)

            # Atomic rename
            temp_path.rename(final_path)
            logger.info(f"Segments written to {final_path}")

    finally:
        conn.close()

    return final_path


def segment_date_range(start: datetime.date, end: datetime.date, output_dir: Path, config: Config) -> list[Path]:
    """Segment multiple days of flight data.

    Args:
        start: Start date (inclusive)
        end: End date (inclusive)
        output_dir: Output directory for segment files
        config: Configuration object with segment parameters

    Returns:
        List of created segment files

    Raises:
        FileNotFoundError: If any input data doesn't exist
    """
    output_files = []
    current = start

    while current <= end:
        try:
            output_file = segment_day(current, output_dir, config)
            output_files.append(output_file)
        except FileNotFoundError as e:
            logger.warning(f"Skipping {current}: {e}")

        current += datetime.timedelta(days=1)

    if not output_files:
        raise FileNotFoundError(f"No data found for date range {start} to {end}")

    return output_files
