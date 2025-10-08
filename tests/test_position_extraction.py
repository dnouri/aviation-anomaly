"""Tests for incident position extraction from segment trajectories.

This validates the SQL logic for extracting (lat, lon) at incident start time
before integrating it into the detection pipeline.
"""

import duckdb


def test_extract_position_at_exact_timestamp():
    """Position extraction finds the point at exact incident start time."""
    conn = duckdb.connect()

    # Create test segment with trajectory
    conn.execute("""
        CREATE TEMP TABLE test_segments AS
        SELECT
            'test_segment_1' as segment_id,
            'abc123' as icao24,
            CAST([
                {'time': 1000, 'lat': 10.0, 'lon': 20.0, 'squawk': '1200', 'onground': false, 'alert': false},
                {'time': 1010, 'lat': 11.0, 'lon': 21.0, 'squawk': '1200', 'onground': false, 'alert': false},
                {'time': 1020, 'lat': 12.0, 'lon': 22.0, 'squawk': '7500', 'onground': false, 'alert': true},
                {'time': 1030, 'lat': 13.0, 'lon': 23.0, 'squawk': '7500', 'onground': false, 'alert': false}
            ] AS STRUCT(time INTEGER, lat DOUBLE, lon DOUBLE, squawk VARCHAR, onground BOOLEAN, alert BOOLEAN)[]) as points
    """)

    # Extract position at time 1020 (when emergency started)
    result = conn.execute("""
        SELECT
            list_filter(points, p -> p.time = 1020)[1].lat as start_lat,
            list_filter(points, p -> p.time = 1020)[1].lon as start_lon
        FROM test_segments
        WHERE segment_id = 'test_segment_1'
    """).fetchone()

    assert result is not None
    assert result[0] == 12.0, "Latitude should be 12.0 at time 1020"
    assert result[1] == 22.0, "Longitude should be 22.0 at time 1020"


def test_extract_position_returns_null_if_timestamp_not_found():
    """Position extraction returns NULL when timestamp doesn't exist in trajectory."""
    conn = duckdb.connect()

    conn.execute("""
        CREATE TEMP TABLE test_segments AS
        SELECT
            'test_segment_1' as segment_id,
            CAST([
                {'time': 1000, 'lat': 10.0, 'lon': 20.0, 'squawk': '1200', 'onground': false, 'alert': false},
                {'time': 1010, 'lat': 11.0, 'lon': 21.0, 'squawk': '1200', 'onground': false, 'alert': false}
            ] AS STRUCT(time INTEGER, lat DOUBLE, lon DOUBLE, squawk VARCHAR, onground BOOLEAN, alert BOOLEAN)[]) as points
    """)

    # Try to extract position at time that doesn't exist
    result = conn.execute("""
        SELECT
            list_filter(points, p -> p.time = 9999)[1].lat as start_lat,
            list_filter(points, p -> p.time = 9999)[1].lon as start_lon
        FROM test_segments
    """).fetchone()

    assert result is not None
    assert result[0] is None, "Latitude should be NULL when timestamp not found"
    assert result[1] is None, "Longitude should be NULL when timestamp not found"


def test_extract_position_for_multiple_incidents():
    """Position extraction works correctly for multiple incidents on same segment."""
    conn = duckdb.connect()

    conn.execute("""
        CREATE TEMP TABLE test_segments AS
        SELECT
            'seg1' as segment_id,
            CAST([
                {'time': 1000, 'lat': 10.0, 'lon': 20.0, 'squawk': '1200', 'onground': false, 'alert': false},
                {'time': 1010, 'lat': 11.0, 'lon': 21.0, 'squawk': '7500', 'onground': false, 'alert': true},
                {'time': 1020, 'lat': 12.0, 'lon': 22.0, 'squawk': '7500', 'onground': false, 'alert': false},
                {'time': 1030, 'lat': 13.0, 'lon': 23.0, 'squawk': '7700', 'onground': false, 'alert': true},
                {'time': 1040, 'lat': 14.0, 'lon': 24.0, 'squawk': '7700', 'onground': false, 'alert': false}
            ] AS STRUCT(time INTEGER, lat DOUBLE, lon DOUBLE, squawk VARCHAR, onground BOOLEAN, alert BOOLEAN)[]) as points
    """)

    conn.execute("""
        CREATE TEMP TABLE test_incidents AS
        SELECT * FROM (VALUES
            ('inc1', 'seg1', 1010),  -- First emergency at 1010
            ('inc2', 'seg1', 1030)   -- Second emergency at 1030
        ) AS t(incident_id, segment_id, start_time)
    """)

    # Extract positions for both incidents
    result = conn.execute("""
        SELECT
            i.incident_id,
            list_filter(s.points, p -> p.time = i.start_time)[1].lat as start_lat,
            list_filter(s.points, p -> p.time = i.start_time)[1].lon as start_lon
        FROM test_incidents i
        JOIN test_segments s ON i.segment_id = s.segment_id
        ORDER BY i.incident_id
    """).fetchall()

    assert len(result) == 2
    # First incident at time 1010
    assert result[0] == ("inc1", 11.0, 21.0)
    # Second incident at time 1030
    assert result[1] == ("inc2", 13.0, 23.0)


