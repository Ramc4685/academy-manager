"""Sentry error tracking (audit C2).

Errors-first: exceptions with stack traces, release/environment tagging, and
searchable `request_id`/`academy_id` tags. Performance tracing stays off unless
`V2_SENTRY_TRACES_SAMPLE_RATE` is raised.

Logs: with a DSN set, INFO+ records from the JSON logging pipeline are also
forwarded to Sentry Logs (30-day retention, searchable by `request_id`), which
replaces shipping Fly's ~7-day stdout elsewhere. `_keep_log` is the volume
guard: DEBUG never leaves the box, the health probe and other pure noise are
dropped, so a month of this app stays far inside the free 5 GB. No DSN ⇒ no-op, so dev/test/CI keep
current behavior. Import guarded like `tracing.py` so environments without the
package still boot.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from backend.v2.shared.config import Settings
from backend.v2.shared.observability.request_context import current_request_id
from backend.v2.shared.tenancy.context import TenantContextUnset, current_academy_id

if TYPE_CHECKING:
    from sentry_sdk.types import Event, Hint, Log

log = logging.getLogger(__name__)


def configure_error_tracking(settings: Settings) -> None:
    if not settings.sentry_dsn:
        log.info("Sentry DSN not configured; error tracking disabled.")
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        log.info("sentry-sdk not installed; error tracking disabled.")
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.env,
        release=resolve_release(),
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # Events carry ids/tags, never request payloads or user PII.
        send_default_pii=False,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            # Breadcrumbs from INFO, events only from ERROR (unchanged), and the
            # same INFO+ records forwarded as Sentry Logs when enabled.
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR,
                sentry_logs_level=logging.INFO if settings.sentry_logs_enabled else None,
            ),
        ],
        enable_logs=settings.sentry_logs_enabled,
        before_send=_tag_event,
        before_send_log=_keep_log,
    )
    log.info(
        "Sentry error tracking enabled (env=%s, logs=%s).",
        settings.env,
        "on" if settings.sentry_logs_enabled else "off",
    )


def resolve_release() -> str | None:
    """Release tag for Sentry: explicit env override, else Fly's image ref.

    Fly stamps ``FLY_IMAGE_REF`` (registry path + deploy tag) on every machine,
    so each deploy gets its own release without a build-time step. ``None``
    when nothing is set — Sentry treats that as "unversioned", never an error.
    """
    for name in ("V2_SENTRY_RELEASE", "SENTRY_RELEASE", "FLY_IMAGE_REF"):
        value = os.environ.get(name)
        if value:
            return value
    return None


# Loggers whose lines carry no diagnostic value off-box. The health probe is
# already DEBUG in RequestLogMiddleware; these are belt-and-braces.
_DROP_LOGGERS = ("uvicorn.access",)
_DROP_MESSAGE_PREFIXES = ("GET /api/v2/healthz ",)


def _keep_log(log_entry: Log, hint: Hint) -> Log | None:
    """Sentry Logs volume guard: return None to drop a record before it is sent."""
    attributes = log_entry.get("attributes") or {}
    logger_name = str(attributes.get("logger.name") or attributes.get("logger") or "")
    if logger_name in _DROP_LOGGERS:
        return None
    body = str(log_entry.get("body") or "")
    if body.startswith(_DROP_MESSAGE_PREFIXES):
        return None
    if log_entry.get("severity_number", 9) < 9:  # below INFO per OTel severity numbers
        return None
    return log_entry


def _tag_event(event: Event, hint: Hint) -> Event | None:
    """Event processor: read correlation contextvars at event time."""
    tags = event.setdefault("tags", {})
    request_id = current_request_id()
    if request_id is not None:
        tags.setdefault("request_id", request_id)
    try:
        tags.setdefault("academy_id", current_academy_id())
    except TenantContextUnset:
        pass
    return event
