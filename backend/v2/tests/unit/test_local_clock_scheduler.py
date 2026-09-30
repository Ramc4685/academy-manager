"""Settings Phase 4: the fixed-hour daily jobs run on each academy's clock.

The jobs used to be APScheduler crons in ``settings.scheduler_tz`` (Chicago in
production). They now tick hourly in UTC and run once per academy-local date
when the academy's wall clock reaches the target (``local_clock.py``). These
tests replay whole days of hourly ticks through the real runner against
mongomock and pin:

* BLNO does not move: an academy on the production scheduler zone, and one with
  no timezone (``LEGACY_FALLBACK_TIMEZONE``), fire every job at exactly the
  wall-clock time APScheduler fired it before, on ordinary, spring-forward and
  fall-back days, exactly once per local date. The one intended exception is
  the past-due sweep for a ZONELESS academy: the old code read its day in UTC
  (``resolve_reporting_timezone``), the spec allows only the legacy fallback,
  so it moves from 09:20 UTC to 09:20 Chicago (pinned separately below).
* Another academy fires at its own local time.
* One academy failing never blocks another, and a failed run retries later the
  same local day, bounded.
"""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import mongomock_motor
import pytest
from apscheduler.triggers.cron import CronTrigger

from backend.v2 import main as main_module
from backend.v2.main import (
    LEGACY_HOURLY_LOCAL_JOBS,
    LOCAL_DAILY_JOB_MAX_ATTEMPTS,
    LOCAL_DAILY_JOBS,
    SCHEDULED_JOB_MONITORS,
    run_local_daily_job,
)
from backend.v2.shared.observability.ops_digest import (
    accumulate_job_run,
    ops_digest_cycle,
    seed_job_heartbeats,
)
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

#: The zone the OLD code used for each academy. Every fixed-hour cron ran in
#: the scheduler zone; the old past-due sweep instead used
#: ``resolve_reporting_timezone``, whose zoneless fallback was UTC.
OLD_UTC_FALLBACK = "UTC"


def _old_zone(job: str, academy_id: str) -> str:
    if job == "send_past_due_reminders" and ACADEMY_ZONES[academy_id] is None:
        return OLD_UTC_FALLBACK
    return PROD_SCHEDULER_TZ


#: (job, academy) pairs whose time the spec deliberately moves.
INTENDED_MOVES = {("send_past_due_reminders", "no_zone")}

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

    for academy_id in ("acad_blno_badminton", "no_zone"):
        if (job, academy_id) in INTENDED_MOVES:
            continue
        old = _old_fire_times(job, _old_zone(job, academy_id), day)
        assert len(old) == 1
        runs = _on(fired[academy_id], day)
        assert _wall(runs) == _wall(old), (academy_id, job)
        # Same instant, not only the same wall clock (fall-back repeats 01:xx).
        assert [r.astimezone(UTC) for r in runs] == [o.astimezone(UTC) for o in old]


@pytest.mark.parametrize("day", [ORDINARY_DAY, SPRING_FORWARD, FALL_BACK])
async def test_zoneless_past_due_sweep_moves_from_utc_to_the_legacy_fallback(day: date) -> None:
    """The one intended move. The old sweep read a zoneless academy's day in
    UTC, so its reminders went out at 09:20 UTC. The spec permits only
    LEGACY_FALLBACK_TIMEZONE, so they now go out at 09:20 Chicago. BLNO is
    unaffected: its academies.timezone is set (America/Chicago)."""
    job = "send_past_due_reminders"
    fired = await _replay(job, ["no_zone"], day)

    old = _old_fire_times(job, OLD_UTC_FALLBACK, day)
    assert _wall(old) == [(9, 20)]  # 09:20 UTC before
    runs = _on(fired["no_zone"], day)
    assert _wall(runs) == [(9, 20)]
    assert runs[0].tzinfo == ZoneInfo(LEGACY_FALLBACK_TIMEZONE)  # 09:20 Chicago now
    assert runs[0].astimezone(UTC) != old[0].astimezone(UTC)


