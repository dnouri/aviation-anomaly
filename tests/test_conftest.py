"""Test conftest fixtures and utilities."""

from pathlib import Path

import pytest


def test_duckdb_extensions_fixture(duckdb_conn):
    """Extensions should be properly installed via fixture."""
    # Test spatial extension works
    result = duckdb_conn.execute("SELECT ST_Point(0, 0) as point").fetchone()
    assert result is not None

    # Test H3 extension works - this is required, not optional
    result = duckdb_conn.execute("SELECT h3_latlng_to_cell(40.7, -74.0, 5) as cell").fetchone()
    assert result is not None
    assert result[0] > 0  # Should be a valid H3 cell index


def test_sample_flight_data_fixture(duckdb_conn, sample_flight_data):
    """Sample flight data fixture should create test data."""
    result = duckdb_conn.execute("SELECT COUNT(*) FROM flights").fetchone()
    assert result[0] == 6

    # Check emergency squawk exists
    result = duckdb_conn.execute("SELECT COUNT(*) FROM flights WHERE squawk = '7700'").fetchone()
    assert result[0] == 1


def test_sql_runner_fixture(tmp_path, sql_runner):
    """SQL runner fixture should execute SQL files correctly."""
    sql_file = tmp_path / "test.sql"
    sql_file.write_text("SELECT 42 as answer, 'hello' as greeting")

    result = sql_runner(sql_file)

    assert result == [(42, "hello")]


def test_sql_runner_with_jinja_template(tmp_path, sql_runner):
    """SQL runner should support Jinja2 templates."""
    sql_file = tmp_path / "template.sql"
    sql_file.write_text("""
        SELECT
            {{ number }} as num,
            '{{ name }}' as name
    """)

    result = sql_runner(sql_file, params={"number": 100, "name": "test"})

    assert result == [(100, "test")]


def test_sql_runner_file_not_found(sql_runner):
    """SQL runner should raise clear error for missing files."""
    with pytest.raises(FileNotFoundError, match="SQL file not found"):
        sql_runner(Path("/nonexistent/file.sql"))


def test_sql_asserter_fixture(sql_asserter):
    """SQL asserter fixture should work correctly."""
    actual = [(1, "a"), (2, "b")]
    expected = [(1, "a"), (2, "b")]

    # Should not raise when equal
    sql_asserter(actual, expected)

    # Should raise when not equal
    wrong = [(1, "a"), (3, "c")]
    with pytest.raises(AssertionError, match="SQL results do not match"):
        sql_asserter(actual, wrong)


def test_sql_runner_with_sql_string(sql_runner):
    """SQL runner should execute SQL strings directly."""
    from decimal import Decimal
    
    # Create a table using SQL
    sql_runner("""
        CREATE TABLE students AS 
        SELECT * FROM (VALUES
            (1, 'Alice', 95.5),
            (2, 'Bob', 87.0),
            (3, 'Charlie', 92.3)
        ) AS t(id, name, score)
    """)

    # Query the table
    result = sql_runner("SELECT * FROM students ORDER BY id")
    assert len(result) == 3
    
    # Check values using Decimal for proper comparison
    assert result[0] == (1, "Alice", Decimal("95.5"))
    assert result[1] == (2, "Bob", Decimal("87.0"))
    assert result[2] == (3, "Charlie", Decimal("92.3"))


def test_sql_runner_with_template_string(sql_runner):
    """SQL runner should support Jinja2 templates in SQL strings."""
    # Create table with template parameters
    sql_runner("""
        CREATE TABLE test_data AS
        SELECT {{ value }} as num, '{{ name }}' as label
    """, params={"value": 42, "name": "test"})
    
    result = sql_runner("SELECT * FROM test_data")
    assert result == [(42, "test")]
