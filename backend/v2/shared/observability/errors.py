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
import re
from typing import TYPE_CHECKING

from backend.v2.shared.config import Settings
from backend.v2.shared.observability.request_context import current_request_id
from backend.v2.shared.tenancy.context import TenantContextUnset, current_academy_id

if TYPE_CHECKING:
    from sentry_sdk.scrubber import EventScrubber
    from sentry_sdk.types import Event, Hint, Log

log = logging.getLogger(__name__)

# Domain field names that hold personal data (#707). ``send_default_pii=False``
# never covered frame locals: an unhandled error at a use case captures the
# whole ``Student(...)`` repr, child name and emergency phone included. These
# keys are redacted wherever they appear — as dict keys (request body, extra,
# structured locals) and inside repr/JSON text (``full_name='Ada'``,
# ``'phone': '555'``) — on top of the SDK's own secrets denylist.
PII_DENYLIST: tuple[str, ...] = (
    "full_name",
    "first_name",
    "last_name",
    "emergency_contact_name",
    "emergency_contact_phone",
    "phone",
    "email",
)
# Prefix matches: ``guardian_name``, ``guardian_email``, ``guardian_phone``...
PII_KEY_PREFIXES: tuple[str, ...] = ("guardian_",)

_FILTERED = "'[Filtered]'"


def _pii_text_pattern() -> re.Pattern[str]:
    keys = "|".join(re.escape(key) for key in PII_DENYLIST)
    prefixed = "|".join(re.escape(prefix) + r"\w*" for prefix in PII_KEY_PREFIXES)
    return re.compile(
        rf"(?P<key>\b(?:{keys}|{prefixed})\b)"
        # ``key='v'`` (dataclass/pydantic repr) or ``'key': 'v'`` (dict repr / JSON).
        r"(?P<sep>[\"']?\s*[=:]\s*)"
        r"(?P<value>'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|[^,)\]}\s]+)",
        re.IGNORECASE,
    )


_PII_TEXT = _pii_text_pattern()


def scrub_pii_text(text: str) -> str:
    """Redact ``<pii key>=<value>`` / ``'<pii key>': <value>`` pairs inside a string."""
    return _PII_TEXT.sub(lambda m: f"{m.group('key')}{m.group('sep')}{_FILTERED}", text)


def build_event_scrubber() -> EventScrubber:
    """SDK denylist + our PII keys, recursive, and text-aware for repr'd locals.

    Frame locals reach the scrubber already serialised (``serialize_frame``
    calls ``safe_repr`` on every non-collection local), so a ``student`` local
    is the *string* ``"Student(id='stu_1', full_name='Ada', ...)"`` under a key
    the denylist would never match. The subclass therefore also scrubs string
    values, and strings nested in lists, which the base class skips.
    """
    from sentry_sdk._types import AnnotatedValue
    from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

    sensitive_keys = frozenset(key.lower() for key in [*DEFAULT_DENYLIST, *PII_DENYLIST])

    class PiiEventScrubber(EventScrubber):
        def _is_sensitive_key(self, key: str) -> bool:
            lowered = key.lower()
            return lowered in sensitive_keys or lowered.startswith(PII_KEY_PREFIXES)

        def scrub_dict(self, d: object) -> None:
            if not isinstance(d, dict):
                return
            for key, value in d.items():
                if isinstance(key, str) and self._is_sensitive_key(key):
                    d[key] = AnnotatedValue.substituted_because_contains_sensitive_data()
                elif isinstance(value, str):
                    d[key] = scrub_pii_text(value)
                elif self.recursive:
                    self.scrub_dict(value)
                    self.scrub_list(value)

        def scrub_list(self, lst: object) -> None:
            if not isinstance(lst, list):
                return
            for index, value in enumerate(lst):
                if isinstance(value, str):
                    lst[index] = scrub_pii_text(value)
                else:
                    self.scrub_dict(value)
                    self.scrub_list(value)

    return PiiEventScrubber(denylist=[*DEFAULT_DENYLIST, *PII_DENYLIST], recursive=True)


def bind_request_user(*, user_id: str, persona: str, academy_id: str) -> None:
    """Attach the signed-in user to the current Sentry scope (#707).

    Only the opaque ``user_id`` and the persona ever leave the box — no email,
    no name — which is enough for Sentry's "users affected" count and for
    filtering an issue to one persona. Best-effort by contract: every failure
    is swallowed so an SDK fault can never influence the auth path that calls
    this. No-op without an active client (no DSN, tests).
    """
    try:
        import sentry_sdk
    except ImportError:
        return
    try:
        if not sentry_sdk.get_client().is_active():
            return
        sentry_sdk.set_user({"id": user_id, "segment": persona})
        sentry_sdk.set_tag("academy_id", academy_id)
        sentry_sdk.set_tag("persona", persona)
    except Exception:
        log.debug("sentry_user_context_failed", exc_info=True)


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
        # Frame locals stay on (they are what confirmed #706's root cause);
        # the scrubber below strips student/guardian PII out of them.
        include_local_variables=True,
        event_scrubber=build_event_scrubber(),
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
