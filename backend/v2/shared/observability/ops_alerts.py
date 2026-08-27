"""Outbound alerting for background failures (issue #428).

Before this module the only errors that reached Sentry were request-path ones
(``configure_error_tracking`` installs the Starlette/FastAPI integrations):
APScheduler job crashes and the outbox dispatcher's top-level loop guard were
logged locally and nowhere else.

Two entry points:

* :func:`handle_scheduler_job_event` — the APScheduler listener registered for
  ``EVENT_JOB_ERROR | EVENT_JOB_MISSED`` in ``main.py``.
* :func:`capture_exception` / :func:`capture_message` — thin, always-safe
  wrappers used by the dispatcher loop guard.

Sentry availability is guarded exactly the way ``errors.py`` does it: the
import is optional, and with no DSN configured ``sentry_sdk`` was never
initialised, so every call here degrades to a no-op. Structured logging always
happens regardless of Sentry.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def _active_sentry() -> Any | None:
    """Return the ``sentry_sdk`` module iff it is installed AND initialised.

    ``configure_error_tracking`` skips ``sentry_sdk.init`` when ``SENTRY_DSN``
    is unset, which leaves a non-recording client behind; sending to it is
    harmless but we check explicitly so callers can log the difference.
    """
    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover - sentry-sdk is in the venv
        return None
    try:
        client = sentry_sdk.get_client()
    except AttributeError:  # pragma: no cover - sentry-sdk < 2.0
        return None
    if client is None or not client.is_active():
        return None
    return sentry_sdk


def capture_exception(exc: BaseException | None = None) -> bool:
    """Report ``exc`` to Sentry when configured. Returns True iff sent."""
    sentry_sdk = _active_sentry()
    if sentry_sdk is None:
        return False
    sentry_sdk.capture_exception(exc)
    return True


def capture_message(message: str, *, level: str = "error") -> bool:
    """Report a message (no exception object) to Sentry when configured."""
    sentry_sdk = _active_sentry()
    if sentry_sdk is None:
        return False
    sentry_sdk.capture_message(message, level=level)
    return True


def handle_scheduler_job_event(event: Any) -> None:
    """APScheduler listener for ``EVENT_JOB_ERROR | EVENT_JOB_MISSED``.

    Must never raise: APScheduler invokes listeners inside its own dispatch
    loop, and an exception here would be swallowed after taking down the
    notification for every other listener.
    """
    try:
        job_id = getattr(event, "job_id", None)
        exc = getattr(event, "exception", None)
        scheduled_run_time = getattr(event, "scheduled_run_time", None)
        extra = {
            "job_id": job_id,
            "event_code": getattr(event, "code", None),
            "scheduled_run_time": (
                scheduled_run_time.isoformat() if scheduled_run_time is not None else None
            ),
        }
        if exc is not None:
            log.error(
                "scheduler_job_error job_id=%s",
                job_id,
                extra=extra,
                exc_info=exc,
            )
            capture_exception(exc)
        else:
            # EVENT_JOB_MISSED carries no exception — the run never happened
            # (process busy/asleep past ``misfire_grace_time``).
            log.error("scheduler_job_missed job_id=%s", job_id, extra=extra)
            capture_message(f"Scheduler job missed: {job_id}")
    except Exception:  # pragma: no cover - defensive; listeners must not raise
        log.exception("scheduler_job_event_listener_failed")