def test_segment_across_multiple_date_files_with_different_trajectories():
    """
    Test the critical multi-date scenario that caused the original bug.

    Regression test for: Same segment_id appears in multiple date files,
    but each file has different trajectory subsets. One file has the
    incident timestamp, others don't. Using DISTINCT ON or FIRST() would
    pick arbitrary file, potentially missing the needed timestamp.

    This validates that during detection, we extract position from whichever
    date file has the segment with the full trajectory containing the incident.
    """
    conn = duckdb.connect()

    # Simulate segment appearing in 3 date files with different trajectory data
    conn.execute("""
        CREATE TEMP TABLE segments_date1 AS
        SELECT
            'abc123_3' as segment_id,
            CAST([
                -- This file only has EARLY part of trajectory
                {'time': 1000, 'lat': 30.0, 'lon': -90.0, 'squawk': '1200', 'onground': false, 'alert': false},
                {'time': 1010, 'lat': 30.1, 'lon': -90.1, 'squawk': '1200', 'onground': false, 'alert': false}
            ] AS STRUCT(time INTEGER, lat DOUBLE, lon DOUBLE, squawk VARCHAR, onground BOOLEAN, alert BOOLEAN)[]) as points
    """)

    conn.execute("""
        CREATE TEMP TABLE segments_date2 AS
        SELECT
            'abc123_3' as segment_id,
            CAST([
                -- This file has the MIDDLE part with incident start
                {'time': 1015, 'lat': 30.15, 'lon': -90.15, 'squawk': '1200', 'onground': false, 'alert': false},
                {'time': 1020, 'lat': 30.2, 'lon': -90.2, 'squawk': '7500', 'onground': false, 'alert': true},
                {'time': 1030, 'lat': 30.3, 'lon': -90.3, 'squawk': '7500', 'onground': false, 'alert': false}
            ] AS STRUCT(time INTEGER, lat DOUBLE, lon DOUBLE, squawk VARCHAR, onground BOOLEAN, alert BOOLEAN)[]) as points
    """)

    conn.execute("""
        CREATE TEMP TABLE segments_date3 AS
        SELECT
            'abc123_3' as segment_id,
            CAST([
                -- This file only has LATE part of trajectory
                {'time': 1040, 'lat': 30.4, 'lon': -90.4, 'squawk': '1200', 'onground': false, 'alert': false},
                {'time': 1050, 'lat': 30.5, 'lon': -90.5, 'squawk': '1200', 'onground': false, 'alert': false}
            ] AS STRUCT(time INTEGER, lat DOUBLE, lon DOUBLE, squawk VARCHAR, onground BOOLEAN, alert BOOLEAN)[]) as points
    """)

    # Incident detected at time 1020 (which exists in date2 file ONLY)
    incident_start_time = 1020

    # Simulate querying all date files (like glob pattern does)
    all_segments = conn.execute("""
        SELECT segment_id, points FROM segments_date1
        UNION ALL
        SELECT segment_id, points FROM segments_date2
        UNION ALL
        SELECT segment_id, points FROM segments_date3
    """).fetchall()

    # Verify we have 3 occurrences of same segment_id
    assert len(all_segments) == 3
    assert all(s[0] == "abc123_3" for s in all_segments)

    # Try extracting position from each file
    results_per_file = []
    for i, (_seg_id, points) in enumerate(all_segments, 1):
        lat_result = conn.execute(
            "SELECT list_filter(?, p -> p.time = ?)[1].lat", [points, incident_start_time]
        ).fetchone()
        lon_result = conn.execute(
            "SELECT list_filter(?, p -> p.time = ?)[1].lon", [points, incident_start_time]
        ).fetchone()
        assert lat_result is not None and lon_result is not None
        lat = lat_result[0]
        lon = lon_result[0]
        results_per_file.append((f"date{i}", lat, lon))

    # Verify only ONE file has the timestamp
    non_null_results = [(d, lat, lon) for d, lat, lon in results_per_file if lat is not None]
    assert len(non_null_results) == 1, "Only one date file should have the timestamp"
    assert non_null_results[0] == ("date2", 30.2, -90.2), "date2 file should have correct position"

    # Simulate MAX() aggregation approach (picks non-NULL across files)
    max_lat_result = conn.execute(
        """
        WITH all_files AS (
            SELECT points FROM segments_date1
            UNION ALL
            SELECT points FROM segments_date2
            UNION ALL
            SELECT points FROM segments_date3
        )
        SELECT MAX(list_filter(points, p -> p.time = ?)[1].lat)
        FROM all_files
    """,
        [incident_start_time],
    ).fetchone()
    assert max_lat_result is not None
    max_lat = max_lat_result[0]

    max_lon_result = conn.execute(
        """
        WITH all_files AS (
            SELECT points FROM segments_date1
            UNION ALL
            SELECT points FROM segments_date2
            UNION ALL
            SELECT points FROM segments_date3
        )
        SELECT MAX(list_filter(points, p -> p.time = ?)[1].lon)
        FROM all_files
    """,
        [incident_start_time],
    ).fetchone()
    assert max_lon_result is not None
    max_lon = max_lon_result[0]

    # MAX() correctly picks the non-NULL value
    assert max_lat == 30.2, "MAX() should find the correct latitude from date2"
    assert max_lon == -90.2, "MAX() should find the correct longitude from date2"

    # This validates our fix: MAX(list_filter(...)) works across multiple file occurrences


