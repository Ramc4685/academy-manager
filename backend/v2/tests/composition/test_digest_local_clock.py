"""Settings Phase 4: coach and parent digests send on each academy's clock.

``digest_due_date`` decides, per academy per hourly tick, whether the digest
window is open and which ``digest_date`` to claim (the date the CRM Messages
thread reads from ``parent_digest_sends``). BLNO must not move: for an academy
on the production scheduler zone, or with no timezone at all, it must agree
with the old rule (hour and date read in ``SCHEDULER_TZ=America/Chicago``) on
every hourly tick, across both DST changes.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from backend.v2.composition import digests as digests_module
from backend.v2.composition.digests import (
    _ParentDigestProvider,
    digest_due_date,
    digest_window_open,
    resolve_digest_schedule,
)
from backend.v2.shared.tenancy.context import tenant_scope
from backend.v2.shared.time.academy_timezone import (
    LEGACY_FALLBACK_TIMEZONE,
    academy_clock_timezone,
)

PROD_SCHEDULER_TZ = LEGACY_FALLBACK_TIMEZONE  # fly.toml SCHEDULER_TZ


def _old_rule(schedule, now: datetime) -> date | None:
    """What the scheduler did before Phase 4: scheduler-zone hour and date."""
    scheduler_now = now.astimezone(ZoneInfo(PROD_SCHEDULER_TZ))
    if not digest_window_open(schedule, scheduler_now.hour):
        return None
    return scheduler_now.date()


def _ticks(day: date) -> list[datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(hours=12)
    return [start + timedelta(hours=h) for h in range(48)]


@pytest.mark.parametrize(
    "day",
    [date(2026, 9, 29), date(2026, 3, 8), date(2026, 11, 1)],
    ids=["ordinary", "spring", "fall"],
)
@pytest.mark.parametrize("hour", [0, 1, 2, 6, 17, 23])
@pytest.mark.parametrize("academy_tz", ["America/Chicago", None, "", "Not/AZone"])
def test_blno_and_zoneless_academies_match_the_old_scheduler_zone_rule(
    day: date, hour: int, academy_tz: str | None
) -> None:
    schedule = resolve_digest_schedule(
        academy_enabled=True, academy_hour=hour, env_enabled=False, env_hour=6
    )
    zone = academy_clock_timezone(academy_tz)

    for tick in _ticks(day):
        assert digest_due_date(schedule, tick, zone) == _old_rule(schedule, tick), tick


def test_env_default_and_disabled_semantics_are_unchanged() -> None:
    tick = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)  # 07:00 Chicago
    env_default = resolve_digest_schedule(
        academy_enabled=None, academy_hour=None, env_enabled=True, env_hour=6
    )
    disabled = resolve_digest_schedule(
        academy_enabled=False, academy_hour=None, env_enabled=True, env_hour=6
    )

    assert digest_due_date(env_default, tick, LEGACY_FALLBACK_TIMEZONE) == date(2026, 9, 29)
    assert digest_due_date(disabled, tick, LEGACY_FALLBACK_TIMEZONE) is None


def test_another_academy_sends_at_its_own_hour_and_date() -> None:
    schedule = resolve_digest_schedule(
        academy_enabled=True, academy_hour=6, env_enabled=False, env_hour=6
    )
    # 00:30 UTC on Sep 30 is 06:00 IST on Sep 30 but 19:30 CDT on Sep 29.
    tick = datetime(2026, 9, 30, 0, 30, tzinfo=UTC)

    assert digest_due_date(schedule, tick, "Asia/Kolkata") == date(2026, 9, 30)
    assert digest_due_date(schedule, tick - timedelta(hours=1), "Asia/Kolkata") is None
    # Chicago's window (06:00 local) opened that morning; its date is Sep 29.
    assert digest_due_date(schedule, tick, LEGACY_FALLBACK_TIMEZONE) == date(2026, 9, 29)


# --- the parent digest's "today" occurrence window --------------------------


def _provider(academy_doc: dict | None) -> tuple[_ParentDigestProvider, AsyncMock]:
    list_between = AsyncMock(return_value=[])
    provider = _ParentDigestProvider(
        students=SimpleNamespace(),
        enrollments=SimpleNamespace(),
        occurrences=SimpleNamespace(list_between=list_between),
        sessions=SimpleNamespace(),
        levels=SimpleNamespace(),
        curriculum=SimpleNamespace(
            resolve_default_program=SimpleNamespace(execute=AsyncMock(return_value=None)),
            get_program=SimpleNamespace(execute=AsyncMock(return_value=None)),
        ),
        teaching_focus=SimpleNamespace(),
        pathway_placement=SimpleNamespace(),
        ledger=SimpleNamespace(),
        autopay_consents=SimpleNamespace(),
        academies=SimpleNamespace(find_by_id=AsyncMock(return_value=academy_doc)),
    )
    return provider, list_between


@pytest.mark.parametrize(
    ("academy_doc", "start"),
    [
        ({"timezone": "Asia/Kolkata"}, datetime(2026, 7, 15, 18, 30, tzinfo=UTC)),
        ({"timezone": "America/Chicago"}, datetime(2026, 7, 16, 5, 0, tzinfo=UTC)),
        # No zone: the legacy clock, which is what SCHEDULER_TZ gave BLNO.
        ({}, datetime(2026, 7, 16, 5, 0, tzinfo=UTC)),
        (None, datetime(2026, 7, 16, 5, 0, tzinfo=UTC)),
    ],
)
async def test_parent_digest_day_is_the_academy_local_day(
    monkeypatch, academy_doc: dict | None, start: datetime
) -> None:
    monkeypatch.setattr(digests_module, "get_settings", lambda: SimpleNamespace(scheduler_tz="UTC"))
    provider, list_between = _provider(academy_doc)

    with tenant_scope("acad-1"):
        await provider._occurrences_for_run(date(2026, 7, 16))

    kwargs = list_between.await_args.kwargs
    assert kwargs["start_at"] == start
    assert kwargs["end_at"] - kwargs["start_at"] == timedelta(days=1) - timedelta(microseconds=1)
