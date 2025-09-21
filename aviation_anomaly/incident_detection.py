"""
Incident detection module with quality gates.
Executes SQL pipeline to detect emergency squawks with validation.
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


def detect_incidents(date: datetime.date, segments_dir: Path, output_dir: Path, config: Config) -> Path:
    """Detect emergency incidents from flight segments with quality gates.

    Processes segmented flight data to identify genuine emergency squawks
    (7500/7600/7700) using temporal validation, persistence checks, and
    confidence scoring. Applies debouncing to merge closely-timed incidents.

    Quality Gates:
    1. Temporal: 5+ samples within 60 seconds
    2. Persistence: Emergency must last >45 seconds
    3. Airborne: <30% of samples on ground
    4. Confidence: Minimum score of 50

    Args:
        date: Date to process
        segments_dir: Directory containing segment files
        output_dir: Output directory for incident files
        config: Configuration object with incident parameters

    Returns:
        Path to created incident file

    Raises:
        FileNotFoundError: If segment data doesn't exist
    """
    # Generate unique session ID for temp files
    session_id = uuid4().hex[:8]

    # Setup paths
    input_file = segments_dir / f"segments_{date}.parquet"
    if not input_file.exists():
        raise FileNotFoundError(f"No segments for {date}: {input_file}")

    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create temp directory for DuckDB spilling if needed
    temp_dir = Path(config.duckdb.temp_directory)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Output paths (atomic write pattern)
    final_path = output_dir / f"incidents_{date}.parquet"
    temp_path = output_dir / f".incidents_{session_id}.parquet"

    # SQL parameters
    params = {
        "input_path": str(input_file),
        "output_path": str(temp_path),
        "processing_date": str(date),
    }

    # Create configured DuckDB connection
    conn = create_configured_connection(config)

    try:
        with log_operation(f"detect_incidents_{date}", logger):
            logger.info(f"Processing segments from {input_file}")
            logger.info(
                "Quality gates: 5+ samples in 60s, >45s persistence, <30% ground, "
                f"debounce {config.incidents.debounce_minutes}min"
            )
            logger.info(f"DuckDB config: memory={config.duckdb.memory_limit}, threads={config.duckdb.threads}")

            # Execute the SQL query - writes directly to temp_path via COPY TO
            sql_file = Path(__file__).parent / "sql" / "incident_detection.sql"
            qck(str(sql_file), params=params, connection=conn)

            # Atomic rename
            temp_path.rename(final_path)
            logger.info(f"Incidents written to {final_path}")

    finally:
        conn.close()

    return final_path


def detect_incidents_range(
    start: datetime.date, end: datetime.date, segments_dir: Path, output_dir: Path, config: Config
) -> list[Path]:
    """Detect incidents for multiple days.

    Each day is processed independently with its own DuckDB connection.
    This ensures clean isolation between days and matches the pattern
    used in segmentation.

    Args:
        start: Start date (inclusive)
        end: End date (inclusive)
        segments_dir: Directory containing segment files
        output_dir: Output directory for incident files
        config: Configuration object with incident parameters

    Returns:
        List of created incident files
    """
    results = []
    current = start

    while current <= end:
        try:
            result = detect_incidents(current, segments_dir, output_dir, config)
            results.append(result)
            logger.info(f"Completed {current}: {result}")
        except FileNotFoundError as e:
            logger.warning(f"Skipping {current}: {e}")
        except Exception as e:
            logger.error(f"Failed processing {current}: {e}")
            raise

        current += datetime.timedelta(days=1)

    return results


def analyze_incidents(incident_file: Path, config: Config | None = None) -> dict:
    """Analyze detected incidents for statistics.

    Args:
        incident_file: Path to incident parquet file
        config: Optional configuration object for DuckDB settings

    Returns:
        Dictionary with incident statistics
    """
    if config is None:
        config = Config()

    conn = create_configured_connection(config)

    # Get basic statistics
    stats = conn.execute(
        f"""
        SELECT
            COUNT(*) as total_incidents,
            COUNT(DISTINCT icao24) as unique_aircraft,
            COUNT(CASE WHEN emergency_type = '7500' THEN 1 END) as hijack_count,
            COUNT(CASE WHEN emergency_type = '7600' THEN 1 END) as radio_failure_count,
            COUNT(CASE WHEN emergency_type = '7700' THEN 1 END) as general_emergency_count,
            AVG(duration_seconds) as avg_duration,
            MAX(duration_seconds) as max_duration,
            AVG(confidence_score) as avg_confidence,
            COUNT(CASE WHEN confidence_level = 'HIGH' THEN 1 END) as high_confidence_count,
            COUNT(CASE WHEN has_roller_dial THEN 1 END) as roller_dial_count
        FROM '{incident_file}'
    """
    ).fetchone()

    conn.close()

    if stats is None:
        return {
            "total_incidents": 0,
            "unique_aircraft": 0,
            "hijack_count": 0,
            "radio_failure_count": 0,
            "general_emergency_count": 0,
            "avg_duration_seconds": 0,
            "max_duration_seconds": 0,
            "avg_confidence": 0,
            "high_confidence_count": 0,
            "roller_dial_count": 0,
        }

    return {
        "total_incidents": stats[0],
        "unique_aircraft": stats[1],
        "hijack_count": stats[2],
        "radio_failure_count": stats[3],
        "general_emergency_count": stats[4],
        "avg_duration_seconds": stats[5],
        "max_duration_seconds": stats[6],
        "avg_confidence": stats[7],
        "high_confidence_count": stats[8],
        "roller_dial_count": stats[9],
    }
