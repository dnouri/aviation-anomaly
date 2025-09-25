"""Tests for the drill-down API."""

import duckdb

from aviation_anomaly.api import query_h3_cell_summary


def test_query_h3_cell_summary_exists():
    """Test that query_h3_cell_summary function exists and is callable."""
    # Verify the function is imported and callable
    conn = duckdb.connect()

    # Function should exist and be callable (may return None for missing data)
    result = query_h3_cell_summary(conn=conn, h3_cell="nonexistent", resolution=4)

    # It's OK if it returns None for a non-existent cell
    assert result is None or isinstance(result, dict)


def test_query_h3_cell_returns_summary_data(h3_test_data):
    """Test that we can query summary data for a specific H3 cell."""
    conn = duckdb.connect()

    # Use fixture data with known values
    test_h3_cell = "594627166885380095"  # Known cell from fixture

    # Query the cell summary
    result = query_h3_cell_summary(conn=conn, h3_cell=test_h3_cell, resolution=4)

    # Verify structure
    assert result is not None
    assert "h3_cell" in result
    assert "incidents_unique" in result
    assert "predominant_emergency_type" in result
    assert "incident_rate" in result

    # Verify known values from fixture
    assert result["h3_cell"] == test_h3_cell
    assert result["incidents_unique"] == 3
    assert result["predominant_emergency_type"] == "7700"
    assert abs(float(result["incident_rate"]) - 0.03) < 0.001  # 3 incidents / 100 segments


def test_query_nonexistent_cell_returns_none(h3_test_data):
    """Test that querying a non-existent cell returns None."""
    conn = duckdb.connect()

    # Use a fake H3 cell that doesn't exist
    result = query_h3_cell_summary(conn=conn, h3_cell="999999999999999999", resolution=4)

    assert result is None


def test_query_with_filter_by_emergency_type(h3_test_data):
    """Test filtering by emergency type."""
    conn = duckdb.connect()

    # Use known cell that has 7700 emergencies
    test_h3_cell = "594627166885380095"

    # Query with filter
    result = query_h3_cell_summary(conn=conn, h3_cell=test_h3_cell, resolution=4, emergency_type="7700")

    # Should return filtered data
    assert result is not None
    assert "7700" in result.get("emergency_types_list", [])
