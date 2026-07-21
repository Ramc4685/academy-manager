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


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # ContextLogFilter stamps request_id/academy_id; OpenTelemetry attaches
        # trace_id/span_id when a span is active.
        for attr in ("trace_id", "span_id", "academy_id", "user_id", "request_id"):
            value = getattr(record, attr, None)
            if value is not None:
                payload[attr] = value
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


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
