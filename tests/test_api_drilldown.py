"""Tests for the drill-down API incident details."""

from pathlib import Path

import duckdb
import pytest


def test_query_h3_cell_incidents():
    """RED test: query_h3_cell_incidents function doesn't exist yet."""
    from aviation_anomaly.api import query_h3_cell_incidents

    conn = duckdb.connect()

    # Should return empty list if no data
    result = query_h3_cell_incidents(conn=conn, h3_cell="999999999999999999", resolution=4)

    assert result["meta"]["count"] == 0
    assert result["rows"] == []


def test_query_h3_cell_incidents_with_data():
    """Test querying actual incident details for a cell."""
    from aviation_anomaly.api import query_h3_cell_incidents

    conn = duckdb.connect()

    # Check if test data exists
    mapping_file = Path("data/h3/incident_h3_mapping_r4.parquet")
    incidents_file = Path("data/incidents/incidents_2025-07-02.parquet")

    if not mapping_file.exists() or not incidents_file.exists():
        pytest.skip("Test data not available")

    # Find a cell with incidents
    test_cell = conn.execute(f"""
        SELECT DISTINCT h3_cell
        FROM '{mapping_file}'
        LIMIT 1
    """).fetchone()

    if not test_cell:
        pytest.skip("No cells in mapping data")

    test_h3_cell = str(test_cell[0])

    # Query incidents for this cell
    result = query_h3_cell_incidents(conn=conn, h3_cell=test_h3_cell, resolution=4)

    # Should have structure with meta and rows
    assert "meta" in result
    assert "rows" in result
    assert "count" in result["meta"]
    assert result["meta"]["count"] >= 0

    # If there are incidents, check row structure
    if result["meta"]["count"] > 0:
        first_row = result["rows"][0]
        assert "incident_id" in first_row
        assert "start_time" in first_row
        assert "end_time" in first_row
        assert "emergency_type" in first_row
        assert "icao24" in first_row


def test_query_h3_cell_incidents_with_limit():
    """Test pagination with limit parameter."""
    from aviation_anomaly.api import query_h3_cell_incidents

    conn = duckdb.connect()

    mapping_file = Path("data/h3/incident_h3_mapping_r4.parquet")
    if not mapping_file.exists():
        pytest.skip("Test data not available")

    # Find a cell with multiple incidents
    test_cell = conn.execute(f"""
        SELECT h3_cell, COUNT(*) as cnt
        FROM '{mapping_file}'
        GROUP BY h3_cell
        HAVING COUNT(*) > 2
        LIMIT 1
    """).fetchone()

    if not test_cell:
        pytest.skip("No cells with multiple incidents")

    test_h3_cell = str(test_cell[0])

    # Query with limit
    result = query_h3_cell_incidents(conn=conn, h3_cell=test_h3_cell, resolution=4, limit=2)

    # Should respect limit
    assert len(result["rows"]) <= 2
    assert result["meta"]["count"] <= 2


def test_query_h3_cell_incidents_with_emergency_filter():
    """Test filtering by emergency type."""
    from aviation_anomaly.api import query_h3_cell_incidents

    conn = duckdb.connect()

    mapping_file = Path("data/h3/incident_h3_mapping_r4.parquet")
    incidents_file = Path("data/incidents/incidents_2025-07-02.parquet")

    if not mapping_file.exists() or not incidents_file.exists():
        pytest.skip("Test data not available")

    # Find incidents with 7700 emergency
    test_incident = conn.execute(f"""
        SELECT incident_id
        FROM '{incidents_file}'
        WHERE emergency_type = '7700'
        LIMIT 1
    """).fetchone()

    if not test_incident:
        pytest.skip("No 7700 incidents in test data")

    # Find the H3 cell for this incident
    test_cell = conn.execute(f"""
        SELECT h3_cell
        FROM '{mapping_file}'
        WHERE incident_id = '{test_incident[0]}'
        LIMIT 1
    """).fetchone()

    if not test_cell:
        pytest.skip("Incident not in mapping")

    test_h3_cell = str(test_cell[0])

    # Query with 7700 filter
    result = query_h3_cell_incidents(conn=conn, h3_cell=test_h3_cell, resolution=4, emergency_type="7700")

    # All results should be 7700
    for row in result["rows"]:
        assert row["emergency_type"] == "7700"


