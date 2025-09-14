"""Tests for data extraction from OpenSky to Parquet."""

import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import duckdb
import pytest

from aviation_anomaly import extraction


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


def test_extract_day_creates_parquet_file(tmp_path, monkeypatch):
    """Test that extraction creates a Parquet file with correct schema."""
    # Mock TrinoQueryEngine to return sample data
    mock_query_result = [
        # Sample state vectors data
        (1704067200, "abc123", "UAL123  ", 40.7128, -74.0060, 10000.0, None, 250.0, 90.0, 0.0, "1234", False, False),
        (1704067260, "abc123", "UAL123  ", 40.7130, -74.0055, 10010.0, None, 250.0, 90.0, 0.5, "1234", False, False),
        (1704067320, "def456", "AAL456  ", 34.0522, -118.2437, 35000.0, None, 450.0, 270.0, 0.0, "5678", False, False),
    ]

    mock_engine = Mock()
    mock_engine.execute.return_value = mock_query_result

    with patch("aviation_anomaly.extraction.TrinoQueryEngine", return_value=mock_engine):
        date = datetime.date(2024, 1, 1)
        output_file = extraction.extract_day(date, tmp_path)

        # Verify file was created
        assert output_file.exists()
        assert output_file.suffix == ".parquet"

        # Verify Parquet file can be read and has correct data
        conn = duckdb.connect()
        result = conn.execute(f"SELECT COUNT(*) FROM '{output_file}'").fetchone()
        assert result is not None
        assert result[0] == 3  # Should have 3 rows

        # Verify schema
        schema = conn.execute(f"DESCRIBE SELECT * FROM '{output_file}'").fetchall()
        column_names = [col[0] for col in schema]
        expected_columns = [
            "time",
            "icao24",
            "callsign",
            "lat",
            "lon",
            "baroaltitude",
            "geoaltitude",
            "velocity",
            "heading",
            "vertrate",
            "squawk",
            "onground",
            "alert",
        ]
        assert column_names == expected_columns
