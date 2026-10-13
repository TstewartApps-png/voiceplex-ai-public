"""
Logging configuration and utilities.

Comprehensive logging with correlation IDs.
"""

import logging
import sys
from contextvars import ContextVar
from typing import Any

from app.config import get_settings

# Context variable for correlation ID tracking across async operations
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


class CorrelationIdFilter(logging.Filter):
    """Logging filter that adds correlation ID to log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Add correlation ID to the log record."""
        record.correlation_id = correlation_id_var.get() or "-"
        return True


class JSONFormatter(logging.Formatter):
    """
    JSON log formatter for structured logging in production.

    Outputs logs in JSON format for easier parsing by log aggregators.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        import json
        from datetime import datetime, timezone

        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in (
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "message",
                "correlation_id",
            ):
                log_data[key] = value

        return json.dumps(log_data)


def setup_logging() -> None:
    """
    Configure application logging.

    Sets up handlers, formatters, and log levels based on environment.
    Uses JSON formatting in production, human-readable in development.
    """
    settings = get_settings()

    # Determine log level based on environment
    if settings.debug:
        log_level = logging.DEBUG
    elif settings.is_production:
        log_level = logging.INFO
    else:
        log_level = logging.DEBUG

    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # Add correlation ID filter
    correlation_filter = CorrelationIdFilter()
    console_handler.addFilter(correlation_filter)

    # Choose formatter based on environment
    if settings.is_production:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(correlation_id)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Set log levels for noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("motor").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("request").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # Silence PyMongo noise
    for logger_name in [
        "pymongo",
        "pymongo.connection",
        "pymongo.topology",
        "pymongo.serverSelection",
        "pymongo.command",
    ]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Log startup message
    logger = logging.getLogger(__name__)
    logger.info(
        f"Logging configured for {settings.app_env} environment (level: {logging.getLevelName(log_level)})"
    )


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the specified name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


def set_correlation_id(correlation_id: str) -> None:
    """
    Set the correlation ID for the current async context.

    Args:
        correlation_id: Unique identifier for request tracing
    """
    correlation_id_var.set(correlation_id)


def get_correlation_id() -> str | None:
    """
    Get the current correlation ID.

    Returns:
        Current correlation ID or None if not set
    """
    return correlation_id_var.get()


def generate_correlation_id() -> str:
    """
    Generate a new correlation ID.

    Returns:
        New UUID-based correlation ID
    """
    import uuid
    return str(uuid.uuid4())


class LoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that includes extra context in log messages.

    Useful for adding consistent context to all logs from a component.
    """

    def process(
        self, msg: str, kwargs: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Process the logging message and keyword arguments."""
        # Add extra context to the message
        extra = self.extra or {}
        context_str = " | ".join(f"{k}={v}" for k, v in extra.items())
        if context_str:
            msg = f"{context_str} | {msg}"
        return msg, kwargs
