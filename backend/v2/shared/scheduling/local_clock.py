"""Run a daily job at each academy's own local wall-clock time.

Settings overhaul Phase 4 (HARDCODED #8, MASTER R09). The fixed-hour night
jobs used to be APScheduler crons in ``settings.scheduler_tz`` (Chicago in
production), so every tenant ran on BLNO's clock. Each job now ticks hourly
and, per academy, runs once the academy's local time reaches the job's target
wall-clock time on that local date.

"Once per local day" is a run marker in ``scheduler_run_markers``, one per
``(job, academy_id, local_date)``. The marker's ``_id`` is that triple, so the
always-present ``_id`` index makes the claim atomic even where migration 0210
(the compound unique index and the 60-day TTL) has not been applied: a second
tick, or a second machine, collides on the insert and does nothing.

Why a marker instead of an exact-hour match:

* Spring forward: a 02:00 target does not exist on that local day. The next
  tick (03:00) sees local time past the target and runs; it still runs once.
* Fall back: the 01:00 hour repeats. The marker already exists for that
  local date, so the second pass is a no-op.
* A missed tick (deploy, restart, stall) catches up on the next tick of the
  same local day instead of losing the day.

Failure: a run that raises marks its marker ``failed``; a later tick of the
SAME local date re-claims it, up to ``MAX_ATTEMPTS`` claims in all. A run
whose process died mid-flight (marker stuck ``running``) is re-claimable
after ``STALE_RUNNING_AFTER``, counted against the same attempt budget. A new
local date is a new marker, so a job never retries a past day here: every job
body is already a sweep of what is due, so the next day's run covers it.

One academy's failure is logged and reported and never stops the others.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

from backend.v2.shared.observability.ops_alerts import capture_exception
from backend.v2.shared.tenancy.context import tenant_scope

log = logging.getLogger(__name__)

MARKERS_COLLECTION = "scheduler_run_markers"

#: Claims per (job, academy, local date), including the first. Hourly ticks,
#: so three failures cost at most the next two hours of that day.
MAX_ATTEMPTS = 3

#: A ``running`` marker older than this belongs to a process that died (every
#: job's distributed lease is 30 minutes or less), so it may be re-claimed.
STALE_RUNNING_AFTER = timedelta(hours=2)

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class LocalDailyTime:
    """The academy-local wall-clock time a daily job is due at."""

    hour: int
    minute: int = 0

    def reached_by(self, local_now: datetime) -> bool:
        """True once ``local_now``'s wall clock is at or past this time."""
        return (local_now.hour, local_now.minute) >= (self.hour, self.minute)


@dataclass
class LocalDailyRunSummary:
    ran: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    not_due: list[str] = field(default_factory=list)
    already_claimed: list[str] = field(default_factory=list)


def marker_id(job: str, academy_id: str, local_date: date) -> str:
    return f"{job}:{academy_id}:{local_date.isoformat()}"


def _as_aware_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def claim_local_run(
    db: Any,
    *,
    job: str,
    academy_id: str,
    local_date: date,
    now: datetime,
    worker_id: str,
) -> bool:
    """Claim this (job, academy, local date). True iff this caller should run it."""
    collection = db[MARKERS_COLLECTION]
    key = marker_id(job, academy_id, local_date)
    try:
        await collection.insert_one(
            {
                "_id": key,
                "job": job,
                "academy_id": academy_id,
                "local_date": local_date.isoformat(),
                "status": STATUS_RUNNING,
                "attempts": 1,
                "worker_id": worker_id,
                "claimed_at": now,
                "created_at": now,
            }
        )
        return True
    except DuplicateKeyError:
        pass
    # Already claimed today. Re-claim only a failed run, or a run whose
    # process died, and only while the attempt budget lasts.
    reclaimed = await collection.find_one_and_update(
        {
            "_id": key,
            "academy_id": academy_id,
            "attempts": {"$lt": MAX_ATTEMPTS},
            "$or": [
                {"status": STATUS_FAILED},
                {"status": STATUS_RUNNING, "claimed_at": {"$lt": now - STALE_RUNNING_AFTER}},
            ],
        },
        {
            "$set": {"status": STATUS_RUNNING, "worker_id": worker_id, "claimed_at": now},
            "$inc": {"attempts": 1},
        },
    )
    return reclaimed is not None


async def _finish_local_run(
    db: Any,
    *,
    job: str,
    academy_id: str,
    local_date: date,
    status: str,
    error: str | None = None,
) -> None:
    update: dict[str, Any] = {"status": status, "finished_at": datetime.now(UTC)}
    if error is not None:
        update["last_error"] = error[:500]
    try:
        await db[MARKERS_COLLECTION].update_one(
            {"_id": marker_id(job, academy_id, local_date), "academy_id": academy_id},
            {"$set": update},
        )
    except Exception:
        # A lost "done" leaves the marker ``running``: it is then re-claimable
        # only after STALE_RUNNING_AFTER, which bounds any repeat to the attempt
        # budget. Never let bookkeeping fail the tick.
        log.warning(
            "scheduler_run_marker_update_failed job=%s academy=%s", job, academy_id, exc_info=True
        )


