"""Settings Phase 4: the fixed-hour daily jobs run on each academy's clock.

The jobs used to be APScheduler crons in ``settings.scheduler_tz`` (Chicago in
production). They now tick hourly in UTC and run once per academy-local date
when the academy's wall clock reaches the target (``local_clock.py``). These
tests replay whole days of hourly ticks through the real runner against
mongomock and pin:

* BLNO does not move: an academy on the production scheduler zone, and one with
  no timezone (``LEGACY_FALLBACK_TIMEZONE``), fire every job at exactly the
  wall-clock time APScheduler fired it before, on ordinary, spring-forward and
  fall-back days, exactly once per local date.
* Another academy fires at its own local time.
* One academy failing never blocks another, and a failed run retries later the
  same local day, bounded.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import mongomock_motor
import pytest
from apscheduler.triggers.cron import CronTrigger

from backend.v2.main import LOCAL_DAILY_JOBS, SCHEDULED_JOB_MONITORS
from backend.v2.shared.scheduling import local_clock
from backend.v2.shared.scheduling.local_clock import (
    MARKERS_COLLECTION,
    MAX_ATTEMPTS,
    LocalDailyTime,
    claim_local_run,
    run_daily_at_local_time,
    seed_markers_from_legacy_heartbeats,
)
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.time.academy_timezone import (
    LEGACY_FALLBACK_TIMEZONE,
    resolve_academy_clock_timezone,
)

BLNO_ZONE = LEGACY_FALLBACK_TIMEZONE  # BLNO's academies.timezone in production
PROD_SCHEDULER_TZ = LEGACY_FALLBACK_TIMEZONE  # fly.toml SCHEDULER_TZ

#: The old ``scheduler.add_job(..., "cron", hour=H, minute=M)`` times.
OLD_CRON_TIMES = {
    "process_scheduled_resume_actions": (2, 0),
    "expire_makeup_requests": (2, 30),
    "expire_due_holds": (2, 45),
    "generate_monthly_invoices": (3, 0),
    "send_hold_reminders": (4, 0),
    "send_win_back_notices": (4, 30),
    "create_trial_follow_ups": (4, 50),
    "send_owner_daily_brief": (7, 30),
    # Hourly cron at :20 whose body only worked in the academy-local 9 o'clock.
    "send_past_due_reminders": (9, 20),
}

ORDINARY_DAY = date(2026, 9, 29)
SPRING_FORWARD = date(2026, 3, 8)  # US: 02:00 -> 03:00
FALL_BACK = date(2026, 11, 1)  # US: 02:00 -> 01:00

ACADEMY_ZONES = {
    "acad_blno_badminton": BLNO_ZONE,
    "no_zone": None,
    "kolkata": "Asia/Kolkata",
    "la": "America/Los_Angeles",
}


def _db():
    return mongomock_motor.AsyncMongoMockClient()["test"]


async def _zone_for(academy_id: str) -> str:
    async def reader(aid: str) -> str | None:
        return ACADEMY_ZONES[aid]

    return await resolve_academy_clock_timezone(reader, academy_id)


def _hourly_ticks(minute: int, start: datetime, end: datetime) -> list[datetime]:
    """The UTC instants an hourly ``minute=M`` UTC cron fires in [start, end)."""
    tick = start.replace(minute=minute, second=0, microsecond=0)
    if tick < start:
        tick += timedelta(hours=1)
    ticks = []
    while tick < end:
        ticks.append(tick)
        tick += timedelta(hours=1)
    return ticks


async def _replay(
    job: str,
    academy_ids: list[str],
    around: date,
    *,
    db=None,
    run=None,
) -> dict[str, list[datetime]]:
    """Replay two days of hourly ticks; return each academy's local run times."""
    db = db if db is not None else _db()
    at = LOCAL_DAILY_JOBS[job]
    fired: dict[str, list[datetime]] = {academy_id: [] for academy_id in academy_ids}

    async def record(academy_id: str, local_now: datetime) -> None:
        assert current_academy_id() == academy_id  # runs inside tenant_scope
        fired[academy_id].append(local_now)
        if run is not None:
            await run(academy_id, local_now)

    start = datetime(around.year, around.month, around.day, tzinfo=UTC) - timedelta(days=1)
    for tick in _hourly_ticks(at.minute, start, start + timedelta(days=3)):
        await run_daily_at_local_time(
            db=db,
            job=job,
            at=at,
            academy_ids=academy_ids,
            zone_for=_zone_for,
            run=record,
            now=tick,
            worker_id="test",
        )
    return fired


