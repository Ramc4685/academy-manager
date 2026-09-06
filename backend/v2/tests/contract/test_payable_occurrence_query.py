"""Mongo payable occurrence query contract."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.coaching.application.use_cases.compute_payout import (
    ComputeCoachPayout,
)
from backend.v2.contexts.coaching.infrastructure.mongo_payout_read_models import (
    MongoCoachRateLookup,
    MongoPayableOccurrenceQuery,
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

    rows = await MongoPayableOccurrenceQuery(db).list_in_period(
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
        occurrences=MongoPayableOccurrenceQuery(db),
        rates=MongoCoachRateLookup(db),
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

    rows = await MongoPayableOccurrenceQuery(db).list_in_period(
        academy_id=acad,
        period_start=_dt("2026-04-01T00:00:00"),
        period_end=_dt("2026-05-01T00:00:00"),
    )

    assert {row.expected_revenue_minor for row in rows} == {15000}


@pytest.mark.asyncio
async def test_expected_revenue_prorates_by_billing_month_not_query_window(db, acad) -> None:
    """#504: a short custom window must not inflate the per-occurrence
    basis. The divisor is the session's occurrence count in its billing
    month, independent of the requested window."""
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": "sess-1",
            "amount_cents": 20000,
        }
    )
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": acad,
                "enrollment_id": f"enr-{i}",
                "session_id": "sess-1",
                "student_id": f"student-{i}",
                "status": "active",
            }
            for i in range(1, 11)
        ]
    )
    for index, day in enumerate((1, 8, 15, 22), start=1):
        await db["session_occurrences"].insert_one(
            {
                "academy_id": acad,
                "occurrence_id": f"occ-{index}",
                "session_id": "sess-1",
                "start_at": _dt(f"2026-07-{day:02d}T18:00:00"),
                "end_at": _dt(f"2026-07-{day:02d}T19:00:00"),
                "status": "completed",
                "scheduled_coach_id": "coach-1",
                "is_payable": True,
            }
        )

    # One-week window containing exactly one of July's four occurrences.
    rows = await MongoPayableOccurrenceQuery(db).list_in_period(
        academy_id=acad,
        period_start=_dt("2026-07-06T00:00:00"),
        period_end=_dt("2026-07-13T00:00:00"),
    )

    assert len(rows) == 1
    # $200/mo x 10 enrollments / 4 July occurrences = $500, NOT $2000.
    assert rows[0].expected_revenue_minor == 50000


@pytest.mark.asyncio
async def test_assistant_coaches_are_never_paid(db) -> None:
    """Payroll contract: an occurrence's ``assistant_coach_ids`` is invisible
    to payroll. The paying coach is ``actual_coach_id`` else
    ``scheduled_coach_id``; an assistant listed on the occurrence gets no
    payout period and no payable row of their own."""
    from backend.v2.contexts.coaching.infrastructure.mongo_payout_read_models import (
        MonthlyCoachOccurrenceReaderAdapter,
    )

    await db["session_occurrences"].insert_many(
        [
            {
                "academy_id": "acad",
                "occurrence_id": "occ-scheduled",
                "session_id": "sess-1",
                "start_at": _dt("2026-05-06T18:00:00"),
                "end_at": _dt("2026-05-06T19:00:00"),
                "status": "completed",
                "scheduled_coach_id": "coach-1",
                "assistant_coach_ids": ["asst-1"],
                "is_payable": True,
            },
            {
                "academy_id": "acad",
                "occurrence_id": "occ-replaced",
                "session_id": "sess-1",
                "start_at": _dt("2026-05-13T18:00:00"),
                "end_at": _dt("2026-05-13T19:00:00"),
                "status": "completed",
                "scheduled_coach_id": "coach-1",
                "actual_coach_id": "coach-2",
                "assistant_coach_ids": ["asst-1", "asst-2"],
                "is_payable": True,
            },
        ]
    )
    period_start, period_end = _dt("2026-05-01T00:00:00"), _dt("2026-06-01T00:00:00")

    grouped = await MonthlyCoachOccurrenceReaderAdapter(
        db["session_occurrences"]
    ).coaches_with_occurrences(academy_id="acad", period_start=period_start, period_end=period_end)
    by_coach = {row.coach_id: row.session_count for row in grouped}
    assert by_coach == {"coach-1": 1, "coach-2": 1}
    assert "asst-1" not in by_coach and "asst-2" not in by_coach

    rows = await MongoPayableOccurrenceQuery(db).list_in_period(
        academy_id="acad", period_start=period_start, period_end=period_end
    )
    assert [(r.scheduled_coach_id, r.actual_coach_id) for r in rows] == [
        ("coach-1", None),
        ("coach-1", "coach-2"),
    ]
    assert all(not hasattr(r, "assistant_coach_ids") for r in rows)
