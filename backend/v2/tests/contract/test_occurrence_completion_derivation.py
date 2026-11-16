"""Past occurrences count as completed for payout purposes.

Nothing in the app ever writes ``session_occurrences.status = "completed"``,
so ``MongoPayableOccurrenceQuery`` (feeds ``ComputeCoachPayout`` and payout
periods) maps past scheduled occurrences to status "completed".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.billing.infrastructure.invoiced_tuition_read_model import (
    MongoInvoicedTuitionReadModel,
)
from backend.v2.contexts.coaching.infrastructure.mongo_payout_read_models import (
    MongoPayableOccurrenceQuery,
    MonthlyCoachOccurrenceReaderAdapter,
)


def _hours_ago(hours: int) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


def _hours_ahead(hours: int) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)


def _occurrence_doc(acad: str, occurrence_id: str, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "academy_id": acad,
        "occurrence_id": occurrence_id,
        "session_id": "sess-1",
        "start_at": _hours_ago(2),
        "end_at": _hours_ago(1),
        "status": "scheduled",
        "scheduled_coach_id": "coach-A",
        "is_payable": True,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_payable_occurrence_query_derives_completion(db, acad) -> None:
    await db["session_occurrences"].insert_many(
        [
            _occurrence_doc(acad, "occ-past"),
            _occurrence_doc(acad, "occ-future", start_at=_hours_ahead(1), end_at=_hours_ahead(2)),
            _occurrence_doc(acad, "occ-cancelled", status="cancelled"),
        ]
    )
    await db["coach_attendance"].insert_one(
        {
            "academy_id": acad,
            "occurrence_id": "occ-past",
            "coach_id": "coach-A",
            "status": "absent",
            "role": "lead",
            "marked_at": _hours_ago(1),
        }
    )

    occurrences = await MongoPayableOccurrenceQuery(
        db, tuition=MongoInvoicedTuitionReadModel(db)
    ).list_in_period(acad, _hours_ago(48), _hours_ahead(48))

    by_id = {occ.occurrence_id: occ for occ in occurrences}
    assert by_id["occ-past"].status == "completed"
    assert by_id["occ-future"].status == "scheduled"
    assert by_id["occ-cancelled"].status == "cancelled"
    assert by_id["occ-past"].coach_attendance[0].status == "absent"


@pytest.mark.asyncio
async def test_monthly_reader_includes_scheduled_coach_displaced_by_replacement(db, acad) -> None:
    """A displaced scheduled coach must still show up in the month's payroll.

    Regression for #228: without a payout period the coach has nowhere to
    carry the ``replaced_by_actual_coach`` trace, so a mistaken attribution
    stays invisible. The occurrence must not be double-counted though — it is
    one session of work, and it belongs to the coach who was paid.
    """
    await db["session_occurrences"].insert_many(
        [
            _occurrence_doc(
                acad,
                "occ-replaced",
                scheduled_coach_id="coach-A",
                actual_coach_id="coach-B",
            ),
            _occurrence_doc(acad, "occ-plain", scheduled_coach_id="coach-B"),
        ]
    )

    rows = await MonthlyCoachOccurrenceReaderAdapter(
        db["session_occurrences"]
    ).coaches_with_occurrences(
        academy_id=acad, period_start=_hours_ago(48), period_end=_hours_ahead(48)
    )

    counts = {row.coach_id: row.session_count for row in rows}
    assert counts == {"coach-A": 0, "coach-B": 2}


@pytest.mark.asyncio
async def test_monthly_reader_ignores_self_attribution_and_cancelled(db, acad) -> None:
    await db["session_occurrences"].insert_many(
        [
            _occurrence_doc(
                acad,
                "occ-self",
                scheduled_coach_id="coach-A",
                actual_coach_id="coach-A",
            ),
            _occurrence_doc(
                acad,
                "occ-cancelled",
                status="cancelled",
                scheduled_coach_id="coach-A",
                actual_coach_id="coach-B",
            ),
        ]
    )

    rows = await MonthlyCoachOccurrenceReaderAdapter(
        db["session_occurrences"]
    ).coaches_with_occurrences(
        academy_id=acad, period_start=_hours_ago(48), period_end=_hours_ahead(48)
    )

    assert {row.coach_id: row.session_count for row in rows} == {"coach-A": 1}