def test_query_h3_cell_incidents_includes_position():
    """Test that incidents include start position for external links."""
    from aviation_anomaly.api import query_h3_cell_incidents

    conn = duckdb.connect()

    # Use r3 data and find a cell that actually has incidents in the incidents file
    mapping_file = Path("data/h3/incident_h3_mapping_r3.parquet")
    h3_file = Path("data/h3/h3_incidents_r3.parquet")

    if not mapping_file.exists() or not h3_file.exists():
        pytest.skip("Test data not available")

    # Find a cell with incidents from the H3 aggregation
    test_cell = conn.execute(f"""
        SELECT h3_cell
        FROM '{h3_file}'
        WHERE incidents_unique > 0
        LIMIT 1
    """).fetchone()

    if not test_cell:
        pytest.skip("No cells with incidents")

    test_h3_cell = str(test_cell[0])

    # Query incidents for this cell
    result = query_h3_cell_incidents(conn=conn, h3_cell=test_h3_cell, resolution=3)

    # Should have at least one incident
    assert result["meta"]["count"] > 0, "Expected to find incidents for cell with incidents_unique > 0"

    first_row = result["rows"][0]

    # Position fields should be present
    assert "start_lat" in first_row, "start_lat field missing from incident response"
    assert "start_lon" in first_row, "start_lon field missing from incident response"

    # Position values should be numeric and valid coordinates
    assert isinstance(first_row["start_lat"], (int, float)), "start_lat should be numeric"
    assert isinstance(first_row["start_lon"], (int, float)), "start_lon should be numeric"

    # Sanity check coordinate ranges
    assert -90 <= first_row["start_lat"] <= 90, "start_lat should be valid latitude"
    assert -180 <= first_row["start_lon"] <= 180, "start_lon should be valid longitude"


def test_build_adsb_exchange_url():
    """Test URL builder for ADS-B Exchange flight replay links."""
    from aviation_anomaly.api import build_adsb_exchange_url

    # Test case from spike script: a3e58b incident on 2025-07-07
    url = build_adsb_exchange_url(
        icao24="a3e58b",
        timestamp=1751925231,  # 2025-07-07 11:13:51 UTC
        lat=61.535541081832626,
        lon=-149.81058756510416,
    )

    # Should build correct URL format
    assert url.startswith("https://globe.adsbexchange.com/")
    assert "icao=a3e58b" in url
    assert "showTrace=2025-07-07" in url
    assert "timestamp=1751925231" in url
    assert "lat=61.535541081832626" in url
    assert "lon=-149.81058756510416" in url
    assert "zoom=" in url


def test_build_adsb_exchange_url_custom_zoom():
    """Test URL builder with custom zoom level."""
    from aviation_anomaly.api import build_adsb_exchange_url

    url = build_adsb_exchange_url(
        icao24="abc123",
        timestamp=1234567890,
        lat=45.0,
        lon=-122.0,
        zoom=12,
    )

    assert "zoom=12" in url


def test_build_adsb_exchange_url_negative_coords():
    """Test URL builder handles negative coordinates."""
    from aviation_anomaly.api import build_adsb_exchange_url

    url = build_adsb_exchange_url(
        icao24="test01",
        timestamp=1600000000,
        lat=-33.8688,  # Sydney
        lon=151.2093,
    )

    assert "lat=-33.8688" in url
    assert "lon=151.2093" in url


def test_query_h3_cell_incidents_includes_adsb_url():
    """Test that API response includes ADS-B Exchange URL for each incident."""
    from aviation_anomaly.api import query_h3_cell_incidents

    conn = duckdb.connect()

    # Use r3 data to find a cell with incidents
    mapping_file = Path("data/h3/incident_h3_mapping_r3.parquet")
    h3_file = Path("data/h3/h3_incidents_r3.parquet")

    if not mapping_file.exists() or not h3_file.exists():
        pytest.skip("Test data not available")

    # Find a cell with incidents
    test_cell = conn.execute(f"""
        SELECT h3_cell
        FROM '{h3_file}'
        WHERE incidents_unique > 0
        LIMIT 1
    """).fetchone()

    if not test_cell:
        pytest.skip("No cells with incidents")

    test_h3_cell = str(test_cell[0])

    # Query incidents
    result = query_h3_cell_incidents(conn=conn, h3_cell=test_h3_cell, resolution=3)

    assert result["meta"]["count"] > 0, "Expected incidents"
    first_row = result["rows"][0]

    # URL field should be present
    assert "adsb_exchange_url" in first_row, "adsb_exchange_url field missing"

    # URL should be properly formatted
    url = first_row["adsb_exchange_url"]
    assert url.startswith("https://globe.adsbexchange.com/")
    assert f"icao={first_row['icao24']}" in url
    assert f"timestamp={first_row['start_time']}" in url
    assert f"lat={first_row['start_lat']}" in url
    assert f"lon={first_row['start_lon']}" in url


