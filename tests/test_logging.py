"""Test structured logging with timing."""

import json
import logging
import time
from io import StringIO

import pytest

from aviation_anomaly.logging import configure_logging, log_operation


def test_logger_not_configured_initially():
    """Logger should not be configured with JSON format initially."""
    # Get a fresh logger
    logger = logging.getLogger("test_unconfigured")

    # Capture output
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    # Log a message
    logger.info("test message")
    output = stream.getvalue()

    # Should not be JSON formatted
    assert "test message" in output
    assert not output.startswith("{")

    # Clean up
    logger.removeHandler(handler)


def test_configure_logging_creates_json_formatter():
    """Configure logging should set up JSON formatted output."""
    # Configure logging
    logger = configure_logging("test_json")

    # Capture output
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logger.handlers[0].formatter)
    logger.addHandler(handler)

    # Log a message
    logger.info("test message", extra={"stage": "test"})
    output = stream.getvalue().strip()

    # Should be valid JSON
    log_entry = json.loads(output)

    # Should have required fields
    assert "timestamp" in log_entry
    assert "level" in log_entry
    assert log_entry["level"] == "INFO"
    assert "message" in log_entry
    assert log_entry["message"] == "test message"
    assert "stage" in log_entry
    assert log_entry["stage"] == "test"

    # Clean up
    logger.removeHandler(handler)


def test_log_operation_context_manager_tracks_duration():
    """log_operation context manager should track operation duration."""
    logger = configure_logging("test_timing")

    # Capture output
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logger.handlers[0].formatter)
    logger.addHandler(handler)

    # Use the context manager with a short operation
    with log_operation("test_op", logger):
        time.sleep(0.01)  # Sleep for 10ms

    # Get all log lines
    lines = stream.getvalue().strip().split("\n")
    assert len(lines) == 2  # Start and end messages

    # Check start message
    start_log = json.loads(lines[0])
    assert start_log["message"] == "Starting operation: test_op"
    assert start_log["operation"] == "test_op"

    # Check end message
    end_log = json.loads(lines[1])
    assert end_log["message"] == "Completed operation: test_op"
    assert end_log["operation"] == "test_op"
    assert "duration_ms" in end_log
    assert end_log["duration_ms"] >= 10  # At least 10ms
    assert end_log["duration_ms"] < 100  # But not too long

    # Clean up
    logger.removeHandler(handler)


def test_log_operation_handles_exceptions():
    """log_operation should log exceptions but not suppress them."""
    logger = configure_logging("test_exception")

    # Capture output
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logger.handlers[0].formatter)
    logger.addHandler(handler)

    # Use the context manager with an operation that fails
    with pytest.raises(ValueError):
        with log_operation("failing_op", logger):
            raise ValueError("Test error")

    # Get all log lines
    lines = stream.getvalue().strip().split("\n")
    assert len(lines) == 2  # Start and error messages

    # Check error message
    error_log = json.loads(lines[1])
    assert error_log["level"] == "ERROR"
    assert "Failed operation: failing_op" in error_log["message"]
    assert error_log["operation"] == "failing_op"
    assert "duration_ms" in error_log
    assert "error" in error_log
    assert error_log["error"] == "Test error"

    # Clean up
    logger.removeHandler(handler)
