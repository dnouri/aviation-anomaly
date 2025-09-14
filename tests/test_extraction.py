"""Tests for data extraction from OpenSky to Parquet."""

import datetime
from pathlib import Path

import duckdb
import pytest

from aviation_anomaly import extraction


class MockTrinoEngine:
    """Mock for TrinoQueryEngine."""
    def __init__(self):
        self.execute_return_value = []

    def execute(self, query):
        if callable(self.execute_return_value):
            return self.execute_return_value(query)
        return self.execute_return_value


class MockExtractHour:
    """Mock for tracking extract_hour calls."""
    def __init__(self):
        self.call_count = 0
        self.call_args_list = []

    def __call__(self, date, hour, output_dir):
        self.call_count += 1
        self.call_args_list.append((date, hour, output_dir))
        return output_dir / f"states_{date.isoformat()}_{hour:02d}.parquet"


class MockDuckDBConnection:
    """Mock for DuckDB connection."""
    def __init__(self, row_count=1000):
        self.row_count = row_count

    def execute(self, query):
        return self

    def fetchone(self):
        return (self.row_count,)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def mock_trino_engine(monkeypatch, request):
    """Automatically mock TrinoQueryEngine to prevent network access.

    Returns a mock that can be configured in tests.
    Use @pytest.mark.no_mock_trino to disable for specific tests.
    """
    if "no_mock_trino" in request.keywords:
        # Skip mocking for tests that need real Trino access
        yield None
        return

    mock_engine = MockTrinoEngine()
    monkeypatch.setattr("aviation_anomaly.extraction.TrinoQueryEngine", lambda: mock_engine)

    yield mock_engine  # Tests can configure this mock as needed


def test_extract_day_exists():
    """Test that extract_day function exists."""
    assert hasattr(extraction, "extract_day")


def test_extraction_rejects_future_date():
    """Test that extraction fails for future dates."""
    future_date = datetime.date(2030, 1, 1)
    output_dir = Path("/tmp/test_extraction")

    with pytest.raises(ValueError, match="Cannot extract future date"):
        extraction.extract_day(future_date, output_dir)


def test_extraction_rejects_pre_opensky_date():
    """Test that extraction fails for dates before OpenSky data availability."""
    # OpenSky data starts around 2016
    old_date = datetime.date(2010, 1, 1)
    output_dir = Path("/tmp/test_extraction")

    with pytest.raises(ValueError, match="Date before OpenSky data availability"):
        extraction.extract_day(old_date, output_dir)


def test_extract_day_creates_parquet_file(tmp_path, mock_trino_engine, monkeypatch):
    """Test that extraction creates a Parquet file with correct schema."""
    # Configure the mock to return sample data only for hour 0
    def mock_execute(query):
        # Only return data for the first hour query
        if "hour = 1704067200" in query:  # Hour 0 of 2024-01-01
            return [
                # Sample state vectors data: time, icao24, callsign, lat, lon, squawk, onground, alert
                (1704067200, "abc123", "UAL123  ", 40.7128, -74.0060, "1234", False, False),
                (1704067260, "abc123", "UAL123  ", 40.7130, -74.0055, "1234", False, False),
                (1704067320, "def456", "AAL456  ", 34.0522, -118.2437, "5678", False, False),
            ]
        return []  # Other hours have no data

    mock_trino_engine.execute_return_value = mock_execute

    date = datetime.date(2024, 1, 1)
    output_file = extraction.extract_day(date, tmp_path)

    # Verify file was created
    assert output_file.exists()
    assert output_file.suffix == ".parquet"

    # Verify Parquet file can be read and has correct data
    conn = duckdb.connect()
    result = conn.execute(f"SELECT COUNT(*) FROM '{output_file}'").fetchone()
    assert result is not None
    assert result[0] == 3  # Should have 3 rows (only from hour 0)

    # Verify schema
    schema = conn.execute(f"DESCRIBE SELECT * FROM '{output_file}'").fetchall()
    column_names = [col[0] for col in schema]
    expected_columns = [
        "time",
        "icao24",
        "callsign",
        "lat",
        "lon",
        "squawk",
        "onground",
        "alert",
    ]
    assert column_names == expected_columns