def _old_fire_times(job: str, zone: str, on: date) -> list[datetime]:
    """When the old scheduler-zone job fired on local date ``on``."""
    hour, minute = OLD_CRON_TIMES[job]
    tz = ZoneInfo(zone)
    if job == "send_past_due_reminders":
        # An hourly cron at :20 whose body worked only when the academy-local
        # hour was 9 (``local_now.hour != 9: continue``).
        day_start = datetime(on.year, on.month, on.day, tzinfo=tz).astimezone(UTC)
        ticks = _hourly_ticks(
            minute, day_start - timedelta(hours=2), day_start + timedelta(hours=27)
        )
        return [
            t.astimezone(tz)
            for t in ticks
            if t.astimezone(tz).date() == on and t.astimezone(tz).hour == hour
        ]
    trigger = CronTrigger(hour=hour, minute=minute, timezone=tz)
    start = datetime(on.year, on.month, on.day, tzinfo=tz) - timedelta(hours=1)
    fires: list[datetime] = []
    previous = None
    now = start
    for _ in range(5):
        nxt = trigger.get_next_fire_time(previous, now)
        if nxt is None or nxt.astimezone(tz).date() > on:
            break
        if nxt.astimezone(tz).date() == on:
            fires.append(nxt.astimezone(tz))
        previous = nxt
        now = nxt + timedelta(seconds=1)
    return fires


def _on(fires: list[datetime], day: date) -> list[datetime]:
    return [f for f in fires if f.date() == day]


def _wall(fires: list[datetime]) -> list[tuple[int, int]]:
    return [(f.hour, f.minute) for f in fires]


def test_the_local_daily_jobs_keep_their_old_wall_clock_times() -> None:
    assert {job: (t.hour, t.minute) for job, t in LOCAL_DAILY_JOBS.items()} == OLD_CRON_TIMES


def test_every_local_daily_job_ticks_hourly_at_its_own_minute() -> None:
    """The Sentry monitor must expect a check-in every hour (every tick checks
    in), or the new cadence reads as missed/extra check-ins."""
    for job, at in LOCAL_DAILY_JOBS.items():
        schedule = SCHEDULED_JOB_MONITORS[job]["schedule"]
        assert schedule == {"type": "crontab", "value": f"{at.minute} * * * *"}, job


@pytest.mark.parametrize("day", [ORDINARY_DAY, FALL_BACK], ids=["ordinary", "fall-back"])
@pytest.mark.parametrize("job", sorted(OLD_CRON_TIMES))
async def test_blno_and_zoneless_academies_fire_exactly_when_the_old_cron_did(
    job: str, day: date
) -> None:
    fired = await _replay(job, ["acad_blno_badminton", "no_zone"], day)
    old = _wall(_old_fire_times(job, PROD_SCHEDULER_TZ, day))

    assert len(old) == 1
    for academy_id in ("acad_blno_badminton", "no_zone"):
        runs = _on(fired[academy_id], day)
        assert _wall(runs) == old, (academy_id, job)
        # Same instant, not only the same wall clock (fall-back repeats 01:xx).
        assert [r.astimezone(UTC) for r in runs] == [
            o.astimezone(UTC) for o in _old_fire_times(job, PROD_SCHEDULER_TZ, day)
        ]


