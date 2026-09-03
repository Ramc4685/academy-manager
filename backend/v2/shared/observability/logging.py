"""Structured JSON logging.

Each log record carries trace_id, span_id (if active), and request-scoped
fields when called from within a request (academy_id, user_id, request_id).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from backend.v2.shared.config import get_settings
from backend.v2.shared.observability.request_context import ContextLogFilter

# Attributes every LogRecord carries (see ``logging.LogRecord``); anything else
# on a record arrived via ``extra=`` (or a filter) and belongs in the payload.
_STANDARD_RECORD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "taskName",
    }
)
_RESERVED_KEYS = frozenset({"timestamp", "level", "logger", "message", "exception"})

# Uvicorn installs its own plain-text handlers on these; re-routing them through
# the root handler gives access lines and "Exception in ASGI application"
# tracebacks the same JSON shape and request_id as application logs.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Everything passed via ``extra=`` (job_id, checks, ...) plus what
        # ContextLogFilter stamps (request_id/academy_id) and OpenTelemetry
        # attaches (trace_id/span_id). Reserved keys are never clobbered.
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_ATTRS or key in _RESERVED_KEYS or key.startswith("_"):
                continue
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    # Reset handlers so reconfiguration is safe under reload.
    root.handlers.clear()
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.addFilter(ContextLogFilter())
    if settings.log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s :: %(message)s")
        )
    root.addHandler(handler)
    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
