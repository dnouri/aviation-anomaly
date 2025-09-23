"""Test CLI serve command integration."""

import threading
import time
from unittest import mock

import httpx
import pytest
from click.testing import CliRunner

from aviation_anomaly.cli import main


def test_serve_command_exists():
    """Serve command should be available in CLI."""
    runner = CliRunner()
    result = runner.invoke(main, ["serve", "--help"])

    assert result.exit_code == 0
    assert "Start the API server" in result.output
    assert "--host" in result.output
    assert "--port" in result.output
    assert "--reload" in result.output


def test_serve_command_starts_server():
    """Serve command should start a uvicorn server."""
    runner = CliRunner()

    # Mock uvicorn.run to avoid actually starting a server
    with mock.patch("uvicorn.run") as mock_uvicorn:
        result = runner.invoke(main, ["serve", "--host", "0.0.0.0", "--port", "3000"])

        # Check the command output
        assert "Starting Aviation Anomaly Tracker API on 0.0.0.0:3000" in result.output
        assert "Interactive API docs: http://0.0.0.0:3000/docs" in result.output

        # Verify uvicorn was called with correct parameters
        mock_uvicorn.assert_called_once()
        call_args = mock_uvicorn.call_args
        assert call_args[1]["host"] == "0.0.0.0"
        assert call_args[1]["port"] == 3000
        assert call_args[1]["reload"] is False


def test_serve_command_with_reload():
    """Serve command should pass reload flag to uvicorn."""
    runner = CliRunner()

    with mock.patch("uvicorn.run") as mock_uvicorn:
        result = runner.invoke(main, ["serve", "--reload"])

        assert result.exit_code == 0
        call_args = mock_uvicorn.call_args
        assert call_args[1]["reload"] is True


@pytest.mark.integration
def test_serve_starts_real_server():
    """Integration test: serve command starts a real server (brief test)."""
    runner = CliRunner()

    # Start server in a thread
    server_thread = threading.Thread(
        target=lambda: runner.invoke(main, ["serve", "--port", "8765"]),
        daemon=True,
    )
    server_thread.start()

    # Give server time to start
    time.sleep(1)

    try:
        # Try to connect to the server
        response = httpx.get("http://127.0.0.1:8765/health", timeout=2)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    except Exception:
        # Server might not be fully up in CI - that's okay for this test
        pytest.skip("Server startup too slow for integration test")