@pytest.mark.parametrize("job", sorted(OLD_CRON_TIMES))
async def test_spring_forward_day_runs_once_at_the_first_tick_past_the_target(job: str) -> None:
    """02:00-02:59 does not exist on 2026-03-08 in Chicago. A 02:xx job runs
    at 03:xx that day, once; every other job keeps its exact time."""
    fired = await _replay(job, ["acad_blno_badminton", "no_zone"], SPRING_FORWARD)
    hour, minute = OLD_CRON_TIMES[job]
    expected = (3, minute) if hour == 2 else (hour, minute)

    old = [o.astimezone(UTC) for o in _old_fire_times(job, PROD_SCHEDULER_TZ, SPRING_FORWARD)]
    for academy_id in ("acad_blno_badminton", "no_zone"):
        runs = _on(fired[academy_id], SPRING_FORWARD)
        assert _wall(runs) == [expected], academy_id
        # APScheduler fired a nonexistent 02:xx at the same instant (02:xx
        # standard time == 03:xx daylight time), so BLNO does not move at all.
        assert [r.astimezone(UTC) for r in runs] == old, academy_id


@pytest.mark.parametrize("day", [ORDINARY_DAY, SPRING_FORWARD, FALL_BACK])
@pytest.mark.parametrize("job", sorted(OLD_CRON_TIMES))
async def test_every_academy_runs_exactly_once_per_local_date(job: str, day: date) -> None:
    fired = await _replay(job, list(ACADEMY_ZONES), day)

    for academy_id, fires in fired.items():
        per_date: dict[date, int] = {}
        for local in fires:
            per_date[local.date()] = per_date.get(local.date(), 0) + 1
        assert all(count == 1 for count in per_date.values()), (academy_id, per_date)
        assert per_date.get(day) == 1, academy_id


async def test_a_second_academy_fires_on_its_own_clock() -> None:
    fired = await _replay("generate_monthly_invoices", list(ACADEMY_ZONES), ORDINARY_DAY)

    assert _wall(_on(fired["la"], ORDINARY_DAY)) == [(3, 0)]
    # Kolkata is UTC+5:30: the :00 UTC tick is :30 local, so the first tick at
    # or past 03:00 local is 03:30.
    assert _wall(_on(fired["kolkata"], ORDINARY_DAY)) == [(3, 30)]
    # Different instants from BLNO's 03:00 Chicago.
    blno = _on(fired["acad_blno_badminton"], ORDINARY_DAY)[0].astimezone(UTC)
    assert _on(fired["la"], ORDINARY_DAY)[0].astimezone(UTC) == blno + timedelta(hours=2)


async def test_billing_day_is_read_on_the_academy_local_date() -> None:
    """At 03:00 Kolkata on the 1st it is still the 31st in Chicago: the job is
    handed Kolkata's local now, so billing_day=1 is already due there."""
    seen: dict[str, datetime] = {}

    async def run(academy_id: str, local_now: datetime) -> None:
        seen.setdefault(academy_id, local_now)

    await run_daily_at_local_time(
        db=_db(),
        job="generate_monthly_invoices",
        at=LOCAL_DAILY_JOBS["generate_monthly_invoices"],
        academy_ids=["kolkata", "acad_blno_badminton"],
        zone_for=_zone_for,
        run=run,
        now=datetime(2026, 9, 30, 22, 0, tzinfo=UTC),  # 03:30 Oct 1 IST, 17:00 Sep 30 CDT
        worker_id="test",
    )

    assert seen["kolkata"].date() == date(2026, 10, 1)
    assert seen["kolkata"].strftime("%Y-%m") == "2026-10"
    assert "acad_blno_badminton" in seen  # 17:00 Chicago, past 03:00 on Sep 30


async def test_one_academys_failure_does_not_block_another_and_retries_that_day() -> None:
    db = _db()
    calls: dict[str, int] = {"acad_blno_badminton": 0, "la": 0}

    async def run(academy_id: str, _local_now: datetime) -> None:
        calls[academy_id] += 1
        if academy_id == "acad_blno_badminton":
            raise RuntimeError("mongo blip")

    fired = await _replay(
        "expire_due_holds", ["acad_blno_badminton", "la"], ORDINARY_DAY, db=db, run=run
    )

    # LA ran once per local date despite BLNO raising on every attempt.
    assert len(_on(fired["la"], ORDINARY_DAY)) == 1
    # BLNO retried on later ticks of the same local day, bounded.
    assert len(_on(fired["acad_blno_badminton"], ORDINARY_DAY)) == MAX_ATTEMPTS
    marker = await db[MARKERS_COLLECTION].find_one(
        {"_id": f"expire_due_holds:acad_blno_badminton:{ORDINARY_DAY.isoformat()}"}
    )
    assert marker["status"] == "failed"
    assert marker["attempts"] == MAX_ATTEMPTS
    assert "mongo blip" in marker["last_error"]


