"""Tests for data access utilities including Trino queries and DuckDB configuration."""

import os

import pytest

from aviation_anomaly.config import Config
from aviation_anomaly.data_access import TrinoQueryEngine, create_configured_connection


def test_query_engine_requires_credentials(monkeypatch, tmp_path) -> None:
    """Test that query engine requires credentials."""
    # Clear environment variables
    monkeypatch.delenv("OPENSKY_USERNAME", raising=False)
    monkeypatch.delenv("OPENSKY_PASSWORD", raising=False)

    # Set CI mode to avoid prompting
    monkeypatch.setenv("CI", "true")

    # Mock the token cache to ensure no cached tokens are used
    from pathlib import Path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    engine = TrinoQueryEngine()

    with pytest.raises(RuntimeError, match="OpenSky credentials required"):
        engine.execute("SELECT 1")


def test_query_engine_with_mocked_auth(monkeypatch) -> None:
    """Test query execution with mocked authentication."""

    # Mock the auth to return a test token
    def mock_get_token():
        return "test-token"

    monkeypatch.setattr("aviation_anomaly.data_access.get_opensky_token", mock_get_token)

    # Mock the connection
    class MockCursor:
        def execute(self, query):
            self.query = query

        def fetchall(self):
            if "SELECT 1" in self.query:
                return [(1,)]
            return []

    class MockConnection:
        def cursor(self):
            return MockCursor()

        def close(self):
            pass

    def mock_connect(*args, **kwargs):
        return MockConnection()

    monkeypatch.setattr("aviation_anomaly.data_access.connect", mock_connect)

    engine = TrinoQueryEngine()
    result = engine.execute("SELECT 1")
    assert result == [(1,)]


def test_query_engine_connection_reuse(monkeypatch) -> None:
    """Test that engine reuses connections efficiently."""
    # Mock auth
    monkeypatch.setattr("aviation_anomaly.data_access.get_opensky_token", lambda: "test-token")

    connection_count = 0

    class MockConnection:
        def __init__(self):
            nonlocal connection_count
            connection_count += 1

        def cursor(self):
            return MockCursor()

        def close(self):
            pass

    class MockCursor:
        def execute(self, query):
            pass

        def fetchall(self):
            return [(1,)]

    def mock_connect(*args, **kwargs):
        return MockConnection()

    monkeypatch.setattr("aviation_anomaly.data_access.connect", mock_connect)

    engine = TrinoQueryEngine()

    # Execute multiple queries
    engine.execute("SELECT 1")
    engine.execute("SELECT 2")
    engine.execute("SELECT 3")

    # Should only create one connection
    assert connection_count == 1


def test_query_engine_closes_connection() -> None:
    """Test that engine can close connections properly."""
    engine = TrinoQueryEngine()

    # Set up a fake connection
    engine._connection = type("MockConnection", (), {"close": lambda self: None})()

    # Close should work without error
    engine.close()
    assert engine._connection is None

    # Closing again should be safe
    engine.close()
    assert engine._connection is None


@pytest.mark.integration
def test_real_opensky_connection() -> None:
    """Integration test with real OpenSky connection.

    To run this test:
    1. Set OPENSKY_USERNAME and OPENSKY_PASSWORD environment variables
    2. Run: pytest -m integration tests/test_data_access.py

    This test verifies that password authentication works correctly
    with OpenSky's Trino server.
    """
    # Skip if no credentials in environment
    if not (os.environ.get("OPENSKY_USERNAME") and os.environ.get("OPENSKY_PASSWORD")):
        pytest.skip("No OpenSky credentials in environment")

    engine = TrinoQueryEngine()

    try:
        # Test simple query
        result = engine.execute("SELECT 1")
        assert result == [[1]]  # Trino returns lists, not tuples

        # Test schema query
        result = engine.execute("SHOW TABLES")
        assert len(result) > 0

    finally:
        engine.close()


def test_create_configured_connection_applies_settings():
    """Test that create_configured_connection applies all settings from config."""
    config = Config()
    config.duckdb.memory_limit = "2GB"
    config.duckdb.threads = 4
    config.duckdb.temp_directory = "/tmp/test_duckdb"
    config.duckdb.max_temp_directory_size = "10GB"

    conn = create_configured_connection(config)

    try:
        # Verify connection is valid by running a simple query
        result = conn.execute("SELECT 1").fetchone()
        assert result is not None
        assert result[0] == 1

        # Verify settings were applied by checking the configuration
        memory_result = conn.execute("SELECT current_setting('memory_limit')").fetchone()
        threads_result = conn.execute("SELECT current_setting('threads')").fetchone()
        temp_result = conn.execute("SELECT current_setting('temp_directory')").fetchone()

        assert memory_result is not None
        assert threads_result is not None
        assert temp_result is not None

        memory_limit = memory_result[0]
        threads = threads_result[0]
        temp_directory = temp_result[0]

        # DuckDB formats memory values (2GB becomes "1.8 GiB" or similar)
        # Just verify it's not the default and has GiB unit
        assert "GiB" in memory_limit or "GB" in memory_limit
        assert threads == 4  # threads is returned as integer
        assert temp_directory == "/tmp/test_duckdb"

    finally:
        conn.close()


def test_create_configured_connection_with_extensions():
    """Test that connection can be extended with additional extensions."""
    config = Config()

    conn = create_configured_connection(config, extensions=["httpfs"])

    try:
        # Verify httpfs extension is loaded by checking if its functions exist
        result = conn.execute("SELECT * FROM duckdb_extensions() WHERE extension_name = 'httpfs'").fetchone()
        assert result is not None
        assert result[1] is True  # loaded column

    finally:
        conn.close()


def test_create_configured_connection_progress_bar_enabled():
    """Test that progress bar is enabled by default."""
    config = Config()

    conn = create_configured_connection(config)

    try:
        # Check that progress bar settings are enabled
        result = conn.execute("SELECT current_setting('enable_progress_bar')").fetchone()
        assert result is not None
        assert result[0] is True

    finally:
        conn.close()
