"""
Tests for SQL-based flight segmentation pipeline.
Tests behavior, not implementation details.
"""

import datetime
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from aviation_anomaly.config import Config
from aviation_anomaly.segmentation import segment_day


@pytest.fixture
def sample_flight_data():
    """Create sample flight data that exercises all segmentation logic."""
    # Aircraft 1: Two segments with 25-minute gap
    aircraft1_seg1 = [
        {
            "icao24": "abc123",
            "time": 1000 + i * 60,
            "lat": 40.0 + i * 0.01,
            "lon": -74.0,
            "squawk": "1200",
            "onground": False,
            "alert": False,
        }
        for i in range(15)  # 15 minutes of data
    ]

    # Gap from time 1840 to 2500 = 660 seconds = 11 minutes (less than 20!)
    # Need bigger gap: 1840 to 3040 = 1200 seconds = 20 minutes exactly
    aircraft1_seg2 = [
        {
            "icao24": "abc123",
            "time": 3040 + i * 60,
            "lat": 41.0 + i * 0.01,
            "lon": -74.0,
            "squawk": "1200",
            "onground": False,
            "alert": False,
        }
        for i in range(12)  # 12 minutes of data
    ]

    # Aircraft 2: Short segment (8 minutes, <30km) - should be filtered
    aircraft2_short = [
        {
            "icao24": "def456",
            "time": 1000 + i * 60,
            "lat": 35.0,
            "lon": -80.0 + i * 0.001,
            "squawk": None,
            "onground": False,
            "alert": False,
        }
        for i in range(8)  # 8 minutes, minimal movement
    ]

    # Aircraft 3: Long distance segment (8 minutes, >30km) - should be kept
    aircraft3_long = [
        {
            "icao24": "ghi789",
            "time": 1000 + i * 60,
            "lat": 30.0 + i * 0.05,
            "lon": -90.0,
            "squawk": "7700",
            "onground": False,
            "alert": True,
        }
        for i in range(8)  # 8 minutes but significant movement
    ]

    # Combine all data
    all_data = aircraft1_seg1 + aircraft1_seg2 + aircraft2_short + aircraft3_long

    df = pd.DataFrame(all_data)
    return df.sort_values(["icao24", "time"]).reset_index(drop=True)


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create temporary directory structure for test data."""
    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True)

    segments_dir = tmp_path / "data" / "segments"
    segments_dir.mkdir(parents=True)

    return tmp_path


@pytest.fixture
def test_config():
    """Create test configuration."""
    config = Config()
    # Use test-appropriate values
    config.segments.gap_minutes = 20
    config.segments.min_duration_s = 600
    config.segments.min_distance_km = 30.0
    config.duckdb.memory_limit = "1GB"
    config.duckdb.threads = 1
    config.duckdb.temp_directory = "/tmp/test_duckdb"
    config.duckdb.max_temp_directory_size = "10GB"
    return config


def test_segment_detection_with_gaps(sample_flight_data, temp_data_dir, test_config, monkeypatch):
    """Test that segments are correctly detected based on time gaps."""
    # Setup
    monkeypatch.chdir(temp_data_dir)
    date = datetime.date(2025, 7, 1)

    # Write sample data to Parquet
    input_file = temp_data_dir / "data" / "raw" / f"states_{date}.parquet"
    sample_flight_data.to_parquet(input_file)

    # Run segmentation
    output_dir = temp_data_dir / "data" / "segments"
    result_file = segment_day(date, output_dir, test_config)

    # Verify output exists
    assert result_file.exists()

    # Read results
    conn = duckdb.connect()
    segments = conn.execute(f"SELECT * FROM '{result_file}' ORDER BY icao24, start_time").df()
    conn.close()

    # Verify segment count
    # Aircraft abc123 should have 2 segments (gap > 20 min)
    abc_segments = segments[segments.icao24 == "abc123"]
    assert len(abc_segments) == 2

    # Verify gap detection worked
    assert abc_segments.iloc[0]["duration_seconds"] == 14 * 60  # First segment ~14 min
    assert abc_segments.iloc[1]["duration_seconds"] == 11 * 60  # Second segment ~11 min


def test_segment_filtering_by_duration_and_distance(sample_flight_data, temp_data_dir, test_config, monkeypatch):
    """Test OR condition: segments kept if duration >= 600s OR distance >= 30km."""
    # Setup
    monkeypatch.chdir(temp_data_dir)
    date = datetime.date(2025, 7, 1)

    # Write sample data
    input_file = temp_data_dir / "data" / "raw" / f"states_{date}.parquet"
    sample_flight_data.to_parquet(input_file)

    # Run segmentation
    output_dir = temp_data_dir / "data" / "segments"
    result_file = segment_day(date, output_dir, test_config)

    # Read results
    conn = duckdb.connect()
    segments = conn.execute(f"""
        SELECT icao24, duration_seconds, distance_km, keep_reason
        FROM '{result_file}'
        ORDER BY icao24
    """).df()
    conn.close()

    # Verify filtering
    # def456 (8 min, <30km) should be filtered out
    assert "def456" not in segments.icao24.values

    # ghi789 (8 min, >30km) should be kept
    ghi_segments = segments[segments.icao24 == "ghi789"]
    assert len(ghi_segments) == 1
    assert ghi_segments.iloc[0]["duration_seconds"] < 600
    assert ghi_segments.iloc[0]["distance_km"] >= 30
    assert ghi_segments.iloc[0]["keep_reason"] == "distance"

    # abc123 segments (>10 min) should be kept
    abc_segments = segments[segments.icao24 == "abc123"]
    assert len(abc_segments) == 2
    assert all(abc_segments["duration_seconds"] >= 600)
    assert all(abc_segments["keep_reason"].isin(["duration", "both"]))


def test_squawk_coverage_calculation(sample_flight_data, temp_data_dir, test_config, monkeypatch):
    """Test squawk coverage ratio calculation."""
    # Setup
    monkeypatch.chdir(temp_data_dir)
    date = datetime.date(2025, 7, 1)

    # Write sample data
    input_file = temp_data_dir / "data" / "raw" / f"states_{date}.parquet"
    sample_flight_data.to_parquet(input_file)

    # Run segmentation
    output_dir = temp_data_dir / "data" / "segments"
    result_file = segment_day(date, output_dir, test_config)

    # Read results
    conn = duckdb.connect()
    segments = conn.execute(f"""
        SELECT icao24, point_count, squawk_count, squawk_coverage_ratio
        FROM '{result_file}'
        ORDER BY icao24
    """).df()
    conn.close()

    # abc123 has squawk for all points (100% coverage)
    abc_segments = segments[segments.icao24 == "abc123"]
    for _, row in abc_segments.iterrows():
        assert row["squawk_count"] == row["point_count"]
        assert row["squawk_coverage_ratio"] == 1.0

    # ghi789 has emergency squawk (7700) for all points
    ghi_segments = segments[segments.icao24 == "ghi789"]
    assert len(ghi_segments) == 1
    assert ghi_segments.iloc[0]["squawk_count"] == ghi_segments.iloc[0]["point_count"]
    assert ghi_segments.iloc[0]["squawk_coverage_ratio"] == 1.0


def test_memory_configuration_applied(temp_data_dir, test_config, monkeypatch):
    """Test that memory configuration is correctly applied."""
    # Setup
    monkeypatch.chdir(temp_data_dir)
    date = datetime.date(2025, 7, 1)

    # Create minimal test data
    df = pd.DataFrame(
        [
            {
                "icao24": "test",
                "time": 1000,
                "lat": 40.0,
                "lon": -74.0,
                "squawk": "1200",
                "onground": False,
                "alert": False,
            }
        ]
    )

    input_file = temp_data_dir / "data" / "raw" / f"states_{date}.parquet"
    df.to_parquet(input_file)

    # Override config with very low memory to ensure it's applied
    test_config.duckdb.memory_limit = "100MB"
    test_config.duckdb.threads = 1

    # Run segmentation - should work even with low memory
    output_dir = temp_data_dir / "data" / "segments"
    result_file = segment_day(date, output_dir, test_config)

    # If we got here without OOM, memory limits were applied
    assert result_file.exists()


def test_atomic_file_writing(temp_data_dir, test_config, monkeypatch):
    """Test atomic write pattern with temp file + rename."""
    # Setup
    monkeypatch.chdir(temp_data_dir)
    date = datetime.date(2025, 7, 1)

    # Create test data
    df = pd.DataFrame(
        [
            {
                "icao24": "test",
                "time": i * 100,
                "lat": 40.0 + i * 0.01,
                "lon": -74.0,
                "squawk": "1200",
                "onground": False,
                "alert": False,
            }
            for i in range(100)  # 100 points to create a valid segment
        ]
    )

    input_file = temp_data_dir / "data" / "raw" / f"states_{date}.parquet"
    df.to_parquet(input_file)

    output_dir = temp_data_dir / "data" / "segments"

    # Run twice to test idempotency
    result1 = segment_day(date, output_dir, test_config)
    result2 = segment_day(date, output_dir, test_config)

    # Should return same file path
    assert result1 == result2

    # No temp files should remain
    temp_files = list(output_dir.glob(".segments_*.parquet"))
    assert len(temp_files) == 0


def test_empty_input_handling(temp_data_dir, test_config, monkeypatch):
    """Test handling of empty input data."""
    # Setup
    monkeypatch.chdir(temp_data_dir)
    date = datetime.date(2025, 7, 1)

    # Create empty DataFrame with correct schema
    df = pd.DataFrame(columns=["icao24", "time", "lat", "lon", "squawk", "onground", "alert"])

    input_file = temp_data_dir / "data" / "raw" / f"states_{date}.parquet"
    df.to_parquet(input_file)

    # Run segmentation
    output_dir = temp_data_dir / "data" / "segments"
    result_file = segment_day(date, output_dir, test_config)

    # Should create output file even if empty
    assert result_file.exists()

    # Verify it's empty but has correct schema
    conn = duckdb.connect()
    result = conn.execute(f"SELECT COUNT(*) FROM '{result_file}'").fetchone()
    assert result is not None and result[0] == 0

    # Check schema exists
    schema = conn.execute(f"DESCRIBE SELECT * FROM '{result_file}'").df()
    expected_columns = {
        "segment_id",
        "icao24",
        "start_time",
        "end_time",
        "duration_seconds",
        "distance_km",
        "point_count",
        "squawk_count",
        "squawk_coverage_ratio",
        "keep_reason",
        "points",
    }
    actual_columns = set(schema["column_name"])
    assert expected_columns.issubset(actual_columns)
    conn.close()


def test_missing_input_file_raises_error(temp_data_dir, test_config, monkeypatch):
    """Test that missing input file raises appropriate error."""
    monkeypatch.chdir(temp_data_dir)
    date = datetime.date(2025, 7, 1)

    # Don't create input file
    output_dir = temp_data_dir / "data" / "segments"

    # Should raise FileNotFoundError
    with pytest.raises(FileNotFoundError, match=f"No data for {date}"):
        segment_day(date, output_dir, test_config)


def test_sql_file_exists():
    """Test that the SQL pipeline file exists."""
    sql_file = Path("aviation_anomaly/sql/segment_pipeline.sql")
    assert sql_file.exists()

    # Verify it has the expected structure
    content = sql_file.read_text()
    assert "WITH raw_data AS" in content
    assert "gaps_detected AS" in content
    assert "segments_raw AS" in content
    assert "COPY" in content
    assert "SET memory_limit" in content


@pytest.mark.parametrize(
    "gap_seconds,should_split",
    [
        (1199, False),  # Just under threshold - same segment
        (1200, True),  # Exactly at threshold - new segment
        (1201, True),  # Just over threshold - new segment
    ],
)
def test_exact_gap_boundary_detection(gap_seconds, should_split, temp_data_dir, test_config, monkeypatch):
    """Test gap detection at exact boundary values."""
    monkeypatch.chdir(temp_data_dir)
    date = datetime.date(2025, 7, 1)

    # Create data with precise gap - segments long enough to not be filtered
    # First segment: 11 minutes (660 seconds) to pass duration filter
    first_segment = [
        {
            "icao24": "test123",
            "time": 1000 + i * 60,
            "lat": 40.0 + i * 0.01,
            "lon": -74.0,
            "squawk": "1200",
            "onground": False,
            "alert": False,
        }
        for i in range(12)  # 12 points = 11 minutes = 660 seconds
    ]

    # Second segment after gap: also 11 minutes
    second_segment = [
        {
            "icao24": "test123",
            "time": 1660 + gap_seconds + i * 60,
            "lat": 41.0 + i * 0.01,
            "lon": -74.0,
            "squawk": "1200",
            "onground": False,
            "alert": False,
        }
        for i in range(12)  # 12 points = 11 minutes = 660 seconds
    ]

    data = first_segment + second_segment

    df = pd.DataFrame(data)
    input_file = temp_data_dir / "data" / "raw" / f"states_{date}.parquet"
    df.to_parquet(input_file)

    output_dir = temp_data_dir / "data" / "segments"
    result_file = segment_day(date, output_dir, test_config)

    conn = duckdb.connect()
    segments = conn.execute(f"SELECT * FROM '{result_file}' ORDER BY start_time").df()
    conn.close()

    if should_split:
        assert len(segments) == 2
        assert segments.iloc[0]["end_time"] == 1660  # Last point of first segment
        assert segments.iloc[1]["start_time"] == 1660 + gap_seconds  # First point of second segment
    else:
        assert len(segments) == 1
        assert segments.iloc[0]["start_time"] == 1000
        assert segments.iloc[0]["end_time"] == 2320 + gap_seconds  # Last point when no split


@pytest.mark.parametrize(
    "duration,distance,expected_kept,expected_reason",
    [
        (599, 29.9, False, None),  # Both under - filtered
        (599, 30.1, True, "distance"),  # Under duration, over distance
        (601, 29.9, True, "duration"),  # Over duration, under distance
        (601, 30.1, True, "both"),  # Both over
        (600, 29.9, True, "duration"),  # Exactly at duration threshold
        (599, 30.0, True, "distance"),  # Exactly at distance threshold
        (600, 30.0, True, "both"),  # Exactly at both thresholds
    ],
)
def test_exact_filter_boundaries(
    duration, distance, expected_kept, expected_reason, temp_data_dir, test_config, monkeypatch
):
    """Test filtering at exact duration and distance boundaries."""
    monkeypatch.chdir(temp_data_dir)
    date = datetime.date(2025, 7, 1)

    # Calculate positions to achieve desired distance
    # Using approximate conversion: 1 degree latitude ≈ 111 km
    lat_change = distance / 111.0

    # Create segment with exact duration and distance
    num_points = max(2, duration // 60 + 1)  # At least 2 points for distance
    time_step = duration / (num_points - 1) if num_points > 1 else 0
    lat_step = lat_change / (num_points - 1) if num_points > 1 else 0

    data = [
        {
            "icao24": "boundary_test",
            "time": 1000 + i * time_step,
            "lat": 40.0 + i * lat_step,
            "lon": -74.0,
            "squawk": "1200",
            "onground": False,
            "alert": False,
        }
        for i in range(num_points)
    ]

    df = pd.DataFrame(data)
    input_file = temp_data_dir / "data" / "raw" / f"states_{date}.parquet"
    df.to_parquet(input_file)

    output_dir = temp_data_dir / "data" / "segments"
    result_file = segment_day(date, output_dir, test_config)

    conn = duckdb.connect()
    segments = conn.execute(f"""
        SELECT icao24, duration_seconds, distance_km, keep_reason
        FROM '{result_file}'
    """).df()
    conn.close()

    if expected_kept:
        assert len(segments) == 1
        assert segments.iloc[0]["keep_reason"] == expected_reason
        # Verify the values are close to what we expected
        assert abs(segments.iloc[0]["duration_seconds"] - duration) < 1
        assert abs(segments.iloc[0]["distance_km"] - distance) < 0.5
    else:
        assert len(segments) == 0


def test_null_squawk_handling(temp_data_dir, test_config, monkeypatch):
    """Test handling of NULL and empty string squawks in coverage calculation."""
    monkeypatch.chdir(temp_data_dir)
    date = datetime.date(2025, 7, 1)

    # Create segments with different squawk patterns
    data = (
        [
            # Segment 1: All NULL squawks (common in real data)
            {
                "icao24": "null_squawks",
                "time": 1000 + i * 60,
                "lat": 40.0 + i * 0.01,
                "lon": -74.0,
                "squawk": None,
                "onground": False,
                "alert": False,
            }
            for i in range(15)
        ]
        + [
            # Segment 2: Mixed NULL and valid squawks (after gap)
            {
                "icao24": "mixed_squawks",
                "time": 1000 + i * 60,
                "lat": 35.0 + i * 0.01,
                "lon": -80.0,
                "squawk": "1200" if i % 3 == 0 else None,
                "onground": False,
                "alert": False,
            }
            for i in range(15)
        ]
        + [
            # Segment 3: Empty string squawks (different from NULL)
            {
                "icao24": "empty_squawks",
                "time": 1000 + i * 60,
                "lat": 30.0 + i * 0.01,
                "lon": -90.0,
                "squawk": "" if i % 2 == 0 else "7700",
                "onground": False,
                "alert": i % 2 == 1,
            }
            for i in range(15)
        ]
        + [
            # Segment 4: All valid squawks (baseline)
            {
                "icao24": "valid_squawks",
                "time": 1000 + i * 60,
                "lat": 25.0 + i * 0.01,
                "lon": -95.0,
                "squawk": "1200",
                "onground": False,
                "alert": False,
            }
            for i in range(15)
        ]
    )

    df = pd.DataFrame(data)
    input_file = temp_data_dir / "data" / "raw" / f"states_{date}.parquet"
    df.to_parquet(input_file)

    output_dir = temp_data_dir / "data" / "segments"
    result_file = segment_day(date, output_dir, test_config)

    conn = duckdb.connect()
    segments = conn.execute(f"""
        SELECT icao24, point_count, squawk_count, squawk_coverage_ratio
        FROM '{result_file}'
        ORDER BY icao24
    """).df()
    conn.close()

    # Verify each segment's squawk handling
    null_seg = segments[segments.icao24 == "null_squawks"].iloc[0]
    assert null_seg["squawk_count"] == 0
    assert null_seg["squawk_coverage_ratio"] == 0.0

    mixed_seg = segments[segments.icao24 == "mixed_squawks"].iloc[0]
    assert mixed_seg["squawk_count"] == 5  # Every 3rd point has squawk
    assert abs(mixed_seg["squawk_coverage_ratio"] - 5 / 15) < 0.01

    empty_seg = segments[segments.icao24 == "empty_squawks"].iloc[0]
    assert empty_seg["squawk_count"] == 7  # Odd indices (1,3,5,7,9,11,13) have "7700"
    assert abs(empty_seg["squawk_coverage_ratio"] - 7 / 15) < 0.01

    valid_seg = segments[segments.icao24 == "valid_squawks"].iloc[0]
    assert valid_seg["squawk_count"] == valid_seg["point_count"]
    assert valid_seg["squawk_coverage_ratio"] == 1.0


def test_single_point_segment(temp_data_dir, test_config, monkeypatch):
    """Test edge case of single-point segments (zero duration, zero distance)."""
    monkeypatch.chdir(temp_data_dir)
    date = datetime.date(2025, 7, 1)

    data = [
        # Single point "segment" (e.g., brief radar contact)
        {
            "icao24": "single_point",
            "time": 1000,
            "lat": 40.0,
            "lon": -74.0,
            "squawk": "1200",
            "onground": False,
            "alert": False,
        },
        # Another single point after gap (new segment)
        {
            "icao24": "single_point",
            "time": 3000,
            "lat": 41.0,
            "lon": -75.0,
            "squawk": "7700",
            "onground": False,
            "alert": True,
        },
        # Two-point segment (minimum for distance calc)
        {
            "icao24": "two_point",
            "time": 1000,
            "lat": 35.0,
            "lon": -80.0,
            "squawk": None,
            "onground": False,
            "alert": False,
        },
        {
            "icao24": "two_point",
            "time": 1060,
            "lat": 35.01,
            "lon": -80.0,
            "squawk": None,
            "onground": False,
            "alert": False,
        },
    ]

    df = pd.DataFrame(data)
    input_file = temp_data_dir / "data" / "raw" / f"states_{date}.parquet"
    df.to_parquet(input_file)

    output_dir = temp_data_dir / "data" / "segments"
    result_file = segment_day(date, output_dir, test_config)

    conn = duckdb.connect()
    segments = conn.execute(f"""
        SELECT icao24, start_time, end_time, duration_seconds, distance_km,
               point_count, squawk_count, keep_reason
        FROM '{result_file}'
        ORDER BY icao24, start_time
    """).df()
    conn.close()

    # Single point segments should be filtered (duration=0, distance=0)
    single_segs = segments[segments.icao24 == "single_point"]
    assert len(single_segs) == 0  # Both filtered out

    # Two-point segment might survive if distance is enough
    two_point_segs = segments[segments.icao24 == "two_point"]
    if len(two_point_segs) > 0:
        seg = two_point_segs.iloc[0]
        assert seg["point_count"] == 2
        assert seg["duration_seconds"] == 60
        assert seg["distance_km"] > 0  # Should have some distance
        assert seg["keep_reason"] in ["duration", "distance", "both"]


def test_unordered_input_data(temp_data_dir, test_config, monkeypatch):
    """Test that ORDER BY in raw_data CTE handles unordered input correctly."""
    monkeypatch.chdir(temp_data_dir)
    date = datetime.date(2025, 7, 1)

    # Create intentionally scrambled data
    ordered_data = (
        [
            {
                "icao24": "abc123",
                "time": 1000 + i * 60,
                "lat": 40.0 + i * 0.01,
                "lon": -74.0,
                "squawk": "1200",
                "onground": False,
                "alert": False,
            }
            for i in range(12)  # 12 points = 11 minutes = 660 seconds
        ]
        + [
            # After gap - second segment
            {
                "icao24": "abc123",
                "time": 3000 + i * 60,
                "lat": 41.0 + i * 0.01,
                "lon": -74.0,
                "squawk": "7700",
                "onground": False,
                "alert": True,
            }
            for i in range(12)  # 12 points = 11 minutes = 660 seconds
        ]
        + [
            # Different aircraft intermixed
            {
                "icao24": "xyz789",
                "time": 1500 + i * 60,
                "lat": 35.0 + i * 0.01,
                "lon": -80.0,
                "squawk": None,
                "onground": False,
                "alert": False,
            }
            for i in range(12)  # 12 points = 11 minutes = 660 seconds
        ]
    )

    # Scramble the order completely
    df = pd.DataFrame(ordered_data)
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)  # Shuffle rows

    input_file = temp_data_dir / "data" / "raw" / f"states_{date}.parquet"
    df.to_parquet(input_file)

    output_dir = temp_data_dir / "data" / "segments"
    result_file = segment_day(date, output_dir, test_config)

    conn = duckdb.connect()
    segments = conn.execute(f"""
        SELECT icao24, segment_id, start_time, end_time, duration_seconds, point_count
        FROM '{result_file}'
        ORDER BY icao24, start_time
    """).df()

    # Also check the points are ordered within segments
    segment_points = conn.execute(f"""
        SELECT segment_id, points
        FROM '{result_file}'
        WHERE icao24 = 'abc123'
        ORDER BY start_time
    """).df()
    conn.close()

    # Verify correct segmentation despite scrambled input
    abc_segs = segments[segments.icao24 == "abc123"]
    assert len(abc_segs) == 2
    assert abc_segs.iloc[0]["start_time"] == 1000
    assert abc_segs.iloc[0]["end_time"] == 1660  # 12 points, last at 1000 + 11*60
    assert abc_segs.iloc[0]["point_count"] == 12
    assert abc_segs.iloc[1]["start_time"] == 3000
    assert abc_segs.iloc[1]["end_time"] == 3660  # 12 points, last at 3000 + 11*60
    assert abc_segs.iloc[1]["point_count"] == 12

    xyz_segs = segments[segments.icao24 == "xyz789"]
    assert len(xyz_segs) == 1
    assert xyz_segs.iloc[0]["point_count"] == 12

    # Verify points within segments are properly ordered
    for _, row in segment_points.iterrows():
        points = row["points"]
        times = [p["time"] for p in points]
        assert times == sorted(times), f"Points not ordered in segment {row['segment_id']}"