async def test_a_failed_run_that_later_succeeds_is_done_and_not_repeated() -> None:
    db = _db()
    attempts = {"n": 0}

    async def run(_academy_id: str, local_now: datetime) -> None:
        if local_now.date() != ORDINARY_DAY:
            return
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("first try fails")

    fired = await _replay(
        "send_hold_reminders", ["acad_blno_badminton"], ORDINARY_DAY, db=db, run=run
    )

    assert _wall(_on(fired["acad_blno_badminton"], ORDINARY_DAY)) == [(4, 0), (5, 0)]
    marker = await db[MARKERS_COLLECTION].find_one(
        {"_id": f"send_hold_reminders:acad_blno_badminton:{ORDINARY_DAY.isoformat()}"}
    )
    assert marker["status"] == "done"


async def test_a_missed_tick_catches_up_later_the_same_local_day() -> None:
    """A deploy spanning 03:00 no longer loses the day: the 05:00 tick runs it."""
    fired: list[datetime] = []

    async def run(_academy_id: str, local_now: datetime) -> None:
        fired.append(local_now)

    zone = ZoneInfo(BLNO_ZONE)
    db = _db()
    for local_hour in (2, 5, 6):  # the 03:00 and 04:00 ticks never happened
        await run_daily_at_local_time(
            db=db,
            job="generate_monthly_invoices",
            at=LOCAL_DAILY_JOBS["generate_monthly_invoices"],
            academy_ids=["acad_blno_badminton"],
            zone_for=_zone_for,
            run=run,
            now=datetime(2026, 9, 29, local_hour, 0, tzinfo=zone),
            worker_id="test",
        )

    assert _wall(fired) == [(5, 0)]


async def test_two_machines_on_the_same_tick_run_once_without_the_0210_index() -> None:
    """The claim rests on the marker ``_id``, not on migration 0210 having run
    (the 2026-09-02 lesson: prod had never built the digest claim indexes)."""
    db = _db()
    runs: list[str] = []

    async def run(academy_id: str, _local_now: datetime) -> None:
        await asyncio.sleep(0)
        runs.append(academy_id)

    tick = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)  # 03:00 Chicago
    await asyncio.gather(
        *(
            run_daily_at_local_time(
                db=db,
                job="generate_monthly_invoices",
                at=LOCAL_DAILY_JOBS["generate_monthly_invoices"],
                academy_ids=["acad_blno_badminton"],
                zone_for=_zone_for,
                run=run,
                now=tick,
                worker_id=worker,
            )
            for worker in ("machine-a", "machine-b")
        )
    )

    assert runs == ["acad_blno_badminton"]


async def test_a_run_stuck_running_is_reclaimable_only_after_the_stale_window() -> None:
    db = _db()
    claimed_at = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
    kwargs = {"job": "j", "academy_id": "a", "local_date": ORDINARY_DAY, "worker_id": "w"}

    assert await claim_local_run(db, now=claimed_at, **kwargs)
    assert not await claim_local_run(db, now=claimed_at + timedelta(hours=1), **kwargs)
    stale = claimed_at + local_clock.STALE_RUNNING_AFTER + timedelta(minutes=1)
    assert await claim_local_run(db, now=stale, **kwargs)


async def test_cancellation_marks_the_run_failed_and_propagates() -> None:
    db = _db()

    async def run(_academy_id: str, _local_now: datetime) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_daily_at_local_time(
            db=db,
            job="expire_due_holds",
            at=LocalDailyTime(2, 45),
            academy_ids=["acad_blno_badminton"],
            zone_for=_zone_for,
            run=run,
            now=datetime(2026, 9, 29, 7, 45, tzinfo=UTC),
            worker_id="test",
        )
    marker = await db[MARKERS_COLLECTION].find_one({})
    assert marker["status"] == "failed"


