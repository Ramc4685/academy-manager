"""Mongo payable occurrence query contract."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.composition.admin import _MongoPayableOccurrenceQuery


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


@pytest.mark.asyncio
async def test_payable_occurrence_query_attaches_coach_attendance(db) -> None:
    await db["session_occurrences"].insert_one(
        {
            "academy_id": "acad",
            "occurrence_id": "occ-1",
            "session_id": "sess-1",
            "start_at": _dt("2026-05-27T18:00:00"),
            "end_at": _dt("2026-05-27T19:00:00"),
            "status": "scheduled",
            "scheduled_coach_id": "coach-1",
            "is_payable": True,
        }
    )
    await db["coach_attendance"].insert_one(
        {
            "academy_id": "acad",
            "attendance_id": "coach-att-1",
            "occurrence_id": "occ-1",
            "coach_id": "coach-2",
            "status": "present",
            "role": "assistant",
            "source": "admin",
            "marked_by": "admin-1",
            "marked_at": _dt("2026-05-27T19:05:00"),
            "rate_override_minor": 1500,
            "note": "Helped with beginner court",
        }
    )

    rows = await _MongoPayableOccurrenceQuery(db).list_in_period(
        academy_id="acad",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )

    assert len(rows) == 1
    assert rows[0].coach_attendance[0].coach_id == "coach-2"
    assert rows[0].coach_attendance[0].role == "assistant"
    assert rows[0].coach_attendance[0].rate_override_minor == 1500
