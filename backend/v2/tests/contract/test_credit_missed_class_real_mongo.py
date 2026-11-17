"""Credit a missed class over a real mongod (#1207).

Drives the production composition (``compose_occurrence_cancellations``) so
the occurrence CAS, the attendance read, the billing override, the credit
ledger's unique source index (migration 0168) and the payout lock are real.
The claims: the preview quotes the cents the confirm issues; the credit is
the same row a pre-class call-off writes (same type, same source key), so it
can never be issued twice by either path; attendance and a frozen payout are
respected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.composition.occurrence_cancellation import (
    compose_apply_occurrence_cancellation,
    compose_occurrence_cancellations,
)
from backend.v2.contexts.billing.application.use_cases.apply_occurrence_cancellation import (
    ApplyOccurrenceCancellationCommand,
)
from backend.v2.contexts.billing.domain.credits import (
    CLASS_CANCELLATION_SOURCE_TYPE,
    class_cancellation_credit_cents,
    class_cancellation_source_id,
)
from backend.v2.contexts.enrollment.application.use_cases.cancel_session_occurrence import (
    CancelSessionOccurrenceCommand,
)
from backend.v2.contexts.enrollment.domain.errors import (
    MissedClassHadAttendance,
    OccurrenceAlreadyCancelled,
)
from backend.v2.shared.tenancy import tenant_scope

pytestmark = pytest.mark.asyncio

ACADEMY = "acad-1207"
TZ = "America/Chicago"
# September 2026 Thursdays 3, 10, 17, 24 at 18:00 Chicago; long past "now".
MISSED_DAY = datetime(2026, 9, 10, 23, 0, tzinfo=UTC)


async def _no_materialize(session: Any) -> None:
    return None


async def _seed(db: Any) -> None:
    await db["academies"].insert_one(
        {"academy_id": ACADEMY, "display_name": "Test Academy", "timezone": TZ}
    )
    await db["sessions"].insert_one(
        {
            "academy_id": ACADEMY,
            "session_id": "sess-1",
            "coach_id": "coach-1",
            "title": "Beginner badminton",
            "location": "Court 1",
            "start_at": datetime(2026, 9, 3, 23, 0, tzinfo=UTC),
            "end_at": datetime(2026, 9, 4, 0, 0, tzinfo=UTC),
            "capacity": 10,
            "amount_cents": 12000,
            "timezone": TZ,
            "days_of_week": ["Thu"],
            "start_time": "18:00",
            "end_time": "19:00",
            "start_date": "2026-09-01",
            "end_date": "2026-12-31",
            "status": "scheduled",
        }
    )
    await db["students"].insert_one(
        {"academy_id": ACADEMY, "student_id": "st-1", "parent_id": "par-1"}
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": ACADEMY,
            "enrollment_id": "enr-1",
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "par-1",
            "status": "active",
            "enrolled_at": datetime(2026, 6, 1, tzinfo=UTC),
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": ACADEMY,
            "invoice_id": "inv-1",
            "parent_id": "par-1",
            "student_id": "st-1",
            "enrollment_id": "enr-1",
            "period": "2026-09",
            "status": "paid",
            "subtotal_cents": 12000,
            "discount_cents": 0,
            "total_cents": 12000,
            "balance_due_cents": 0,
            "currency": "usd",
            "due_date": datetime(2026, 9, 8, tzinfo=UTC),
            "created_at": datetime(2026, 8, 28, tzinfo=UTC),
            "updated_at": datetime(2026, 8, 28, tzinfo=UTC),
        }
    )
    for occurrence_id, start in (
        ("occ-missed", MISSED_DAY),
        ("occ-held", MISSED_DAY + timedelta(days=7)),
    ):
        await db["session_occurrences"].insert_one(
            {
                "occurrence_id": occurrence_id,
                "academy_id": ACADEMY,
                "session_id": "sess-1",
                "template_session_id": "sess-1",
                "start_at": start,
                "end_at": start + timedelta(hours=1),
                "status": "scheduled",
                "scheduled_coach_id": "coach-1",
                "is_billable": True,
                "is_payable": True,
            }
        )


def _cancel(db: Any):
    return compose_occurrence_cancellations(db, None, _no_materialize)["cancel_session_occurrence"]


def _missed(occurrence_id: str = "occ-missed") -> CancelSessionOccurrenceCommand:
    return CancelSessionOccurrenceCommand(
        occurrence_id=occurrence_id,
        reason="gym closed, found out late",
        actor_id="admin-1",
        notify=False,
        missed=True,
    )


async def _credits(db: Any) -> list[dict[str, Any]]:
    return [
        doc
        async for doc in db["account_credit_ledger"].find(
            {"academy_id": ACADEMY, "type": "CLASS_CANCELLATION_CREDIT"}
        )
    ]


async def test_preview_matches_confirm_to_the_cent_and_is_the_call_off_credit(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        cancel = _cancel(real_db)
        preview = await cancel.preview_missed("occ-missed")
        assert await _credits(real_db) == []
        assert (await real_db["session_occurrences"].find_one({"occurrence_id": "occ-missed"}))[
            "status"
        ] == "scheduled"

        result = await cancel.execute(_missed())

    expected = class_cancellation_credit_cents(period_charge_cents=12000, billable_classes=4)
    assert [(f.enrollment_id, f.amount_cents, f.outcome) for f in preview.families] == [
        ("enr-1", expected, "would_credit")
    ]
    assert preview.credit_total_cents == result.credit_total_cents == expected
    credits = await _credits(real_db)
    assert len(credits) == 1
    credit = credits[0]
    # The exact row a pre-class call-off writes, with who and why on it.
    assert credit["amount_cents"] == expected
    assert credit["source_type"] == CLASS_CANCELLATION_SOURCE_TYPE
    assert credit["source_id"] == class_cancellation_source_id(
        occurrence_id="occ-missed", enrollment_id="enr-1"
    )
    assert credit["approved_by"] == "admin-1"
    assert "gym closed, found out late" in credit["reason"]
    # No class on the parent calendar, and the coach is not paid for it.
    row = await real_db["session_occurrences"].find_one({"occurrence_id": "occ-missed"})
    assert row["status"] == "cancelled"
    assert row["is_payable"] is False and row["is_billable"] is False
    override = await real_db["session_occurrence_overrides"].find_one({"academy_id": ACADEMY})
    assert override is not None and override["status"] == "cancelled"
    event = await real_db["enrollment_events"].find_one(
        {"academy_id": ACADEMY, "event_type": "occurrence_cancelled"}
    )
    assert event["metadata"]["missed_class"] == "true"


async def test_rerunning_never_credits_twice(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        cancel = _cancel(real_db)
        await cancel.execute(_missed())
        with pytest.raises(OccurrenceAlreadyCancelled):
            await cancel.execute(_missed())
        # Even the billing step itself, replayed, finds the credit already issued.
        replay = await compose_apply_occurrence_cancellation(real_db).execute(
            ApplyOccurrenceCancellationCommand(
                occurrence_id="occ-missed",
                session_id="sess-1",
                start_at=MISSED_DAY,
                reason="again",
                actor_id="admin-2",
            )
        )
    assert [d.outcome for d in replay.decisions] == ["already_credited"]
    assert len(await _credits(real_db)) == 1


async def test_a_date_with_students_marked_present_is_refused(real_db: Any) -> None:
    await _seed(real_db)
    await real_db["attendance"].insert_one(
        {
            "academy_id": ACADEMY,
            "attendance_id": "att-1",
            "occurrence_id": "occ-held",
            "session_id": "sess-1",
            "student_id": "st-1",
            "marked_by": "coach-1",
            "marked_at": MISSED_DAY + timedelta(days=7, minutes=5),
            "status": "present",
            "client_app_version": "test",
        }
    )
    with tenant_scope(ACADEMY):
        with pytest.raises(MissedClassHadAttendance):
            await _cancel(real_db).execute(_missed("occ-held"))
    assert await _credits(real_db) == []
    row = await real_db["session_occurrences"].find_one({"occurrence_id": "occ-held"})
    assert row["status"] == "scheduled"


async def test_a_frozen_payout_still_credits_and_flags_payroll(real_db: Any) -> None:
    await _seed(real_db)
    await real_db["payout_periods"].insert_one(
        {
            "academy_id": ACADEMY,
            "payout_period_id": "pp-1",
            "coach_id": "coach-1",
            "period_start": datetime(2026, 9, 1, tzinfo=UTC),
            "period_end": datetime(2026, 10, 1, tzinfo=UTC),
            "status": "paid",
            "created_at": datetime(2026, 10, 2, tzinfo=UTC),
            "updated_at": datetime(2026, 10, 2, tzinfo=UTC),
        }
    )
    with tenant_scope(ACADEMY):
        result = await _cancel(real_db).execute(_missed())
    assert result.payroll_flag and "paid" in result.payroll_flag
    assert len(await _credits(real_db)) == 1
