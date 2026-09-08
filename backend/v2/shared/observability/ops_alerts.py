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
* :func:`cron_checkin` — Sentry Crons check-ins around a scheduled job's
  body, opt-in per job id (``settings.sentry_cron_jobs``) because the free
  plan includes a single monitor. This is the layer that notices a job that
  *stopped firing*, which no exception listener can see; the ops digest's
  stale-job section is the zero-cost counterpart for every other job.

Sentry availability is guarded exactly the way ``errors.py`` does it: the
import is optional, and with no DSN configured ``sentry_sdk`` was never
initialised, so every call here degrades to a no-op. Structured logging always
happens regardless of Sentry.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
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


def should_report_failure(consecutive_failures: int) -> bool:
    """Backoff for a hot retry loop: report the 1st, 10th, then every 100th.

    A tight poll loop that keeps failing (a Mongo outage, say) is one incident,
    not one incident per iteration. The first failure reports immediately so the
    alert is not delayed; the rest are throttled so the issue stays readable and
    the quota survives.
    """
    if consecutive_failures <= 0:
        return False
    if consecutive_failures in (1, 10):
        return True
    return consecutive_failures % 100 == 0


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
            # (process busy/asleep past ``misfire_grace_time``). Reported at
            # warning, not error: even with the 30s grace time configured in
            # main.py, a single misfire on a 60s interval job is usually a
            # transient event-loop stall, not an outage. A real outage shows up
            # as a run of them.
            log.warning("scheduler_job_missed job_id=%s", job_id, extra=extra)
            capture_message(f"Scheduler job missed: {job_id}", level="warning")
    except Exception:  # pragma: no cover - defensive; listeners must not raise
        log.exception("scheduler_job_event_listener_failed")


@asynccontextmanager
async def cron_checkin(
    job_id: str, *, schedule: Mapping[str, Any], settings: Any
) -> AsyncIterator[None]:
    """Bracket a scheduled job body with Sentry Crons check-ins.

    ``schedule`` is the job's Sentry ``monitor_config`` minus the timezone
    (``{"schedule": {...}, "checkin_margin": ..., "max_runtime": ...}``); the
    timezone is stamped from ``settings.scheduler_tz`` so the monitor's
    expectation matches the APScheduler clock. Sending the config with every
    check-in keeps the monitor upserted from code — nothing to click together
    in the Sentry UI, and a changed schedule follows the next deploy.

    A no-op unless Sentry is initialised AND ``job_id`` is allowlisted in
    ``settings.sentry_cron_jobs``. A failing check-in (transport error, bad
    config) is logged and never reaches the job: the switch must not be able
    to break the thing it watches.
    """
    sentry_sdk = _active_sentry()
    if sentry_sdk is None or job_id not in tuple(getattr(settings, "sentry_cron_jobs", ())):
        yield
        return
    monitor_config = {**schedule, "timezone": settings.scheduler_tz}
    check_in_id = _checkin(sentry_sdk, job_id, None, "in_progress", monitor_config)
    if check_in_id is None:
        yield
        return
    started = time.monotonic()
    try:
        yield
    except BaseException:
        _checkin(sentry_sdk, job_id, check_in_id, "error", monitor_config, started)
        raise
    else:
        _checkin(sentry_sdk, job_id, check_in_id, "ok", monitor_config, started)


def _checkin(
    sentry_sdk: Any,
    job_id: str,
    check_in_id: str | None,
    status: str,
    monitor_config: dict[str, Any],
    started: float | None = None,
) -> str | None:
    try:
        return str(
            sentry_sdk.crons.capture_checkin(
                monitor_slug=job_id,
                check_in_id=check_in_id,
                status=status,
                duration=None if started is None else time.monotonic() - started,
                monitor_config=monitor_config,
            )
        )
    except Exception:
        log.warning("sentry_cron_checkin_failed job_id=%s status=%s", job_id, status, exc_info=True)
        return None