async def test_a_zone_lookup_failure_is_isolated_to_that_academy() -> None:
    ran: list[str] = []

    async def zone_for(academy_id: str) -> str:
        if academy_id == "broken":
            raise RuntimeError("lookup failed")
        return BLNO_ZONE

    async def run(academy_id: str, _local_now: datetime) -> None:
        ran.append(academy_id)

    summary = await run_daily_at_local_time(
        db=_db(),
        job="send_win_back_notices",
        at=LocalDailyTime(4, 30),
        academy_ids=["broken", "acad_blno_badminton"],
        zone_for=zone_for,
        run=run,
        now=datetime(2026, 9, 29, 9, 30, tzinfo=UTC),
        worker_id="test",
    )

    assert ran == ["acad_blno_badminton"]
    assert summary.failed == ["broken"]


# --- first boot: do not repeat what the old cron already did today ---------


async def test_first_boot_after_the_old_cron_ran_today_does_not_run_it_again() -> None:
    db = _db()
    zone = ZoneInfo(BLNO_ZONE)
    # The old 07:30 owner-brief cron ran this morning; we deploy at 10:05.
    await db["ops_job_runs"].insert_one(
        {
            "_id": "send_owner_daily_brief",
            "last_tick_at": datetime(2026, 9, 29, 7, 30, 4, tzinfo=zone),
        }
    )
    boot = datetime(2026, 9, 29, 10, 5, tzinfo=zone)
    seeded = await seed_markers_from_legacy_heartbeats(
        db,
        schedules={"send_owner_daily_brief": LOCAL_DAILY_JOBS["send_owner_daily_brief"]},
        academy_ids=["acad_blno_badminton"],
        zone_for=_zone_for,
        now=boot,
    )
    ran: list[str] = []

    async def run(academy_id: str, _local_now: datetime) -> None:
        ran.append(academy_id)

    await run_daily_at_local_time(
        db=db,
        job="send_owner_daily_brief",
        at=LOCAL_DAILY_JOBS["send_owner_daily_brief"],
        academy_ids=["acad_blno_badminton"],
        zone_for=_zone_for,
        run=run,
        now=boot + timedelta(minutes=25),
        worker_id="test",
    )

    assert seeded == 1
    assert ran == []


async def test_first_boot_before_todays_old_run_still_runs_today() -> None:
    db = _db()
    zone = ZoneInfo(BLNO_ZONE)
    await db["ops_job_runs"].insert_one(
        {"_id": "send_owner_daily_brief", "last_tick_at": datetime(2026, 9, 28, 7, 30, tzinfo=zone)}
    )
    seeded = await seed_markers_from_legacy_heartbeats(
        db,
        schedules={"send_owner_daily_brief": LOCAL_DAILY_JOBS["send_owner_daily_brief"]},
        academy_ids=["acad_blno_badminton"],
        zone_for=_zone_for,
        now=datetime(2026, 9, 29, 6, 0, tzinfo=zone),
    )

    assert seeded == 0
    assert await db[MARKERS_COLLECTION].count_documents({}) == 0


async def test_seeding_is_skipped_once_the_job_has_markers() -> None:
    """Later boots must not read an hourly heartbeat as 'already ran today'."""
    db = _db()
    zone = ZoneInfo(BLNO_ZONE)
    await db[MARKERS_COLLECTION].insert_one(
        {"_id": "x", "job": "send_hold_reminders", "academy_id": "la", "local_date": "2026-09-28"}
    )
    await db["ops_job_runs"].insert_one(
        {"_id": "send_hold_reminders", "last_tick_at": datetime(2026, 9, 29, 9, 0, tzinfo=zone)}
    )

    seeded = await seed_markers_from_legacy_heartbeats(
        db,
        schedules={"send_hold_reminders": LOCAL_DAILY_JOBS["send_hold_reminders"]},
        academy_ids=["acad_blno_badminton", "la"],
        zone_for=_zone_for,
        now=datetime(2026, 9, 29, 10, 0, tzinfo=zone),
    )

    assert seeded == 0