@pytest.mark.parametrize("job", sorted(OLD_CRON_TIMES))
async def test_spring_forward_day_runs_once_at_the_first_tick_past_the_target(job: str) -> None:
    """02:00-02:59 does not exist on 2026-03-08 in Chicago. A 02:xx job runs
    at 03:xx that day, once; every other job keeps its exact time."""
    fired = await _replay(job, ["acad_blno_badminton", "no_zone"], SPRING_FORWARD)
    hour, minute = OLD_CRON_TIMES[job]
    expected = (3, minute) if hour == 2 else (hour, minute)

    for academy_id in ("acad_blno_badminton", "no_zone"):
        if (job, academy_id) in INTENDED_MOVES:
            continue
        old = [
            o.astimezone(UTC)
            for o in _old_fire_times(job, _old_zone(job, academy_id), SPRING_FORWARD)
        ]
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


async def test_cutover_old_chicago_run_covers_an_academy_on_another_clock() -> None:
    """The old cron briefed every academy at 07:30 Chicago, which is 05:30 in
    Los Angeles: before LA's new 07:30 target, but still LA's today. It must
    count as covered, or LA gets a second owner brief on deploy day."""
    db = _db()
    chicago = ZoneInfo(BLNO_ZONE)
    await db["ops_job_runs"].insert_one(
        {
            "_id": "send_owner_daily_brief",
            "last_tick_at": datetime(2026, 9, 29, 7, 30, 4, tzinfo=chicago),
        }
    )

    seeded = await seed_markers_from_legacy_heartbeats(
        db,
        schedules={"send_owner_daily_brief": LOCAL_DAILY_JOBS["send_owner_daily_brief"]},
        academy_ids=["la"],
        zone_for=_zone_for,
        now=datetime(2026, 9, 29, 9, 0, tzinfo=chicago),
        legacy_hourly_jobs=LEGACY_HOURLY_LOCAL_JOBS,
    )

    assert seeded == 1


async def test_cutover_old_hourly_past_due_tick_before_target_is_not_a_run() -> None:
    """The old past-due sweep ticked hourly, so a heartbeat before the local
    target only shows the old code was alive; today still runs."""
    db = _db()
    chicago = ZoneInfo(BLNO_ZONE)
    await db["ops_job_runs"].insert_one(
        {
            "_id": "send_past_due_reminders",
            "last_tick_at": datetime(2026, 9, 29, 8, 20, tzinfo=chicago),
        }
    )

    seeded = await seed_markers_from_legacy_heartbeats(
        db,
        schedules={"send_past_due_reminders": LOCAL_DAILY_JOBS["send_past_due_reminders"]},
        academy_ids=["acad_blno_badminton"],
        zone_for=_zone_for,
        now=datetime(2026, 9, 29, 8, 50, tzinfo=chicago),
        legacy_hourly_jobs=LEGACY_HOURLY_LOCAL_JOBS,
    )

    assert seeded == 0


async def test_seeding_ignores_this_codes_own_heartbeats() -> None:
    """Every heartbeat the academy-clock scheduler writes (each tick, and the
    boot stamp) is marked ``local_clock_tick_at``; only an unmarked one is the
    old cron's. So an hourly tick past the target never reads as 'ran today'."""
    db = _db()
    zone = ZoneInfo(BLNO_ZONE)
    tick = datetime(2026, 9, 29, 9, 0, tzinfo=zone)
    await db["ops_job_runs"].insert_one(
        {"_id": "send_hold_reminders", "last_tick_at": tick, "local_clock_tick_at": tick}
    )

    seeded = await seed_markers_from_legacy_heartbeats(
        db,
        schedules={"send_hold_reminders": LOCAL_DAILY_JOBS["send_hold_reminders"]},
        academy_ids=["acad_blno_badminton", "la"],
        zone_for=_zone_for,
        now=datetime(2026, 9, 29, 10, 0, tzinfo=zone),
    )

    assert seeded == 0


async def test_boot_heartbeat_stamp_is_never_read_as_an_old_cron_run() -> None:
    db = _db()
    zone = ZoneInfo(BLNO_ZONE)
    boot = datetime(2026, 9, 29, 10, 5, tzinfo=zone)
    await seed_job_heartbeats(db, now=boot)

    seeded = await seed_markers_from_legacy_heartbeats(
        db,
        schedules=LOCAL_DAILY_JOBS,
        academy_ids=["acad_blno_badminton"],
        zone_for=_zone_for,
        now=boot + timedelta(minutes=25),
    )

    assert seeded == 0


