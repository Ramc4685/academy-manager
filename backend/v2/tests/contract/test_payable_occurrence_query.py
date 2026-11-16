"""Mongo payable occurrence query contract.

The invoiced-tuition basis is pinned on a real mongod in
``test_invoiced_tuition_basis_real_mongo.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.infrastructure.invoiced_tuition_read_model import (
    MongoInvoicedTuitionReadModel,
)
from backend.v2.contexts.coaching.infrastructure.mongo_payout_read_models import (
    MongoPayableOccurrenceQuery,
)


def _query(db) -> MongoPayableOccurrenceQuery:
    return MongoPayableOccurrenceQuery(db, tuition=MongoInvoicedTuitionReadModel(db))


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

    rows = await _query(db).list_in_period(
        academy_id="acad",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )

    assert len(rows) == 1
    assert rows[0].coach_attendance[0].coach_id == "coach-2"
    assert rows[0].coach_attendance[0].role == "assistant"
    assert rows[0].coach_attendance[0].rate_override_minor == 1500


@pytest.mark.asyncio
async def test_assistant_coaches_get_a_period_and_their_assisted_classes(db) -> None:
    """Payroll contract (L7): an assistant listed on an occurrence is paid their
    own line, so the monthly reader returns them with their assisted classes and
    the payable rows carry ``assistant_coach_ids``. The paying coach listed as
    an assistant too is never counted twice."""
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
                "assistant_coach_ids": ["asst-1", "coach-1"],
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
    assert by_coach == {"coach-1": 1, "coach-2": 1, "asst-1": 2, "asst-2": 1}

    rows = await _query(db).list_in_period(
        academy_id="acad", period_start=period_start, period_end=period_end
    )
    assert [r.assistant_coach_ids for r in rows] == [["asst-1", "coach-1"], ["asst-1", "asst-2"]]
