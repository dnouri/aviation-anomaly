"""Data extraction from OpenSky to Parquet with DuckDB streaming."""

import datetime
import logging
from pathlib import Path

import duckdb
from tqdm import tqdm

from aviation_anomaly.data_access import TrinoQueryEngine
from aviation_anomaly.logging import log_operation

logger = logging.getLogger(__name__)


def extract_day(date: datetime.date, output_dir: Path) -> Path:
    """Extract one day of OpenSky data to Parquet.

    Streams data from Trino through DuckDB to Parquet without loading
    entire dataset into memory. Handles ~500M rows per day efficiently.

    Args:
        date: Date to extract (UTC)
        output_dir: Directory for output Parquet files

    Returns:
        Path to the created Parquet file
    """
    # Minimal validation
    if date > datetime.date.today():
        raise ValueError(f"Cannot extract future date: {date}")
    if date < datetime.date(2016, 1, 1):
        raise ValueError(f"Date before OpenSky data availability: {date}")

    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build query for all 24 hour partitions of the day
    start_ts = int(datetime.datetime.combine(date, datetime.time.min).timestamp())
    end_ts = start_ts + 86400  # 24 hours later

    query = f"""
    SELECT
        time,
        icao24,
        callsign,
        lat,
        lon,
        baroaltitude,
        geoaltitude,
        velocity,
        heading,
        vertrate,
        squawk,
        onground,
        alert
    FROM minio.osky.state_vectors_data4
    WHERE hour >= {start_ts}
      AND hour < {end_ts}
      AND lat IS NOT NULL
      AND lon IS NOT NULL
    ORDER BY time
    """

    logger.info(f"Extracting data for {date} (timestamps {start_ts} to {end_ts})")

    with log_operation(f"extract_day_{date.isoformat()}", logger):
        # Execute query via Trino
        engine = TrinoQueryEngine()
        results = engine.execute(query)

        # Stream results through DuckDB to Parquet
        conn = duckdb.connect()

        # Create table with proper schema
        conn.execute("""
            CREATE TABLE states (
                time BIGINT,
                icao24 VARCHAR,
                callsign VARCHAR,
                lat DOUBLE,
                lon DOUBLE,
                baroaltitude DOUBLE,
                geoaltitude DOUBLE,
                velocity DOUBLE,
                heading DOUBLE,
                vertrate DOUBLE,
                squawk VARCHAR,
                onground BOOLEAN,
                alert BOOLEAN
            )
        """)

        # Stream data in batches for memory efficiency
        batch_size = 10000
        batch = []
        row_count = 0

        # Create progress bar
        pbar = tqdm(desc=f"Processing {date}", unit=" rows", unit_scale=True)

        for row in results:
            batch.append(row)
            if len(batch) >= batch_size:
                conn.executemany("INSERT INTO states VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", batch)
                row_count += len(batch)
                pbar.update(len(batch))
                batch = []

        # Insert remaining rows
        if batch:
            conn.executemany("INSERT INTO states VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", batch)
            row_count += len(batch)
            pbar.update(len(batch))

        pbar.close()

        # Write to Parquet
        output_file = output_dir / f"states_{date.isoformat()}.parquet"
        conn.execute(f"""
            COPY states TO '{output_file}' (FORMAT PARQUET, COMPRESSION 'snappy')
        """)

        # Get final statistics
        stats = conn.execute("SELECT COUNT(*) as count FROM states").fetchone()
        conn.close()

        final_count = stats[0] if stats else 0
        logger.info(f"Extracted {final_count:,} rows to {output_file}")

        return output_file


def extract_date_range(from_date: datetime.date, to_date: datetime.date, output_dir: Path) -> list[Path]:
    """Extract multiple days of data.

    Args:
        from_date: Start date (inclusive)
        to_date: End date (inclusive)
        output_dir: Directory for output Parquet files

    Returns:
        List of created Parquet files
    """
    if from_date > to_date:
        raise ValueError(f"from_date ({from_date}) must be before to_date ({to_date})")

    output_files = []
    total_days = (to_date - from_date).days + 1

    # Progress bar for days
    days_pbar = tqdm(total=total_days, desc="Extracting days", unit="day", position=0, leave=True)

    current_date = from_date
    while current_date <= to_date:
        output_file = extract_day(current_date, output_dir)
        output_files.append(output_file)
        days_pbar.update(1)
        current_date += datetime.timedelta(days=1)

    days_pbar.close()

    return output_files