async def test_rolling_deploy_old_machine_runs_after_new_boot_is_not_repeated() -> None:
    """A Fly rolling deploy: the new machine boots at 07:25 (nothing to seed),
    the old machine still takes the shared lease at 07:30 and sends the brief,
    then the new machine's 08:30 tick must not send it again."""
    db = _db()
    zone = ZoneInfo(BLNO_ZONE)
    job = "send_owner_daily_brief"
    # The new machine's earlier ticks stamped their heartbeats.
    earlier = datetime(2026, 9, 29, 6, 30, tzinfo=zone)
    await db["ops_job_runs"].insert_one(
        {"_id": job, "last_tick_at": earlier, "local_clock_tick_at": earlier}
    )
    boot_seeded = await seed_markers_from_legacy_heartbeats(
        db,
        schedules={job: LOCAL_DAILY_JOBS[job]},
        academy_ids=["acad_blno_badminton"],
        zone_for=_zone_for,
        now=datetime(2026, 9, 29, 7, 25, tzinfo=zone),
    )
    # The old code's heartbeat write: last_tick_at only.
    await db["ops_job_runs"].update_one(
        {"_id": job}, {"$set": {"last_tick_at": datetime(2026, 9, 29, 7, 30, 6, tzinfo=zone)}}
    )
    ran: list[str] = []

    async def run(academy_id: str, _local_now: datetime) -> None:
        ran.append(academy_id)

    summary = await run_local_daily_job(
        db,
        job,
        academy_ids=["acad_blno_badminton"],
        zone_for=_zone_for,
        run=run,
        now=datetime(2026, 9, 29, 8, 30, tzinfo=zone),
        worker_id="new-machine",
    )

    assert boot_seeded == 0
    assert ran == []
    assert summary.already_claimed == ["acad_blno_badminton"]


async def test_rolling_deploy_new_tick_runs_when_the_old_cron_did_not_run_today() -> None:
    db = _db()
    zone = ZoneInfo(BLNO_ZONE)
    job = "send_owner_daily_brief"
    await db["ops_job_runs"].insert_one(
        {"_id": job, "last_tick_at": datetime(2026, 9, 28, 7, 30, 6, tzinfo=zone)}
    )
    ran: list[str] = []

    async def run(academy_id: str, _local_now: datetime) -> None:
        ran.append(academy_id)

    await run_local_daily_job(
        db,
        job,
        academy_ids=["acad_blno_badminton"],
        zone_for=_zone_for,
        run=run,
        now=datetime(2026, 9, 29, 7, 30, tzinfo=zone),
        worker_id="new-machine",
    )

    assert ran == ["acad_blno_badminton"]


# --- owner brief: never re-sent after a failed or cancelled run -------------


@pytest.mark.parametrize("error", [RuntimeError("smtp"), asyncio.CancelledError()])
async def test_owner_brief_is_not_retried_the_same_day_after_a_failure(
    error: BaseException,
) -> None:
    """send_owner_daily_briefs records no per-recipient send: a deploy that
    cancels it after the first owner was mailed must not mail them again."""
    db = _db()
    zone = ZoneInfo(BLNO_ZONE)
    job = "send_owner_daily_brief"
    calls: list[datetime] = []

    async def run(_academy_id: str, local_now: datetime) -> None:
        calls.append(local_now)
        if len(calls) == 1:
            raise error

    for local_hour in range(7, 24):
        try:
            await run_local_daily_job(
                db,
                job,
                academy_ids=["acad_blno_badminton"],
                zone_for=_zone_for,
                run=run,
                now=datetime(2026, 9, 29, local_hour, 30, tzinfo=zone),
                worker_id="test",
            )
        except asyncio.CancelledError:
            pass

    assert _wall(calls) == [(7, 30)]
    assert LOCAL_DAILY_JOB_MAX_ATTEMPTS[job] == 1


async def test_owner_brief_stuck_running_is_never_reclaimed() -> None:
    db = _db()
    kwargs = {"job": "send_owner_daily_brief", "academy_id": "a", "local_date": ORDINARY_DAY}
    claimed_at = datetime(2026, 9, 29, 12, 30, tzinfo=UTC)

    assert await claim_local_run(db, now=claimed_at, worker_id="w", max_attempts=1, **kwargs)
    later = claimed_at + local_clock.STALE_RUNNING_AFTER + timedelta(hours=1)
    assert not await claim_local_run(db, now=later, worker_id="w", max_attempts=1, **kwargs)


