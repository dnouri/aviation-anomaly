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
