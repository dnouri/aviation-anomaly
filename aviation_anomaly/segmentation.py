"""
Flight segmentation module with automatic batching.
Processes data in controlled batches to avoid memory issues.
"""

import datetime
import logging
from pathlib import Path
from uuid import uuid4

from qck import qck
from tqdm import tqdm

from aviation_anomaly.config import Config
from aviation_anomaly.data_access import create_configured_connection
from aviation_anomaly.logging import log_operation

logger = logging.getLogger(__name__)


def get_aircraft_count(input_path: Path, config: Config | None = None) -> int:
    """Get count of unique aircraft in the data.

    Args:
        input_path: Path to input parquet file
        config: Optional configuration object for DuckDB settings

    Returns:
        Number of unique aircraft
    """
    if config is None:
        config = Config()

    conn = create_configured_connection(config)
    try:
        result = conn.execute(f"""
            SELECT COUNT(DISTINCT icao24)
            FROM read_parquet('{input_path}')
        """).fetchone()
        return result[0] if result else 0
    finally:
        conn.close()


def segment_day(date: datetime.date, output_dir: Path, config: Config) -> Path:
    """Segment one day of flight data using batched SQL pipeline.

    Always processes data in batches to control memory usage.
    Batch size is configurable via config.segments.batch_size.

    Output Structure:
        The output file contains block-sorted data:
        - Each batch's segments are sorted by (icao24, start_time)
        - All segments for a given aircraft are in the same batch
        - Batches themselves are not globally ordered
        This structure is optimal for downstream operations that process
        segments independently or by geographic location.

    Args:
        date: Date to process
        output_dir: Output directory for segment files
        config: Configuration object with segment parameters

    Returns:
        Path to created segment file

    Raises:
        FileNotFoundError: If input data doesn't exist
    """
    # Setup paths
    input_file = Path(f"data/raw/states_{date}.parquet")
    if not input_file.exists():
        raise FileNotFoundError(f"No data for {date}: {input_file}")

    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create temp directory for DuckDB spilling if needed
    temp_dir = Path(config.duckdb.temp_directory)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Final output path
    final_path = output_dir / f"segments_{date}.parquet"

    with log_operation(f"segment_{date}", logger):
        logger.info(f"Processing {input_file}")
        logger.info(
            f"Parameters: gap={config.segments.gap_minutes}min, "
            f"duration≥{config.segments.min_duration_s}s, "
            f"distance≥{config.segments.min_distance_km}km, "
            f"batch_size={config.segments.batch_size}"
        )
        logger.info(f"DuckDB config: memory={config.duckdb.memory_limit}, threads={config.duckdb.threads}")

        # Get aircraft count to determine number of batches
        # Note: The SQL now uses volume-based batching, so actual batch distribution
        # will be balanced by data points, not just aircraft count
        aircraft_count = get_aircraft_count(input_file, config)
        if aircraft_count == 0:
            raise RuntimeError("No aircraft found in input data")
        num_batches = (aircraft_count + config.segments.batch_size - 1) // config.segments.batch_size
        logger.info(f"Found {aircraft_count} aircraft, processing in {num_batches} volume-balanced batches")

        # Create configured DuckDB connection
        conn = create_configured_connection(config)

        # Process batches
        batch_files = []
        sql_file = Path(__file__).parent / "sql" / "segment_pipeline.sql"

        try:
            # Use tqdm for progress tracking
            with tqdm(total=num_batches, desc=f"Processing {date}", unit="batch") as pbar:
                for batch_num in range(num_batches):
                    # Generate unique temp file for this batch
                    session_id = uuid4().hex[:8]
                    batch_path = output_dir / f".batch_{batch_num}_{session_id}.parquet"

                    # SQL parameters for this batch (no DuckDB config needed)
                    params = {
                        "input_path": str(input_file),
                        "output_path": str(batch_path),
                        "batch_size": config.segments.batch_size,
                        "batch_number": batch_num,
                        "gap_threshold": config.segments.gap_minutes * 60,
                        "min_duration": config.segments.min_duration_s,
                        "min_distance": config.segments.min_distance_km,
                    }

                    try:
                        # Execute the SQL query for this batch using the shared connection
                        qck(str(sql_file), params=params, connection=conn)
                        batch_files.append(batch_path)
                        pbar.update(1)
                        pbar.set_postfix({"batch": f"{batch_num + 1}/{num_batches}"})
                    except Exception as e:
                        # Clean up any batch files on error
                        for bf in batch_files:
                            if bf.exists():
                                bf.unlink()
                        raise RuntimeError(f"Failed on batch {batch_num}: {e}") from e
        finally:
            # Always close the connection
            conn.close()

        # Combine all batch files into final output
        logger.info(f"Combining {len(batch_files)} batch files")

        # Build UNION ALL BY NAME query for robust schema handling
        # This approach handles any minor schema differences between batches
        union_parts = [f"SELECT * FROM read_parquet('{bf}')" for bf in batch_files]
        union_query = " UNION ALL BY NAME ".join(union_parts)

        # Create new connection for combining with optimized settings
        combine_conn = create_configured_connection(config)
        # Additional optimization for large combines
        combine_conn.execute("SET preserve_insertion_order = false")

        # Atomic write pattern for combining batches
        temp_final_path = final_path.with_suffix(".tmp")

        # Combine pre-sorted batches into final output
        # Note: Output is block-sorted - each batch's data remains internally sorted
        # by (icao24, start_time), but batches themselves are not globally ordered.
        # This structure is sufficient for downstream operations that process segments
        # independently or by geographic location (H3 cells).
        logger.info(f"Combining {len(batch_files)} pre-sorted batch files using UNION ALL BY NAME...")
        try:
            combine_conn.execute(f"""
                COPY (
                    {union_query}
                ) TO '{temp_final_path}' (FORMAT PARQUET, COMPRESSION 'zstd')
            """)
            temp_final_path.rename(final_path)
            logger.info("Batch combination completed successfully")
        except Exception:
            if temp_final_path.exists():
                temp_final_path.unlink()
            raise
        finally:
            combine_conn.close()

        # Clean up batch files
        for batch_file in batch_files:
            if batch_file.exists():
                batch_file.unlink()

        logger.info(f"Segments written to {final_path}")

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
