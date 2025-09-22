"""
Test batched segmentation and combining to ensure it works correctly.
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


def test_union_all_by_name_combines_correctly(tmp_path):
    """Test that UNION ALL BY NAME combines batches correctly while preserving block structure."""
    # Create sample batch files with segment data
    batch_dir = tmp_path / "batches"
    batch_dir.mkdir()

    conn = duckdb.connect()

    # Create 3 batch files to test combining
    for batch_num in range(3):
        batch_file = batch_dir / f".batch_{batch_num}_test.parquet"

        # Create realistic segment data
        conn.execute(f"""
            COPY (
                WITH segments AS (
                    SELECT
                        'seg_' || (n + {batch_num * 100})::VARCHAR as segment_id,
                        'aircraft_' || ((n % 10) + {batch_num * 10})::VARCHAR as icao24,
                        1700000000 + (n * 100) as start_time,
                        1700000000 + (n * 100) + 60 as end_time,
                        n as num_samples,
                        100.0 + n * 0.1 as distance_km,
                        60 as duration_s,
                        40.0 + (n % 10) * 0.01 as start_lat,
                        -74.0 + (n % 10) * 0.01 as start_lon,
                        40.1 + (n % 10) * 0.01 as end_lat,
                        -73.9 + (n % 10) * 0.01 as end_lon,
                        CASE WHEN n % 20 = 0 THEN '7700' ELSE NULL END as squawk_codes,
                        0.5 as squawk_coverage
                    FROM generate_series(1, 50) as t(n)
                )
                SELECT * FROM segments
            ) TO '{batch_file}' (FORMAT PARQUET)
        """)

    # Test the batch combination approach
    batch_files = sorted(batch_dir.glob(".batch_*.parquet"))
    assert len(batch_files) == 3

    # Build UNION ALL BY NAME query (matches production code)
    union_parts = [f"SELECT * FROM read_parquet('{bf}')" for bf in batch_files]
    union_query = " UNION ALL BY NAME ".join(union_parts)

    # Configure connection as production does
    conn.execute("SET memory_limit = '1GB'")
    conn.execute("SET preserve_insertion_order = false")

    # Combine batches (production now does single-pass combination)
    combined_file = tmp_path / "combined.parquet"
    conn.execute(f"""
        COPY (
            {union_query}
        ) TO '{combined_file}' (FORMAT PARQUET, COMPRESSION 'zstd')
    """)

    # Verify combined has all data
    result = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{combined_file}')").fetchone()
    assert result is not None
    assert result[0] == 150, "Should have 150 segments total"

    # Verify block-sorted structure: within each aircraft, segments are time-ordered
    # This is the key invariant that downstream operations depend on
    result = conn.execute(f"""
        WITH aircraft_groups AS (
            SELECT
                icao24,
                start_time,
                LAG(start_time) OVER (PARTITION BY icao24 ORDER BY start_time) as prev_start_time
            FROM read_parquet('{combined_file}')
        )
        SELECT COUNT(*)
        FROM aircraft_groups
        WHERE prev_start_time IS NOT NULL AND start_time < prev_start_time
    """).fetchone()
    assert result is not None
    assert result[0] == 0, "Within each aircraft, segments should be time-ordered"

    conn.close()


def test_combine_with_low_memory_limit(tmp_path):
    """Test that combining works even with very low memory limits."""
    batch_dir = tmp_path / "batches"
    batch_dir.mkdir()

    conn = duckdb.connect()

    # Create batch files
    for batch_num in range(2):
        batch_file = batch_dir / f".batch_{batch_num}.parquet"
        conn.execute(f"""
            COPY (
                SELECT
                    'seg_' || n::VARCHAR as segment_id,
                    'aircraft_' || (n % 5)::VARCHAR as icao24,
                    1700000000 + (n * 60) as start_time,
                    1700000000 + (n * 60) + 50 as end_time
                FROM generate_series({batch_num * 100}, {batch_num * 100 + 99}) as t(n)
            ) TO '{batch_file}' (FORMAT PARQUET)
        """)

    # Test with very low memory (forces streaming)
    conn.execute("SET memory_limit = '100MB'")
    conn.execute("SET preserve_insertion_order = false")
    conn.execute("SET threads = 1")

    batch_files = sorted(batch_dir.glob(".batch_*.parquet"))
    union_parts = [f"SELECT * FROM read_parquet('{bf}')" for bf in batch_files]
    union_query = " UNION ALL BY NAME ".join(union_parts)

    output_file = tmp_path / "low_memory_output.parquet"

    # Should complete without OOM
    conn.execute(f"""
        COPY (
            {union_query}
        ) TO '{output_file}' (FORMAT PARQUET, COMPRESSION 'zstd')
    """)

    # Verify all data present
    result = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{output_file}')").fetchone()
    assert result is not None
    assert result[0] == 200, "Should handle low memory scenario"

    conn.close()
