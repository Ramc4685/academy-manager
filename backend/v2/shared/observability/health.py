"""Real liveness reporting for ``/api/v2/healthz`` (issue #429).

The endpoint used to return ``{"status": "ok"}`` unconditionally. Fly polls it
every 30s (``backend/fly.toml``), so a wedged scheduler, a dead dispatcher
task, or a lost Mongo connection stayed green forever and no machine was ever
restarted.

Two rules shape what is allowed to return 503:

1. **Only restartable faults fail the check.** Fly's response to a failed
   check is to restart the machine, so a fault a restart cannot fix must not
   be reported as unhealthy — that produces a boot loop instead of a fix.
   A stale job heartbeat is reported (``jobs.<id>.stale``, from the same
   ``JOB_STALE_AFTER`` table the ops digest alerts on) but never fails the
   check: restarting the process will not make a monthly job run.
2. **A component that was never wired is not a fault.** In production the
   lifespan wires Mongo, the scheduler, and the dispatcher before Uvicorn
   serves the first request, so "missing" only ever means "this app was
   assembled differently" (an embedded or test app). Those are reported as
   skipped rather than failing.

Response shape note: nested check results use ``ok: bool``, deliberately NOT
a nested ``"status"`` key. ``scripts/smoke/production_smoke.sh`` greps the raw
body for ``"status":"ok"``, so a nested healthy check inside an overall
degraded response would otherwise let a broken API pass the deploy smoke test.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from backend.v2.shared.observability.ops_digest import JOB_RUNS_COLLECTION, stale_jobs

log = logging.getLogger(__name__)

#: Fly's check timeout is 5s. Ping well inside it so a slow-but-alive Mongo is
#: reported as a failure by us (with a reason) rather than as a timeout by Fly
#: (without one).
MONGO_PING_TIMEOUT_SECONDS = 2.0

OK = "ok"
DEGRADED = "degraded"


async def build_health_report(
    *,
    db: Any | None = None,
    scheduler: Any | None = None,
    dispatcher: Any | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """Return ``(report, healthy)``.

    ``healthy`` is False only when a wired component is actually broken, which
    is what the caller turns into a 503.
    """
    now = now or datetime.now(UTC)
    checks: dict[str, Any] = {
        "mongo": await _check_mongo(db),
        "scheduler": _check_scheduler(scheduler),
        "dispatcher": _check_dispatcher(dispatcher),
    }
    healthy = all(check.get("ok", True) for check in checks.values())

    report: dict[str, Any] = {
        "status": OK if healthy else DEGRADED,
        "checks": checks,
    }
    # Only read heartbeats once the ping proved Mongo is answering. Against a
    # dead Mongo this query would block on the driver's server-selection
    # timeout (30s by default) — six times Fly's check budget — turning a
    # clean 503 into a hung request that Fly can only score as a timeout.
    if checks["mongo"].get("ok") and not checks["mongo"].get("skipped"):
        jobs = await _job_heartbeats(db, now)
        if jobs:
            # Informational only — excluded from `healthy`, see rule 1.
            report["jobs"] = jobs
    return report, healthy


async def _check_mongo(db: Any | None) -> dict[str, Any]:
    if db is None:
        return {"ok": True, "skipped": "not wired"}
    started = time.perf_counter()
    try:
        await asyncio.wait_for(db.command("ping"), timeout=MONGO_PING_TIMEOUT_SECONDS)
    except TimeoutError:
        return {"ok": False, "error": "ping timed out"}
    except Exception as exc:
        log.warning("healthz_mongo_ping_failed", exc_info=True)
        return {"ok": False, "error": type(exc).__name__}
    return {"ok": True, "latency_ms": round((time.perf_counter() - started) * 1000, 1)}


def _check_scheduler(scheduler: Any | None) -> dict[str, Any]:
    if scheduler is None:
        return {"ok": True, "skipped": "not wired"}
    try:
        running = bool(scheduler.running)
        job_count = len(scheduler.get_jobs())
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
    if not running:
        return {"ok": False, "error": "scheduler not running"}
    return {"ok": True, "jobs": job_count}


def _check_dispatcher(dispatcher: Any | None) -> dict[str, Any]:
    if dispatcher is None:
        return {"ok": True, "skipped": "not wired"}
    is_running = getattr(dispatcher, "is_running", None)
    if not callable(is_running):
        return {"ok": True, "skipped": "no liveness signal"}
    try:
        if not is_running():
            # The outbox loop has stopped: events are being written and never
            # dispatched. Nothing else notices, and a restart does fix it.
            return {"ok": False, "error": "dispatcher task stopped"}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
    return {"ok": True}


async def _job_heartbeats(db: Any | None, now: datetime) -> dict[str, Any]:
    """Last-tick age per scheduled job, for an external uptime monitor.

    Best-effort: this is a diagnostic, so a read failure returns nothing rather
    than failing a health check that Mongo itself already covers.
    """
    if db is None:
        return {}
    try:
        docs = await asyncio.wait_for(_read_job_docs(db), timeout=MONGO_PING_TIMEOUT_SECONDS)
    except Exception:
        # Bounded even though the ping already succeeded: a responsive server
        # is not proof that this read is. The health verdict is already
        # decided, so losing the diagnostic beats delaying the response.
        # (TimeoutError is an Exception, so the wait_for timeout lands here.)
        log.warning("healthz_job_heartbeat_read_failed", exc_info=True)
        return {}

    jobs: dict[str, Any] = {}
    ticks: dict[str, Any] = {}
    for doc in docs:
        name = doc.get("_id")
        if not isinstance(name, str):
            continue
        ticks[name] = doc.get("last_tick_at")
        jobs[name] = {
            "last_tick_age_seconds": _age_seconds(doc.get("last_tick_at"), now),
            "last_run_age_seconds": _age_seconds(doc.get("recorded_at"), now),
            "stale": False,
        }
    # Dead-man flag (informational, rule 1): a job past its expected tick age,
    # or one that never recorded a heartbeat, is listed as stale so an external
    # monitor can alert on it without parsing ages against its own table.
    for job in stale_jobs(ticks, now):
        entry = jobs.setdefault(
            job.job_id, {"last_tick_age_seconds": None, "last_run_age_seconds": None}
        )
        entry["stale"] = True
    return jobs


async def _read_job_docs(db: Any) -> list[dict[str, Any]]:
    cursor = db[JOB_RUNS_COLLECTION].find({}, {"last_tick_at": 1, "recorded_at": 1})
    return [doc async for doc in cursor]


def _age_seconds(stamp: Any, now: datetime) -> int | None:
    if not isinstance(stamp, datetime):
        return None
    # Mongo hands back naive UTC datetimes; treat them as UTC rather than
    # letting the subtraction raise and take the whole endpoint down.
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return max(int((now - stamp).total_seconds()), 0)
