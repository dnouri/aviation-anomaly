"""Structured JSON logging with timing support."""

import json
import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime


class JSONFormatter(logging.Formatter):
    """Format log records as JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON string."""
        log_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }

        # Add any extra fields from the record
        if hasattr(record, "stage"):
            log_data["stage"] = record.stage
        if hasattr(record, "operation"):
            log_data["operation"] = record.operation
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms
        if hasattr(record, "error"):
            log_data["error"] = record.error

        return json.dumps(log_data)


def configure_logging(name: str = "aviation_anomaly") -> logging.Logger:
    """Configure structured JSON logging.

    Args:
        name: Logger name

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Remove any existing handlers
    logger.handlers.clear()

    # Create console handler with JSON formatter
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)

    # Prevent propagation to root logger
    logger.propagate = False

    return logger


@contextmanager
def log_operation(operation: str, logger: logging.Logger) -> Generator[None]:
    """Context manager to log and time operations.

    Args:
        operation: Name of the operation being performed
        logger: Logger instance to use

    Example:
        with log_operation("data_extraction", logger):
            # Do some work
            pass
    """
    start_time = time.perf_counter()

    # Log start of operation
    logger.info(f"Starting operation: {operation}", extra={"operation": operation})

    try:
        yield
    except Exception as e:
        # Log error with duration
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error(
            f"Failed operation: {operation}",
            extra={"operation": operation, "duration_ms": duration_ms, "error": str(e)},
        )
        raise
    else:
        # Log successful completion with duration
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.info(f"Completed operation: {operation}", extra={"operation": operation, "duration_ms": duration_ms})
