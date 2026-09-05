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
_UVICORN_ACCESS_LOGGER = "uvicorn.access"

# Third-party loggers that chatter at INFO on every tick or request (APScheduler's
# "Running job ..."/"executed successfully" pair once a minute from the webhook
# drain, stripe's per-request URL line, driver connection churn). They carry no
# application signal at INFO but dominate Sentry Logs volume, so they are held at
# WARNING unless the root level is DEBUG (developers asking for everything get it).
QUIET_THIRD_PARTY_LOGGERS: tuple[tuple[str, int], ...] = (
    ("apscheduler.executors.default", logging.WARNING),
    ("apscheduler.scheduler", logging.WARNING),
    ("apscheduler.jobstores", logging.WARNING),
    ("stripe", logging.WARNING),
    ("pymongo", logging.WARNING),
    ("httpx", logging.WARNING),
    ("httpcore", logging.WARNING),
    ("urllib3", logging.WARNING),
)


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
        # ``uvicorn --no-access-log`` disables access logging by leaving
        # ``uvicorn.access`` with no handlers AND ``propagate=False`` (see
        # uvicorn.config.Config.configure_logging). This runs later, from the
        # app lifespan, so blindly re-enabling propagation would resurrect the
        # access log on top of RequestLogMiddleware's line -- every request
        # logged twice and the health probe back at INFO every 30s. Preserve
        # that disabled state; an enabled access logger (uvicorn's default
        # dictConfig gives it a handler) is re-routed like the others.
        if (
            name == _UVICORN_ACCESS_LOGGER
            and not uvicorn_logger.handlers
            and not uvicorn_logger.propagate
        ):
            continue
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    _quiet_third_party_loggers(root.level)


def _quiet_third_party_loggers(root_level: int) -> None:
    """Hold chatty third-party loggers at WARNING unless the root is at DEBUG."""
    for name, level in QUIET_THIRD_PARTY_LOGGERS:
        third_party = logging.getLogger(name)
        if root_level <= logging.DEBUG:
            third_party.setLevel(logging.NOTSET)
        else:
            third_party.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
