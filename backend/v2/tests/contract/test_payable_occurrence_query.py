"""Mongo payable occurrence query contract."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.composition.admin import _MongoCoachRateRepository, _MongoPayableOccurrenceQuery
from backend.v2.contexts.coaching.application.use_cases.compute_payout import (
    ComputeCoachPayout,
)


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


@pytest.mark.asyncio
async def test_percent_payout_uses_legacy_seeded_coach_rate_fields(db, acad) -> None:
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": "sess-1",
            "amount_cents": 6000,
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "enr-1",
            "session_id": "sess-1",
            "student_id": "student-1",
            "status": "active",
        }
    )
    await db["session_occurrences"].insert_one(
        {
            "academy_id": acad,
            "occurrence_id": "occ-1",
            "session_id": "sess-1",
            "start_at": _dt("2026-04-01T18:00:00"),
            "end_at": _dt("2026-04-01T19:00:00"),
            "status": "completed",
            "scheduled_coach_id": "coach-1",
            "is_payable": True,
        }
    )
    await db["coach_rates"].insert_one(
        {
            "academy_id": acad,
            "rate_id": "rate-legacy",
            "coach_id": "coach-1",
            "rate_type": "percentage_of_expected_revenue",
            "percentage": 30.0,
            "per_session_cents": 2500,
            "effective_from": _dt("2026-04-01T00:00:00"),
            "status": "active",
        }
    )

    statement = await ComputeCoachPayout(
        occurrences=_MongoPayableOccurrenceQuery(db),
        rates=_MongoCoachRateRepository(db),
    ).execute(
        coach_id="coach-1",
        academy_id=acad,
        period_start=_dt("2026-04-01T00:00:00"),
        period_end=_dt("2026-05-01T00:00:00"),
    )

    assert statement.total_minor == 1800
    assert statement.lines[0].percent_bps == 3000
    assert statement.lines[0].expected_revenue_minor == 6000


@pytest.mark.asyncio
async def test_expected_revenue_prorates_monthly_session_fee_across_occurrences(db, acad) -> None:
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": "sess-1",
            "amount_cents": 60000,
        }
    )
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": acad,
                "enrollment_id": "enr-1",
                "session_id": "sess-1",
                "student_id": "student-1",
                "status": "active",
            },
            {
                "academy_id": acad,
                "enrollment_id": "enr-2",
                "session_id": "sess-1",
                "student_id": "student-2",
                "status": "paused",
            },
        ]
    )
    for index, day in enumerate((1, 8, 15, 22), start=1):
        await db["session_occurrences"].insert_one(
            {
                "academy_id": acad,
                "occurrence_id": f"occ-{index}",
                "session_id": "sess-1",
                "start_at": _dt(f"2026-04-{day:02d}T18:00:00"),
                "end_at": _dt(f"2026-04-{day:02d}T19:00:00"),
                "status": "completed",
                "scheduled_coach_id": "coach-1",
                "is_payable": True,
            }
        )

    rows = await _MongoPayableOccurrenceQuery(db).list_in_period(
        academy_id=acad,
        period_start=_dt("2026-04-01T00:00:00"),
        period_end=_dt("2026-05-01T00:00:00"),
    )

    assert {row.expected_revenue_minor for row in rows} == {15000}
