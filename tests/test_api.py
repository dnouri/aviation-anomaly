"""Tests for the drill-down API."""

from pathlib import Path

import duckdb
import pytest
from aviation_anomaly.api import query_h3_cell_summary


def test_query_h3_cell_summary_not_implemented():
    """RED test: query_h3_cell_summary function doesn't exist yet."""
    # This should fail because the function doesn't exist
    conn = duckdb.connect()

    with pytest.raises(AttributeError):
        # Function doesn't exist yet
        query_h3_cell_summary(conn=conn, h3_cell="594627166885380095", resolution=4)


def test_query_h3_cell_returns_summary_data():
    """Test that we can query summary data for a specific H3 cell."""
    # This test will be RED until we implement the function
    conn = duckdb.connect()

    # Use real test data
    h3_incidents_file = Path("data/h3/h3_incidents_r4.parquet")
    if not h3_incidents_file.exists():
        pytest.skip("Test data not available")

    # Find a cell with incidents
    test_cell = conn.execute(f"""
        SELECT h3_cell
        FROM '{h3_incidents_file}'
        WHERE incidents_unique > 0
        LIMIT 1
    """).fetchone()

    if not test_cell:
        pytest.skip("No cells with incidents in test data")

    test_h3_cell = str(test_cell[0])

    # Query the cell summary
    result = query_h3_cell_summary(conn=conn, h3_cell=test_h3_cell, resolution=4)

    # Verify structure
    assert result is not None
    assert "h3_cell" in result
    assert "incidents_unique" in result
    assert "predominant_emergency_type" in result
    assert "incident_rate" in result

    # Verify values
    assert result["h3_cell"] == test_h3_cell
    assert result["incidents_unique"] > 0


def test_query_nonexistent_cell_returns_none():
    """Test that querying a non-existent cell returns None."""
    conn = duckdb.connect()

    # Use a fake H3 cell that doesn't exist
    result = query_h3_cell_summary(conn=conn, h3_cell="999999999999999999", resolution=4)

    assert result is None


def test_query_with_filter_by_emergency_type():
    """Test filtering by emergency type."""
    conn = duckdb.connect()

    h3_incidents_file = Path("data/h3/h3_incidents_r4.parquet")
    if not h3_incidents_file.exists():
        pytest.skip("Test data not available")

    # Find a cell with 7700 emergencies
    test_cell = conn.execute(f"""
        SELECT h3_cell
        FROM '{h3_incidents_file}'
        WHERE '7700' = ANY(emergency_types_list)
        LIMIT 1
    """).fetchone()

    if not test_cell:
        pytest.skip("No cells with 7700 emergencies")

    test_h3_cell = str(test_cell[0])

    # Query with filter
    result = query_h3_cell_summary(conn=conn, h3_cell=test_h3_cell, resolution=4, emergency_type="7700")

    # Should return filtered data
    assert result is not None
    assert "7700" in result.get("emergency_types_list", [])
