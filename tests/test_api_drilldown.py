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
