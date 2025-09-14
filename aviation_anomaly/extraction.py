"""Data extraction from OpenSky to Parquet with DuckDB streaming."""

import datetime
import logging
from pathlib import Path

import duckdb

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

    Raises:
        ValueError: If date is invalid (future or before OpenSky availability)
        RuntimeError: If extraction fails
    """
    # Validate date
    today = datetime.date.today()
    if date > today:
        raise ValueError(f"Cannot extract future date: {date}")

    # OpenSky data starts around 2016
    opensky_start = datetime.date(2016, 1, 1)
    if date < opensky_start:
        raise ValueError(f"Date before OpenSky data availability: {date}")

    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build query for all 24 hour partitions of the day
    # Convert date to Unix timestamp for hour partitions
    start_ts = int(datetime.datetime.combine(date, datetime.time.min).timestamp())
    end_ts = start_ts + 86400  # 24 hours later

    # Build SQL query for state_vectors_data4 with hour partitions
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
        try:
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

            for row in results:
                batch.append(row)
                if len(batch) >= batch_size:
                    # Insert batch
                    conn.executemany("INSERT INTO states VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", batch)
                    row_count += len(batch)
                    if row_count % 100000 == 0:
                        logger.info(f"Processed {row_count:,} rows...")
                    batch = []

            # Insert remaining rows
            if batch:
                conn.executemany("INSERT INTO states VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", batch)
                row_count += len(batch)

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

        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            raise RuntimeError(f"Failed to extract data for {date}: {e}") from e