# --- ops digest: a day's per-academy invoice ticks add up -------------------


async def test_invoice_ops_record_sums_the_cycle_instead_of_keeping_the_last_tick() -> None:
    db = _db()
    zone = ZoneInfo(PROD_SCHEDULER_TZ)
    # BLNO generates at 03:00 CDT; an LA academy's 03:00 PDT tick only emails.
    blno_cycle = ops_digest_cycle(datetime(2026, 9, 29, 3, 0, tzinfo=zone))
    la_cycle = ops_digest_cycle(datetime(2026, 9, 29, 5, 0, tzinfo=zone))
    assert blno_cycle == la_cycle == "2026-09-29"
    await accumulate_job_run(
        db,
        "generate_monthly_invoices",
        {"academy_count": 1, "created_count": 120, "invoices_emailed": 118},
        cycle=blno_cycle,
        period="2026-10",
    )
    await accumulate_job_run(
        db,
        "generate_monthly_invoices",
        {"academy_count": 0, "created_count": 0, "invoices_emailed": 1},
        cycle=la_cycle,
        period="2026-09",
    )

    doc = await db["ops_job_runs"].find_one({"_id": "generate_monthly_invoices"})
    assert doc["totals"] == {
        "academy_count": 1,
        "created_count": 120,
        "invoices_emailed": 119,
        "period": "2026-10",
    }

    # After the 07:00 digest, the next cycle starts afresh.
    next_cycle = ops_digest_cycle(datetime(2026, 9, 29, 7, 0, tzinfo=zone))
    assert next_cycle == "2026-09-30"
    await accumulate_job_run(
        db,
        "generate_monthly_invoices",
        {"academy_count": 0, "created_count": 0, "invoices_emailed": 2},
        cycle=next_cycle,
    )
    doc = await db["ops_job_runs"].find_one({"_id": "generate_monthly_invoices"})
    assert doc["totals"] == {"academy_count": 0, "created_count": 0, "invoices_emailed": 2}


# --- main.py wiring: registration and bodies match LOCAL_DAILY_JOBS ---------


def _lifespan_ast() -> ast.AsyncFunctionDef:
    tree = ast.parse(Path(main_module.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_lifespan":
            return node
    raise AssertionError("_lifespan not found")


def _kw(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def test_each_local_daily_job_is_registered_hourly_in_utc_at_its_minute() -> None:
    registered: dict[str, ast.Call] = {}
    for node in ast.walk(_lifespan_ast()):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_job"
        ):
            job_id = _kw(node, "id")
            if isinstance(job_id, ast.Constant):
                registered[job_id.value] = node

    for job in LOCAL_DAILY_JOBS:
        call = registered[job]
        hour = _kw(call, "hour")  # no hour= is every hour
        assert hour is None or ast.unparse(hour) == "'*'", job
        assert ast.unparse(_kw(call, "minute")) == f"LOCAL_DAILY_JOBS['{job}'].minute", job
        assert ast.unparse(_kw(call, "timezone")) == "UTC", job


def test_each_local_daily_job_body_runs_through_the_academy_clock_runner() -> None:
    """Every job body hands its own job id to _run_local_daily, and the invoice
    body passes the ACADEMY-LOCAL now into _run_monthly_invoice_generation."""
    bodies = {
        node.name: node
        for node in ast.walk(_lifespan_ast())
        if isinstance(node, ast.AsyncFunctionDef) and node.name.endswith("_body")
    }
    runner_jobs: dict[str, str] = {}
    for name, body in bodies.items():
        for node in ast.walk(body):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_run_local_daily"
            ):
                arg = node.args[0]
                assert isinstance(arg, ast.Constant)
                runner_jobs[arg.value] = name
    assert set(runner_jobs) == set(LOCAL_DAILY_JOBS)

    invoice_body = bodies[runner_jobs["generate_monthly_invoices"]]
    calls = [
        node
        for node in ast.walk(invoice_body)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_run_monthly_invoice_generation"
    ]
    assert len(calls) == 1
    assert ast.unparse(_kw(calls[0], "now")) == "local_now"
