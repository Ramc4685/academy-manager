"""Regression tests for #510 — coach date queries must bucket occurrences by
the session-local calendar day, not UTC day bounds.

A Chicago academy class at 7:00pm CDT is stored as 00:00 UTC the *next* day.
Before the fix, ``MongoSessionOccurrenceRepository.list_for_coach_on_date``
used midnight-to-midnight UTC bounds, so the coach's Today view for the
class's actual local date never showed it (it appeared under tomorrow), and
``_month_window`` pushed month-end evening occurrences into the next month's
payroll.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.v2.contexts.enrollment.application.use_cases.list_coach_occurrences_for_date import (
    ListCoachOccurrencesForDate,
)
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.migrations import run_pending_migrations
from backend.v2.shared.tenancy.context import tenant_scope

CHICAGO = ZoneInfo("America/Chicago")


@dataclass(frozen=True)
class _FakeSession:
    session_id: str
    title: str = "Evening class"
    location: str = "Court 1"
    timezone: str | None = "America/Chicago"


class _FakeSessionQuery:
    def __init__(self, sessions: dict[str, _FakeSession]) -> None:
        self._sessions = sessions

    async def get(self, session_id: str) -> _FakeSession | None:
        return self._sessions.get(session_id)


def _occurrence(
    occurrence_id: str,
    session_id: str,
    start_local: datetime,
) -> SessionOccurrence:
    start_utc = start_local.astimezone(UTC)
    return SessionOccurrence(
        occurrence_id=occurrence_id,
        academy_id="academy-a",
        session_id=session_id,
        start_at=start_utc,
        end_at=start_utc + timedelta(hours=1),
        status="scheduled",
        scheduled_coach_id="coach-1",
    )


@pytest.mark.asyncio
async def test_evening_class_appears_on_its_local_date_not_utc_date(db) -> None:
    """7:00pm CDT on 2026-06-01 == 2026-06-02T00:00Z. The coach asking for
    June 1 (the class's real local day) must see it; asking for June 2 must
    not."""
    await run_pending_migrations(db)

    with tenant_scope("academy-a"):
        repo = MongoSessionOccurrenceRepository(db)
        await repo.save_many(
            [
                _occurrence(
                    "occ-evening",
                    "sess-evening",
                    datetime(2026, 6, 1, 19, 0, tzinfo=CHICAGO),
                ),
                _occurrence(
                    "occ-morning-next",
                    "sess-morning",
                    datetime(2026, 6, 2, 9, 0, tzinfo=CHICAGO),
                ),
            ]
        )

        use_case = ListCoachOccurrencesForDate(
            occurrences=repo,
            sessions=_FakeSessionQuery(
                {
                    "sess-evening": _FakeSession("sess-evening"),
                    "sess-morning": _FakeSession("sess-morning"),
                }
            ),
        )

        june_first = await use_case.execute("coach-1", date(2026, 6, 1))
        june_second = await use_case.execute("coach-1", date(2026, 6, 2))

    assert [row.occurrence_id for row in june_first] == ["occ-evening"]
    assert [row.occurrence_id for row in june_second] == ["occ-morning-next"]


@pytest.mark.asyncio
async def test_sessions_without_timezone_keep_utc_day_semantics(db) -> None:
    """Fixtures / legacy sessions with no timezone fall back to the UTC
    calendar day, preserving pre-#510 behavior."""
    await run_pending_migrations(db)

    with tenant_scope("academy-a"):
        repo = MongoSessionOccurrenceRepository(db)
        await repo.save_many(
            [
                _occurrence(
                    "occ-utc",
                    "sess-utc",
                    datetime(2026, 6, 1, 18, 0, tzinfo=UTC),
                ),
            ]
        )

        use_case = ListCoachOccurrencesForDate(
            occurrences=repo,
            sessions=_FakeSessionQuery({"sess-utc": _FakeSession("sess-utc", timezone=None)}),
        )

        same_day = await use_case.execute("coach-1", date(2026, 6, 1))
        next_day = await use_case.execute("coach-1", date(2026, 6, 2))

    assert [row.occurrence_id for row in same_day] == ["occ-utc"]
    assert next_day == []


def test_payroll_month_window_uses_academy_timezone() -> None:
    """A month-end 7:00pm CDT class (stored as 00:00 UTC on the 1st) must
    stay inside its local month's payroll window."""
    from backend.v2.interfaces.admin.payroll_routes import _month_window

    start, end = _month_window("2026-07", CHICAGO)

    # Chicago July == [Jul 1 05:00Z, Aug 1 05:00Z) in UTC during CDT.
    assert start == datetime(2026, 7, 1, 5, 0, tzinfo=UTC)
    assert end == datetime(2026, 8, 1, 5, 0, tzinfo=UTC)

    # July 31, 7pm CDT == Aug 1 00:00Z — inside the July window now.
    month_end_evening = datetime(2026, 7, 31, 19, 0, tzinfo=CHICAGO).astimezone(UTC)
    assert start <= month_end_evening < end

    # Default (no tz) preserves the old UTC month window.
    utc_start, utc_end = _month_window("2026-07")
    assert utc_start == datetime(2026, 7, 1, tzinfo=UTC)
    assert utc_end == datetime(2026, 8, 1, tzinfo=UTC)
