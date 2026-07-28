"""Past occurrences count as completed for payout purposes.

Nothing in the app ever writes ``session_occurrences.status = "completed"``,
so both payout paths derive completion from the clock:

- ``MongoPayoutRepository._derive_from_completed_occurrences`` (billing,
  feeds the admin payouts dashboard list) matches past non-cancelled
  occurrences in its Mongo filter.
- ``MongoPayableOccurrenceQuery`` (composition, feeds
  ``ComputeCoachPayout`` / payout periods) maps past scheduled
  occurrences to status "completed".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.billing.application.use_cases.finance import MongoPayoutRepository
from backend.v2.contexts.coaching.infrastructure.mongo_payout_read_models import (
    MongoPayableOccurrenceQuery,
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
async def test_billing_derive_pays_past_scheduled_occurrences(db, acad) -> None:
    await db["session_occurrences"].insert_many(
        [
            _occurrence_doc(acad, "occ-past"),
            _occurrence_doc(acad, "occ-future", start_at=_hours_ahead(1), end_at=_hours_ahead(2)),
            _occurrence_doc(acad, "occ-cancelled", status="cancelled"),
        ]
    )
    await db["coach_rates"].insert_one(
        {
            "academy_id": acad,
            "coach_id": "coach-A",
            "rate_id": "rate-1",
            "billing_unit": "per_session",
            "amount_minor": 2500,
            "currency": "USD",
            "effective_from": datetime(2026, 1, 1, tzinfo=UTC),
            "status": "active",
        }
    )

    rows = await MongoPayoutRepository(db).list_all()

    assert len(rows) == 1
    assert rows[0].coach_id == "coach-A"
    assert rows[0].amount_cents == 2500
    assert rows[0].sessions_count == 1


@pytest.mark.asyncio
async def test_payable_occurrence_query_derives_completion_and_revenue(db, acad) -> None:
    await db["session_occurrences"].insert_many(
        [
            _occurrence_doc(acad, "occ-past"),
            _occurrence_doc(acad, "occ-future", start_at=_hours_ahead(1), end_at=_hours_ahead(2)),
            _occurrence_doc(acad, "occ-cancelled", status="cancelled"),
        ]
    )
    await db["sessions"].insert_one(
        {"academy_id": acad, "session_id": "sess-1", "amount_cents": 15000}
    )
    await db["enrollments"].insert_many(
        [
            {"academy_id": acad, "session_id": "sess-1", "status": "active"},
            {"academy_id": acad, "session_id": "sess-1", "status": "active"},
            {"academy_id": acad, "session_id": "sess-1", "status": "cancelled"},
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

    occurrences = await MongoPayableOccurrenceQuery(db).list_in_period(
        acad, _hours_ago(48), _hours_ahead(48)
    )

    by_id = {occ.occurrence_id: occ for occ in occurrences}
    assert by_id["occ-past"].status == "completed"
    assert by_id["occ-future"].status == "scheduled"
    assert by_id["occ-cancelled"].status == "cancelled"
    # 2 active enrollments x $150.00 monthly price / 2 non-cancelled occurrences.
    assert by_id["occ-past"].expected_revenue_minor == 15000
    assert by_id["occ-past"].coach_attendance[0].status == "absent"
