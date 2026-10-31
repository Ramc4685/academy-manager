"""Zoneless legacy sessions read the ACADEMY's zone (hardcoded-values row 7).

Before: every site fell back to a hardcoded ``America/Chicago``. After:
session zone -> academy zone -> ``LEGACY_FALLBACK_TIMEZONE``. BLNO's academy
is ``America/Chicago``, so its output is pinned unchanged here; a tenant on
another zone now gets its own clock.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from backend.v2.contexts.billing.infrastructure.mongo_move_schedule_reader import (
    MongoMoveScheduleReader,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_writer import (
    MongoSessionWriter,
)
from backend.v2.shared.time import academy_timezone_lookup, resolve_session_doc_timezone

ACADEMY = "test-academy"


def _template(**extra: object) -> dict[str, object]:
    doc: dict[str, object] = {
        "academy_id": ACADEMY,
        "session_id": "sess-legacy",
        "title": "Tue 6pm",
        "location": "Court 1",
        "coach_id": "coach-1",
        "status": "scheduled",
        "days_of_week": ["Tue"],
        "start_time": "18:00",
        "end_time": "19:00",
        "monthly_price_cents": 12_000,
    }
    doc.update(extra)
    return doc


async def _seed(db, *, academy_zone: str | None, **extra: object) -> None:
    academy: dict[str, object] = {"academy_id": ACADEMY}
    if academy_zone is not None:
        academy["timezone"] = academy_zone
    await db["academies"].insert_one(academy)
    await db["sessions"].insert_one(_template(**extra))


def _local_hour(instant: datetime, zone: str) -> int:
    return instant.astimezone(ZoneInfo(zone)).hour


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("academy_zone", "expected_zone"),
    [
        ("America/Chicago", "America/Chicago"),  # BLNO: unchanged
        (None, "America/Chicago"),  # no academy zone: legacy, unchanged
        ("America/Los_Angeles", "America/Los_Angeles"),  # other tenant: its own clock
    ],
)
async def test_repo_expands_zoneless_template_in_academy_zone(
    db, acad, academy_zone: str | None, expected_zone: str
) -> None:
    await _seed(db, academy_zone=academy_zone)
    session = await MongoSessionRepository(db).get("sess-legacy")
    assert session is not None
    assert _local_hour(session.start_at, expected_zone) == 18
    assert session.start_at.astimezone(ZoneInfo(expected_zone)).strftime("%a") == "Tue"
    # The stored zone is still reported as absent; only the expansion changes.
    assert session.timezone is None


@pytest.mark.asyncio
async def test_repo_keeps_the_session_zone_over_the_academy_zone(db, acad) -> None:
    await _seed(db, academy_zone="America/Los_Angeles", timezone="America/New_York")
    session = await MongoSessionRepository(db).get("sess-legacy")
    assert session is not None
    assert _local_hour(session.start_at, "America/New_York") == 18


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("academy_zone", "expected_zone"),
    [("America/Chicago", "America/Chicago"), ("America/Denver", "America/Denver")],
)
async def test_move_schedule_reads_academy_zone(
    db, acad, academy_zone: str, expected_zone: str
) -> None:
    await _seed(db, academy_zone=academy_zone, start_date="2026-01-01")
    schedule = await MongoMoveScheduleReader(db).load(session_id="sess-legacy", period="2026-09")
    assert schedule is not None
    assert schedule.timezone == expected_zone
    assert schedule.occurrences
    assert all(_local_hour(o.start_at, expected_zone) == 18 for o in schedule.occurrences)


@pytest.mark.asyncio
async def test_doc_resolver_reads_the_docs_own_academy_only_when_needed(db) -> None:
    await db["academies"].insert_many(
        [
            {"academy_id": "acad_blno_badminton", "timezone": "America/Chicago"},
            {"academy_id": "acad-west", "timezone": "America/Los_Angeles"},
        ]
    )
    reader = academy_timezone_lookup(db)
    assert (
        await resolve_session_doc_timezone(reader, {"academy_id": "acad_blno_badminton"})
        == "America/Chicago"
    )
    assert (
        await resolve_session_doc_timezone(reader, {"academy_id": "acad-west"})
        == "America/Los_Angeles"
    )
    assert (
        await resolve_session_doc_timezone(
            reader, {"academy_id": "acad-west", "timezone": "Europe/London"}
        )
        == "Europe/London"
    )
    assert await resolve_session_doc_timezone(reader, {}) == "America/Chicago"


@pytest.mark.asyncio
async def test_resolver_survives_a_failing_lookup() -> None:
    async def broken(_academy_id: str) -> str | None:
        raise RuntimeError("mongo down")

    assert await resolve_session_doc_timezone(broken, {"academy_id": "x"}) == "America/Chicago"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("academy_zone", "target_zone", "matches"),
    [
        ("America/Chicago", "America/Chicago", True),  # BLNO: unchanged
        ("America/Los_Angeles", "America/Los_Angeles", True),  # legacy row = tenant zone
        ("America/Los_Angeles", "America/Chicago", False),  # no silent Chicago merge
    ],
)
async def test_duplicate_series_compares_zoneless_rows_in_academy_zone(
    db, acad, academy_zone: str, target_zone: str, matches: bool
) -> None:
    await _seed(db, academy_zone=academy_zone, start_at=datetime(2026, 9, 1, 23, tzinfo=UTC))
    found = await MongoSessionWriter(db).find_duplicate_recurring_series(
        title="Tue 6pm",
        location="Court 1",
        coach_id="coach-1",
        days_of_week=["Tue"],
        start_time="18:00",
        end_time="19:00",
        timezone=target_zone,
    )
    assert (found is not None) is matches
