"""
Test batched segmentation to ensure it works correctly.
"""

import datetime

import duckdb
import pandas as pd
import pytest

from aviation_anomaly.config import Config
from aviation_anomaly.segmentation import segment_day


@pytest.fixture
def multi_aircraft_data():
    """Create data with multiple aircraft to force batching."""
    data = []

    # Create 5 different aircraft with valid segments
    for aircraft_idx in range(5):
        aircraft_id = f"plane{aircraft_idx:03d}"

        # Each aircraft has 15-minute segment
        for i in range(16):  # 16 points = 15 minutes
            data.append(
                {
                    "icao24": aircraft_id,
                    "time": 1000 + i * 60,
                    "lat": 40.0 + aircraft_idx + i * 0.01,
                    "lon": -74.0,
                    "squawk": "1200",
                    "onground": False,
                    "alert": False,
                }
            )

    df = pd.DataFrame(data)
    return df.sort_values(["icao24", "time"]).reset_index(drop=True)


@pytest.fixture
def small_batch_config():
    """Config with small batch size to force batching."""
    config = Config()
    config.segments.gap_minutes = 20
    config.segments.min_duration_s = 600
    config.segments.min_distance_km = 30.0
    config.segments.batch_size = 2  # Force batching with only 2 aircraft per batch
    config.duckdb.memory_limit = "1GB"
    config.duckdb.threads = 1
    config.duckdb.temp_directory = "/tmp/test_duckdb"
    config.duckdb.max_temp_directory_size = "10GB"
    return config


def test_batched_segmentation(multi_aircraft_data, small_batch_config, tmp_path, monkeypatch):
    """Test that batched segmentation produces correct results."""
    # Setup
    monkeypatch.chdir(tmp_path)
    date = datetime.date(2025, 7, 1)

    # Write test data
    input_file = tmp_path / "data" / "raw" / f"states_{date}.parquet"
    input_file.parent.mkdir(parents=True, exist_ok=True)
    multi_aircraft_data.to_parquet(input_file)

    # Run segmentation with small batch size (should create 3 batches for 5 aircraft)
    output_dir = tmp_path / "data" / "segments"
    result_file = segment_day(date, output_dir, small_batch_config)

    # Verify output exists
    assert result_file.exists()

    # Read results
    conn = duckdb.connect()
    segments = conn.execute(f"SELECT * FROM '{result_file}' ORDER BY icao24, start_time").df()
    conn.close()

    # Should have 5 segments (one per aircraft)
    assert len(segments) == 5
    assert sorted(segments.icao24.unique()) == ["plane000", "plane001", "plane002", "plane003", "plane004"]

    # Each segment should have correct properties
    for _, seg in segments.iterrows():
        assert seg["duration_seconds"] == 15 * 60  # 15 minutes
        assert seg["point_count"] == 16
        assert seg["keep_reason"] == "duration"  # Passes duration filter

    # Verify no batch files remain
    batch_files = list(output_dir.glob(".batch_*.parquet"))
    assert len(batch_files) == 0, "Batch files should be cleaned up"


def test_empty_batch_handling(small_batch_config, tmp_path, monkeypatch):
    """Test handling of empty batches."""
    # Setup
    monkeypatch.chdir(tmp_path)
    date = datetime.date(2025, 7, 1)

    # Create data where only first aircraft has valid segments
    data = []

    # First aircraft: valid segment
    for i in range(12):
        data.append(
            {
                "icao24": "valid001",
                "time": 1000 + i * 60,
                "lat": 40.0 + i * 0.01,
                "lon": -74.0,
                "squawk": "1200",
                "onground": False,
                "alert": False,
            }
        )

    # Second aircraft: too short (will be filtered)
    for i in range(3):
        data.append(
            {
                "icao24": "short002",
                "time": 1000 + i * 60,
                "lat": 35.0,
                "lon": -80.0,
                "squawk": None,
                "onground": False,
                "alert": False,
            }
        )

    df = pd.DataFrame(data)

    # Write test data
    input_file = tmp_path / "data" / "raw" / f"states_{date}.parquet"
    input_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(input_file)

    # Run segmentation
    output_dir = tmp_path / "data" / "segments"
    result_file = segment_day(date, output_dir, small_batch_config)

    # Read results
    conn = duckdb.connect()
    segments = conn.execute(f"SELECT * FROM '{result_file}'").df()
    conn.close()

    # Should have only 1 segment (from valid001)
    assert len(segments) == 1
    assert segments.iloc[0]["icao24"] == "valid001"


def test_batch_size_configuration(multi_aircraft_data, tmp_path, monkeypatch):
    """Test that batch size configuration works correctly."""
    # Setup
    monkeypatch.chdir(tmp_path)
    date = datetime.date(2025, 7, 1)

    # Write test data
    input_file = tmp_path / "data" / "raw" / f"states_{date}.parquet"
    input_file.parent.mkdir(parents=True, exist_ok=True)
    multi_aircraft_data.to_parquet(input_file)

    output_dir = tmp_path / "data" / "segments"

    # Test with different batch sizes
    for batch_size in [1, 3, 10]:
        config = Config()
        config.segments.batch_size = batch_size
        config.duckdb.memory_limit = "1GB"
        config.duckdb.threads = 1
        config.duckdb.temp_directory = "/tmp/test_duckdb"

        # Clear output directory
        if output_dir.exists():
            for f in output_dir.glob("*.parquet"):
                f.unlink()

        # Run segmentation
        result_file = segment_day(date, output_dir, config)

        # Should always produce the same results regardless of batch size
        conn = duckdb.connect()
        segments = conn.execute(f"SELECT * FROM '{result_file}' ORDER BY icao24").df()
        conn.close()

        assert len(segments) == 5, f"Failed with batch_size={batch_size}"
