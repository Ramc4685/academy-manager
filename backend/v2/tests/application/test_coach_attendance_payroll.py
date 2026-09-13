"""Coach attendance payroll use case tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.coaching.application.ports import OccurrenceDetails
from backend.v2.contexts.coaching.application.use_cases.mark_coach_attendance import (
    MarkCoachAttendance,
    MarkCoachAttendanceCommand,
)
from backend.v2.contexts.coaching.domain.errors import PayoutPeriodFrozen
from backend.v2.contexts.coaching.domain.models import CoachAttendance


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


class _FakeCoachAttendanceRepo:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], CoachAttendance] = {}

    async def upsert(self, row: CoachAttendance) -> CoachAttendance:
        self.rows[(row.occurrence_id, row.coach_id)] = row
        return row

    async def find_for_occurrence_coach(
        self, occurrence_id: str, coach_id: str
    ) -> CoachAttendance | None:
        return self.rows.get((occurrence_id, coach_id))

    async def list_for_occurrences(self, occurrence_ids: list[str]) -> list[CoachAttendance]:
        return [row for key, row in self.rows.items() if key[0] in occurrence_ids]


class _FakeOccurrenceLookup:
    async def get(self, occurrence_id: str) -> OccurrenceDetails | None:
        if occurrence_id == "missing":
            return None
        return OccurrenceDetails(
            occurrence_id=occurrence_id,
            session_id="sess-1",
            starts_at=_dt("2026-05-27T18:00:00"),
            status="scheduled",
            scheduled_coach_id="coach-1",
            actual_coach_id=None,
            substitute_coach_id="coach-2",
            template_session_id=None,
        )


@pytest.mark.asyncio
async def test_coach_self_check_in_records_present_for_assigned_occurrence() -> None:
    repo = _FakeCoachAttendanceRepo()
    use_case = MarkCoachAttendance(
        coach_attendance=repo,
        occurrence_lookup=_FakeOccurrenceLookup(),
        academy_id="acad",
        clock=lambda: _dt("2026-05-27T18:05:00"),
    )

    row = await use_case.execute(
        MarkCoachAttendanceCommand(
            occurrence_id="occ-1",
            coach_id="coach-1",
            status="present",
            role="lead",
            source="coach_self",
        ),
        actor_id="coach-1",
    )

    assert row.coach_id == "coach-1"
    assert row.status == "present"
    assert row.role == "lead"
    assert row.source == "coach_self"
    assert row.marked_by == "coach-1"


@pytest.mark.asyncio
async def test_admin_can_mark_assistant_with_rate_override_and_note() -> None:
    repo = _FakeCoachAttendanceRepo()
    use_case = MarkCoachAttendance(
        coach_attendance=repo,
        occurrence_lookup=_FakeOccurrenceLookup(),
        academy_id="acad",
        clock=lambda: _dt("2026-05-27T18:10:00"),
    )

    row = await use_case.execute(
        MarkCoachAttendanceCommand(
            occurrence_id="occ-1",
            coach_id="coach-assist",
            status="present",
            role="assistant",
            source="admin",
            rate_override_minor=1500,
            note="Helped with beginner court",
        ),
        actor_id="admin-1",
    )

    assert row.coach_id == "coach-assist"
    assert row.role == "assistant"
    assert row.rate_override_minor == 1500
    assert row.note == "Helped with beginner court"
    assert row.marked_by == "admin-1"


class _FakePayoutPeriodLock:
    """Stand-in for the finance-backed frozen-window lookup (#787)."""

    def __init__(self, status: str | None) -> None:
        self._status = status
        self.calls: list[tuple[str, datetime]] = []

    async def locked_status_for(self, *, coach_id: str, at: datetime) -> str | None:
        self.calls.append((coach_id, at))
        return self._status


@pytest.mark.asyncio
async def test_marking_attendance_is_refused_once_the_payout_period_is_approved() -> None:
    """#787: payroll inputs must not drift behind a frozen payout snapshot."""
    repo = _FakeCoachAttendanceRepo()
    lock = _FakePayoutPeriodLock("approved")
    use_case = MarkCoachAttendance(
        coach_attendance=repo,
        occurrence_lookup=_FakeOccurrenceLookup(),
        academy_id="acad",
        payout_lock=lock,
        clock=lambda: _dt("2026-05-27T18:10:00"),
    )

    with pytest.raises(PayoutPeriodFrozen):
        await use_case.execute(
            MarkCoachAttendanceCommand(
                occurrence_id="occ-1",
                coach_id="coach-1",
                status="absent",
                source="admin",
                rate_override_minor=9900,
            ),
            actor_id="admin-1",
        )

    assert repo.rows == {}
    assert lock.calls == [("coach-1", _dt("2026-05-27T18:00:00"))]


@pytest.mark.asyncio
async def test_marking_attendance_still_works_while_the_period_is_draft() -> None:
    repo = _FakeCoachAttendanceRepo()
    use_case = MarkCoachAttendance(
        coach_attendance=repo,
        occurrence_lookup=_FakeOccurrenceLookup(),
        academy_id="acad",
        payout_lock=_FakePayoutPeriodLock(None),
        clock=lambda: _dt("2026-05-27T18:10:00"),
    )

    row = await use_case.execute(
        MarkCoachAttendanceCommand(
            occurrence_id="occ-1",
            coach_id="coach-1",
            status="present",
            source="admin",
        ),
        actor_id="admin-1",
    )

    assert row.status == "present"
