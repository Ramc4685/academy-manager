"""Sentry error tracking (audit C2).

Errors-first: exceptions with stack traces, release/environment tagging, and
searchable `request_id`/`academy_id` tags. Performance tracing stays off unless
`V2_SENTRY_TRACES_SAMPLE_RATE` is raised. No DSN ⇒ no-op, so dev/test/CI keep
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
    from sentry_sdk.types import Event, Hint

log = logging.getLogger(__name__)


def configure_error_tracking(settings: Settings) -> None:
    if not settings.sentry_dsn:
        log.info("Sentry DSN not configured; error tracking disabled.")
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
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
        integrations=[StarletteIntegration(), FastApiIntegration()],
        before_send=_tag_event,
    )
    log.info("Sentry error tracking enabled (env=%s).", settings.env)


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
