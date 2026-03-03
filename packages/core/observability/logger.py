"""Structured logging with context.

All logs include:
- session_id
- stage_id
- agent_name
- timestamp
- trace_id (for distributed tracing)
"""

import json
import logging
import sys
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

# Context variables for log correlation
_session_id: ContextVar[str | None] = ContextVar("session_id", default=None)
_stage_id: ContextVar[str | None] = ContextVar("stage_id", default=None)
_agent_name: ContextVar[str | None] = ContextVar("agent_name", default=None)
_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)


class StructuredLogFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "source": f"{record.filename}:{record.lineno}",
        }

        # Add correlation context
        session_id = _session_id.get()
        stage_id = _stage_id.get()
        agent_name = _agent_name.get()
        trace_id = _trace_id.get()

        if session_id:
            log_data["session_id"] = session_id
        if stage_id:
            log_data["stage_id"] = stage_id
        if agent_name:
            log_data["agent_name"] = agent_name
        if trace_id:
            log_data["trace_id"] = trace_id

        # Add extra fields from record
        if hasattr(record, "extra"):
            log_data.update(record.extra)

        # Add exception info
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


class ContextualLogger:
    """Logger with context support."""

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def _log(
        self,
        level: int,
        message: str,
        extra: dict[str, Any] | None = None,
        **kwargs,
    ) -> None:
        """Log with context."""
        # Build extra dict
        log_extra = extra or {}
        log_extra.update(kwargs)

        # Create log record with extra data
        record = self._logger.makeRecord(
            self._logger.name,
            level,
            "(unknown file)",
            0,
            message,
            (),
            None,
        )
        record.extra = log_extra

        self._logger.handle(record)

    def debug(self, message: str, **kwargs) -> None:
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        self._log(logging.ERROR, message, **kwargs)

    def exception(self, message: str, **kwargs) -> None:
        self._log(logging.ERROR, message, exc_info=True, **kwargs)


class LogContext:
    """Context manager for log correlation.

    Usage:
        with LogContext(session_id="abc", stage_id="def", agent_name="pm_agent"):
            logger.info("Processing...")
    """

    def __init__(
        self,
        session_id: str | None = None,
        stage_id: str | None = None,
        agent_name: str | None = None,
        trace_id: str | None = None,
    ):
        self.session_id = session_id
        self.stage_id = stage_id
        self.agent_name = agent_name
        self.trace_id = trace_id or str(uuid.uuid4())

        # Tokens for resetting context
        self._tokens = []

    def __enter__(self) -> "LogContext":
        """Enter context."""
        if self.session_id:
            self._tokens.append((_session_id, _session_id.set(self.session_id)))
        if self.stage_id:
            self._tokens.append((_stage_id, _stage_id.set(self.stage_id)))
        if self.agent_name:
            self._tokens.append((_agent_name, _agent_name.set(self.agent_name)))
        if self.trace_id:
            self._tokens.append((_trace_id, _trace_id.set(self.trace_id)))

        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context."""
        for var, token in reversed(self._tokens):
            var.reset(token)


def get_logger(name: str) -> ContextualLogger:
    """Get contextual logger.

    Args:
        name: Logger name

    Returns:
        ContextualLogger instance
    """
    return ContextualLogger(name)


def configure_logging(
    level: str = "INFO",
    json_format: bool = True,
) -> None:
    """Configure structured logging.

    Args:
        level: Log level
        json_format: Use JSON format
    """
    handlers = [logging.StreamHandler(sys.stdout)]

    if json_format:
        formatter = StructuredLogFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(
        level=getattr(logging, level.upper()),
        handlers=handlers,
        force=True,
    )


# Convenience context managers


@contextmanager
def session_context(session_id: str):
    """Context manager for session-scoped logging."""
    with LogContext(session_id=session_id):
        yield


@contextmanager
def stage_context(session_id: str, stage_id: str, agent_name: str):
    """Context manager for stage-scoped logging."""
    with LogContext(
        session_id=session_id,
        stage_id=stage_id,
        agent_name=agent_name,
    ):
        yield