async def run_daily_at_local_time(
    *,
    db: Any,
    job: str,
    at: LocalDailyTime,
    academy_ids: Iterable[str],
    zone_for: Callable[[str], Awaitable[str]],
    run: Callable[[str, datetime], Awaitable[None]],
    now: datetime,
    worker_id: str,
) -> LocalDailyRunSummary:
    """One tick of a per-academy daily job.

    For each academy: read its zone, and when its local wall clock has reached
    ``at`` and nobody has run ``job`` for it on this local date, claim the
    marker and call ``run(academy_id, local_now)`` inside the academy's
    ``tenant_scope``. ``now`` is any aware instant (the tick time).
    """
    summary = LocalDailyRunSummary()
    instant = _as_aware_utc(now)
    for academy_id in academy_ids:
        local_date: date | None = None
        try:
            local_now = instant.astimezone(ZoneInfo(await zone_for(academy_id)))
            if not at.reached_by(local_now):
                summary.not_due.append(academy_id)
                continue
            claimed = await claim_local_run(
                db,
                job=job,
                academy_id=academy_id,
                local_date=local_now.date(),
                now=instant,
                worker_id=worker_id,
            )
            if not claimed:
                summary.already_claimed.append(academy_id)
                continue
            local_date = local_now.date()
            with tenant_scope(academy_id):
                await run(academy_id, local_now)
        except BaseException as exc:
            if local_date is not None:
                await _finish_local_run(
                    db,
                    job=job,
                    academy_id=academy_id,
                    local_date=local_date,
                    status=STATUS_FAILED,
                    error=repr(exc),
                )
            if not isinstance(exc, Exception):
                # Cancellation (a deploy) or interpreter exit: the marker is
                # already ``failed`` so a later tick today retries; stop here.
                raise
            summary.failed.append(academy_id)
            log.exception(
                "scheduled_job_academy_failed job=%s academy=%s",
                job,
                academy_id,
                extra={"job_id": job, "academy_id": academy_id},
            )
            capture_exception(exc)
            continue
        await _finish_local_run(
            db, job=job, academy_id=academy_id, local_date=local_date, status=STATUS_DONE
        )
        summary.ran.append(academy_id)
    return summary


async def seed_markers_from_legacy_heartbeats(
    db: Any,
    *,
    schedules: dict[str, LocalDailyTime],
    academy_ids: Iterable[str],
    zone_for: Callable[[str], Awaitable[str]],
    now: datetime,
    heartbeats_collection: str = "ops_job_runs",
) -> int:
    """Mark today as done where the old fixed-hour cron already ran today.

    Runs at boot, and only for a job that has no marker at all yet (the first
    boot of this code). Without it, deploying after, say, 07:30 would send a
    second owner brief that same day: the old cron ran at 07:30 and left no
    marker, so the new tick would see the target passed and nothing claimed.
    When the old job's heartbeat (``ops_job_runs.last_tick_at``, written after
    the body) falls on the academy's local today at or after the target, the
    old cron already covered today. Best effort; returns markers seeded.
    """
    seeded = 0
    instant = _as_aware_utc(now)
    ids = list(academy_ids)
    for job, at in schedules.items():
        try:
            if await db[MARKERS_COLLECTION].find_one({"job": job, "academy_id": {"$in": ids}}):
                continue
            heartbeat = await db[heartbeats_collection].find_one({"_id": job})
            last_tick = (heartbeat or {}).get("last_tick_at")
            if not isinstance(last_tick, datetime):
                continue
            for academy_id in ids:
                zone = ZoneInfo(await zone_for(academy_id))
                local_now = instant.astimezone(zone)
                local_tick = _as_aware_utc(last_tick).astimezone(zone)
                if local_tick.date() != local_now.date() or not at.reached_by(local_tick):
                    continue
                local_date = local_now.date()
                await db[MARKERS_COLLECTION].update_one(
                    {"_id": marker_id(job, academy_id, local_date), "academy_id": academy_id},
                    {
                        "$setOnInsert": {
                            "job": job,
                            "academy_id": academy_id,
                            "local_date": local_date.isoformat(),
                            "status": STATUS_DONE,
                            "attempts": 0,
                            "seeded_from_heartbeat": True,
                            "created_at": instant,
                        }
                    },
                    upsert=True,
                )
                seeded += 1
        except Exception:
            log.warning("scheduler_run_marker_seed_failed job=%s", job, exc_info=True)
    return seeded