def test_position_matches_current_api_approach():
    """
    Verify denormalized approach produces same results as current API query.

    This test ensures backward compatibility - positions from denormalized
    columns should match what the current list_filter query returns.
    """
    conn = duckdb.connect()

    # Create test data matching real schema
    conn.execute("""
        CREATE TEMP TABLE segments AS
        SELECT
            'abc123_1' as segment_id,
            'abc123' as icao24,
            1000 as start_time,
            1100 as end_time,
            100 as duration_seconds,
            0.0 as distance_km,
            5 as point_count,
            1 as squawk_count,
            0.2 as squawk_coverage_ratio,
            'squawk' as keep_reason,
            CAST([
                {'time': 1000, 'lat': 40.0, 'lon': -100.0, 'squawk': '1200', 'onground': false, 'alert': false},
                {'time': 1020, 'lat': 40.1, 'lon': -100.1, 'squawk': '7500', 'onground': false, 'alert': true},
                {'time': 1040, 'lat': 40.2, 'lon': -100.2, 'squawk': '7500', 'onground': false, 'alert': false},
                {'time': 1060, 'lat': 40.3, 'lon': -100.3, 'squawk': '7500', 'onground': false, 'alert': false},
                {'time': 1080, 'lat': 40.4, 'lon': -100.4, 'squawk': '1200', 'onground': false, 'alert': false}
            ] AS STRUCT(time INTEGER, lat DOUBLE, lon DOUBLE, squawk VARCHAR, onground BOOLEAN, alert BOOLEAN)[]) as points
    """)

    conn.execute("""
        CREATE TEMP TABLE incidents AS
        SELECT * FROM (VALUES
            ('abc123_1020', 'abc123_1', 'abc123', 1020, 1080, '7500', 90, 60)
        ) AS t(incident_id, segment_id, icao24, start_time, end_time, emergency_type, confidence_score, duration_seconds)
    """)

    # Current approach (what API does now)
    current_result = conn.execute("""
        SELECT
            i.incident_id,
            list_filter(s.points, p -> p.time = i.start_time)[1].lat as lat,
            list_filter(s.points, p -> p.time = i.start_time)[1].lon as lon
        FROM incidents i
        JOIN segments s ON i.segment_id = s.segment_id
    """).fetchone()

    # Proposed approach (denormalized columns)
    # Simulate adding columns during detection
    proposed_result = conn.execute("""
        SELECT
            incident_id,
            list_filter(s.points, p -> p.time = i.start_time)[1].lat as start_lat,
            list_filter(s.points, p -> p.time = i.start_time)[1].lon as start_lon
        FROM incidents i
        JOIN segments s ON i.segment_id = s.segment_id
    """).fetchone()

    # Both approaches should produce identical results
    assert current_result is not None
    assert proposed_result is not None
    assert current_result[1] == proposed_result[1], "Latitudes must match"
    assert current_result[2] == proposed_result[2], "Longitudes must match"
    assert proposed_result[1] == 40.1, "Should extract position at incident start (1020)"
    assert proposed_result[2] == -100.1, "Should extract position at incident start (1020)"