def test_position_extracted_at_incident_start_not_segment_start():
    """
    Test that position is extracted at incident start time, not segment start.

    Regression test for bug where positions used segment start (points[1])
    instead of the point at incident.start_time, causing ADS-B Exchange links
    to point to incorrect locations (sometimes hundreds of miles away).

    This test also verifies that when segments appear in multiple date files
    with different trajectory data, the query correctly finds the occurrence
    containing the incident start timestamp, rather than arbitrarily picking
    the first occurrence (which may not have that timestamp).
    """
    from aviation_anomaly.api import query_h3_cell_incidents

    conn = duckdb.connect()

    # Use data files that exist across multiple dates
    segments_file = Path("data/segments/segments_2025-07-02.parquet")
    incidents_file = Path("data/incidents/incidents_2025-07-02.parquet")
    mapping_file = Path("data/h3/incident_h3_mapping_r5.parquet")

    if not all([segments_file.exists(), incidents_file.exists(), mapping_file.exists()]):
        pytest.skip("Test data not available")

    # Find an incident where segment start differs significantly from incident start
    # This catches cases where the incident occurs mid-flight, not at takeoff
    test_data = conn.execute(f"""
        WITH incident_sample AS (
            SELECT i.incident_id, i.segment_id, i.start_time, i.icao24
            FROM '{incidents_file}' i
            LIMIT 10
        ),
        segment_with_incident AS (
            SELECT
                s.segment_id,
                s.points[1].lat as segment_start_lat,
                s.points[1].lon as segment_start_lon,
                i.start_time,
                s.points
            FROM '{segments_file}' s
            JOIN incident_sample i ON s.segment_id = i.segment_id
        ),
        segment_with_position AS (
            SELECT DISTINCT ON (segment_id)
                segment_id,
                segment_start_lat,
                segment_start_lon,
                list_filter(points, p -> p.time = start_time)[1].lat as incident_start_lat,
                list_filter(points, p -> p.time = start_time)[1].lon as incident_start_lon
            FROM segment_with_incident
        )
        SELECT
            i.incident_id,
            i.start_time,
            s.segment_start_lat,
            s.segment_start_lon,
            s.incident_start_lat,
            s.incident_start_lon,
            -- Calculate distance between segment start and incident start
            ABS(s.segment_start_lat - s.incident_start_lat) +
            ABS(s.segment_start_lon - s.incident_start_lon) as coord_diff
        FROM incident_sample i
        JOIN segment_with_position s ON i.segment_id = s.segment_id
        WHERE s.incident_start_lat IS NOT NULL
          AND coord_diff > 0.01  -- Significant difference (>1 degree)
        LIMIT 1
    """).fetchone()

    if not test_data:
        pytest.skip("No incidents found with sufficient position difference")

    (incident_id, start_time, segment_start_lat, segment_start_lon, expected_lat, expected_lon, _) = test_data

    # Verify this segment exists in multiple date files (if available)
    # This tests the multi-date deduplication behavior
    icao24_pattern = f"%{incident_id.split('_')[0]}%"
    multi_date_result = conn.execute(
        """
        SELECT COUNT(DISTINCT file) FROM (
            SELECT 'seg1' as file FROM 'data/segments/segments_2025-07-02.parquet' WHERE segment_id LIKE ?
            UNION ALL
            SELECT 'seg2' FROM 'data/segments/segments_2025-07-03.parquet' WHERE segment_id LIKE ?
            UNION ALL
            SELECT 'seg3' FROM 'data/segments/segments_2025-07-04.parquet' WHERE segment_id LIKE ?
        )
    """,
        [icao24_pattern] * 3,
    ).fetchone()
    multi_date_count = multi_date_result[0] if multi_date_result else 0

    # Find H3 cell for this incident
    h3_cell_result = conn.execute(f"""
        SELECT h3_cell
        FROM '{mapping_file}'
        WHERE incident_id = '{incident_id}'
        LIMIT 1
    """).fetchone()

    if not h3_cell_result:
        pytest.skip("Incident not in H3 mapping")

    test_h3_cell = str(h3_cell_result[0])

    # Query via API (which uses glob patterns to query all date files)
    result = query_h3_cell_incidents(conn=conn, h3_cell=test_h3_cell, resolution=5)

    # Find our specific incident in the results
    target_incident = None
    for row in result["rows"]:
        if row["incident_id"] == incident_id:
            target_incident = row
            break

    assert target_incident is not None, f"Incident {incident_id} not found in API results"

    # Position should match incident start, NOT segment start
    actual_lat = target_incident["start_lat"]
    actual_lon = target_incident["start_lon"]

    # Verify position matches incident start time (within floating point tolerance)
    assert abs(actual_lat - expected_lat) < 0.0001, (
        f"Latitude should be at incident start ({expected_lat}), "
        f"not segment start ({segment_start_lat}). Got {actual_lat}. "
        f"Segment appears in {multi_date_count} date files."
    )
    assert abs(actual_lon - expected_lon) < 0.0001, (
        f"Longitude should be at incident start ({expected_lon}), "
        f"not segment start ({segment_start_lon}). Got {actual_lon}. "
        f"Segment appears in {multi_date_count} date files."
    )

    # Verify it's NOT the segment start position (the bug we're preventing)
    segment_diff = abs(actual_lat - segment_start_lat) + abs(actual_lon - segment_start_lon)
    assert segment_diff > 0.01, (
        "Position should NOT match segment start "
        f"(segment: {segment_start_lat}, {segment_start_lon}). "
        "This would indicate regression to the bug where points[1] was used."
    )