def test_extract_day_skips_existing_hour_files(tmp_path, mock_trino_engine, monkeypatch):
    """Test that extract_day skips hours that already have complete files."""
    date = datetime.date(2024, 1, 1)

    # Create some existing hour files (hours 0, 1, 2)
    for hour in [0, 1, 2]:
        existing_file = tmp_path / f"states_{date.isoformat()}_{hour:02d}.parquet"
        # Create a minimal valid parquet file
        conn = duckdb.connect()
        conn.execute("""
            CREATE TABLE test AS
            SELECT 1704067200 as time, 'abc123' as icao24, 'TEST' as callsign,
                   0.0 as lat, 0.0 as lon, '0000' as squawk,
                   false as onground, false as alert
        """)
        conn.execute(f"COPY test TO '{existing_file}' (FORMAT PARQUET)")
        conn.close()

    # Mock extract_hour for the hours that need extraction
    mock_extract_hour = MockExtractHour()
    monkeypatch.setattr("aviation_anomaly.extraction.extract_hour", mock_extract_hour)

    # Call extract_day - should skip hours 0, 1, 2
    extraction.extract_day(date, tmp_path)

    # Should have been called 21 times (hours 3-23), not 24
    assert mock_extract_hour.call_count == 21

    # Verify it wasn't called for hours 0, 1, 2
    called_hours = [args[1] for args in mock_extract_hour.call_args_list]
    assert 0 not in called_hours
    assert 1 not in called_hours
    assert 2 not in called_hours
    assert set(called_hours) == set(range(3, 24))


def test_extract_day_force_redownload_overwrites(tmp_path, mock_trino_engine, monkeypatch):
    """Test that force_redownload=True re-extracts even existing files."""
    date = datetime.date(2024, 1, 1)

    # Create an existing hour file
    existing_file = tmp_path / f"states_{date.isoformat()}_00.parquet"
    conn = duckdb.connect()
    conn.execute("""
        CREATE TABLE test AS
        SELECT 1704067200 as time, 'old' as icao24, 'OLD' as callsign,
               0.0 as lat, 0.0 as lon, '0000' as squawk,
               false as onground, false as alert
    """)
    conn.execute(f"COPY test TO '{existing_file}' (FORMAT PARQUET)")
    conn.close()

    # Mock extract_hour
    mock_extract_hour = MockExtractHour()
    monkeypatch.setattr("aviation_anomaly.extraction.extract_hour", mock_extract_hour)

    # Call with force_redownload=True
    extraction.extract_day(date, tmp_path, force_redownload=True)

    # Should have been called for all 24 hours
    assert mock_extract_hour.call_count == 24
    called_hours = [args[1] for args in mock_extract_hour.call_args_list]
    assert set(called_hours) == set(range(24))


def test_extract_day_skips_when_daily_file_exists(tmp_path, mock_trino_engine, monkeypatch):
    """Test that extract_day skips extraction when daily file already exists."""
    date = datetime.date(2025, 1, 1)

    # Create existing daily file (simulating previous successful extraction)
    daily_file = tmp_path / f"states_{date.isoformat()}.parquet"

    # Create a valid Parquet file with DuckDB
    conn = duckdb.connect()
    conn.execute("""
        CREATE TABLE test_data AS
        SELECT
            1735689600 + i AS time,
            'abc' || i AS icao24,
            'CALL' || i AS callsign,
            40.0 + (i * 0.001) AS lat,
            -74.0 + (i * 0.001) AS lon,
            '7700' AS squawk,
            false AS onground,
            false AS alert
        FROM generate_series(1, 100) AS t(i)
    """)
    conn.execute(f"COPY test_data TO '{daily_file}' (FORMAT PARQUET)")
    conn.close()

    # Mock extract_hour to track if it's called (it shouldn't be)
    mock_extract = MockExtractHour()
    monkeypatch.setattr("aviation_anomaly.extraction.extract_hour", mock_extract)

    # Call without force_redownload - should skip
    result = extraction.extract_day(date, tmp_path, force_redownload=False)

    # Should return existing daily file without calling extract_hour
    assert result == daily_file
    assert mock_extract.call_count == 0  # No hourly extractions should occur


def test_extract_day_re_extracts_with_force_redownload_even_if_daily_exists(tmp_path, mock_trino_engine, monkeypatch):
    """Test that force_redownload=True re-extracts even when daily file exists."""
    date = datetime.date(2025, 1, 1)

    # Create existing daily file
    daily_file = tmp_path / f"states_{date.isoformat()}.parquet"
    conn = duckdb.connect()
    conn.execute("""
        CREATE TABLE test_data AS
        SELECT 1 AS time, 'old' AS icao24
    """)
    conn.execute(f"COPY test_data TO '{daily_file}' (FORMAT PARQUET)")
    conn.close()

    # Mock extract_hour to track calls
    mock_extract = MockExtractHour()
    monkeypatch.setattr("aviation_anomaly.extraction.extract_hour", mock_extract)

    # Mock DuckDB for consolidation
    monkeypatch.setattr("duckdb.connect", lambda: MockDuckDBConnection())

    # Call with force_redownload=True
    extraction.extract_day(date, tmp_path, force_redownload=True)

    # Should re-extract all hours despite daily file existing
    assert mock_extract.call_count == 24  # All 24 hours should be extracted
