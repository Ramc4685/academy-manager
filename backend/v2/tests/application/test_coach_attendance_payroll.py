"""Coach attendance payroll use case tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.coaching.application.ports import OccurrenceDetails
from backend.v2.contexts.coaching.application.use_cases.mark_coach_attendance import (
    MarkCoachAttendance,
    MarkCoachAttendanceCommand,
)
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
