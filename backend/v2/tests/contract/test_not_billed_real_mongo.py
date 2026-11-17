""" "Not billed" children on a real mongod (validators and indexes from the migrations).

Covers the write (owner marks an enrollment not billed / starts billing, the
audit row, the optional void), the monthly run skipping it and restarting next
month, the payroll warning shape it used to cause, and the headcounts.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.enrollment_not_billed import (
    SetEnrollmentBilling,
    SetEnrollmentBillingCommand,
)
from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.contexts.billing.infrastructure.admin_reports_read_model import (
    make_projected_income_report,
)
from backend.v2.contexts.billing.infrastructure.invoiced_tuition_read_model import (
    MongoInvoicedTuitionReadModel,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_enrollment_not_billed_store import (
    MongoEnrollmentNotBilledStore,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository
from backend.v2.contexts.coaching.application.use_cases.compute_payout import (
    ComputeCoachPayout,
)
from backend.v2.contexts.coaching.infrastructure.mongo_payout_read_models import (
    MongoCoachRateLookup,
    MongoPayableOccurrenceQuery,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)

pytestmark = pytest.mark.asyncio

ACAD = "test-academy"
NOW = datetime(2026, 11, 16, 18, tzinfo=UTC)
# Local November on the Central clock (CST from Nov 1, UTC-6; Nov 1 is CDT).
NOV_START, NOV_END = datetime(2026, 11, 1, 5, tzinfo=UTC), datetime(2026, 12, 1, 6, tzinfo=UTC)


async def _central(_academy_id: str) -> str:
    return "America/Chicago"


class _Month:
    def __init__(self, period: str) -> None:
        self.period = period

    async def current_period(self) -> str:
        return self.period


async def _enroll(
    db: Any,
    enrollment_id: str,
    *,
    student_id: str,
    session_id: str = "sess-1",
    billing_type: str | None = None,
    status: str = "active",
) -> None:
    doc: dict[str, Any] = {
        "academy_id": ACAD,
        "enrollment_id": enrollment_id,
        "student_id": student_id,
        "session_id": session_id,
        "parent_id": "parent-1",
        "status": status,
        "billing_start_at": datetime(2026, 1, 1, tzinfo=UTC),
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    if billing_type is not None:
        doc["billing_type"] = billing_type
    await db["enrollments"].insert_one(doc)


async def _invoice(
    db: Any,
    invoice_id: str,
    *,
    enrollment_id: str,
    cents: int = 6_000,
    period: str = "2026-11",
    status: str = "open",
    balance_due_cents: int | None = None,
) -> None:
    await MongoBillingLedgerRepository(db).create_invoice(
        LedgerInvoice(
            invoice_id=invoice_id,
            academy_id=ACAD,
            parent_id="parent-1",
            enrollment_id=enrollment_id,
            period=period,
            status=status,  # type: ignore[arg-type]
            subtotal_cents=cents,
            total_cents=cents,
            balance_due_cents=cents if balance_due_cents is None else balance_due_cents,
            currency="usd",
            due_date=date(2026, 11, 8),
            created_at=NOW,
            updated_at=NOW,
        ),
        lines=[
            InvoiceLine(
                line_id=f"{invoice_id}-0",
                academy_id=ACAD,
                invoice_id=invoice_id,
                line_type="tuition",
                description="tuition",
                quantity=1,
                unit_amount_cents=cents,
                amount_cents=cents,
                created_at=NOW,
            )
        ],
        idempotency_key=f"seed:{invoice_id}",
    )


def _setter(db: Any, voided: list[str], *, period: str = "2026-11") -> SetEnrollmentBilling:
    async def void_invoice(*, invoice_id: str, reason: str, actor_id: str | None = None) -> None:
        voided.append(invoice_id)
        await db["invoices"].update_one(
            {"invoice_id": invoice_id}, {"$set": {"status": "void", "void_reason": reason}}
        )

    return SetEnrollmentBilling(
        store=MongoEnrollmentNotBilledStore(db),
        invoices=MongoBillingLedgerRepository(db),
        void_invoice=void_invoice,
        billing_month=_Month(period),
        audit=RecordMoneySettingChange(audit=MongoBillingAuditLogRepository(db), now=lambda: NOW),
        clock=lambda: NOW,
    )


async def _payroll(db: Any) -> Any:
    return await ComputeCoachPayout(
        occurrences=MongoPayableOccurrenceQuery(
            db, tuition=MongoInvoicedTuitionReadModel(db), academy_timezone=_central
        ),
        rates=MongoCoachRateLookup(db),
    ).execute(coach_id="coach-1", academy_id=ACAD, period_start=NOV_START, period_end=NOV_END)


async def _two_november_classes(db: Any) -> None:
    await db["coach_rates"].insert_one(
        {
            "academy_id": ACAD,
            "rate_id": "rate-1",
            "coach_id": "coach-1",
            "rate_type": "percentage_of_expected_revenue",
            "percentage": 30.0,
            "effective_from": datetime(2026, 9, 1, tzinfo=UTC),
            "status": "active",
        }
    )
    await db["session_occurrences"].insert_many(
        [
            {
                "academy_id": ACAD,
                "occurrence_id": f"occ-{index}",
                "session_id": "sess-1",
                "start_at": start,
                "end_at": start + timedelta(hours=1),
                "status": "completed",
                "scheduled_coach_id": "coach-1",
                "is_payable": True,
            }
            for index, start in enumerate(
                [datetime(2026, 11, 3, 23, tzinfo=UTC), datetime(2026, 11, 10, 23, tzinfo=UTC)]
            )
        ]
    )


def _missing_invoice_warnings(statement: Any) -> list[Any]:
    return [
        w
        for w in statement.payout_warnings
        if w.reason == "missing_invoiced_tuition_for_percent_revenue"
    ]


async def test_owner_children_class_blocked_payroll_until_marked_not_billed(real_db, acad) -> None:
    """The reported shape: a class whose only children are the owner's two, one
    imported NoCharge, the other billed by hand with its invoice voided."""
    await _two_november_classes(real_db)
    await _enroll(real_db, "enr-a", student_id="kid-a", billing_type="NoCharge")
    await _enroll(real_db, "enr-b", student_id="kid-b", billing_type="Manual")
    await _invoice(real_db, "inv-b", enrollment_id="enr-b", status="void")

    before = await _payroll(real_db)
    assert before.total_minor == 0
    assert len(_missing_invoice_warnings(before)) == 2

    await _setter(real_db, []).execute(
        ACAD,
        SetEnrollmentBillingCommand(
            enrollment_id="enr-b", not_billed=True, reason="owner_child", actor_id="owner-1"
        ),
    )
    after = await _payroll(real_db)
    assert after.total_minor == 0
    assert _missing_invoice_warnings(after) == []
    assert after.unpaid_occurrence_ids == []


async def test_one_billed_child_without_an_invoice_still_warns(real_db, acad) -> None:
    await _two_november_classes(real_db)
    await _enroll(real_db, "enr-a", student_id="kid-a", billing_type="nocharge")
    await _enroll(real_db, "enr-b", student_id="kid-b")

    statement = await _payroll(real_db)
    assert len(_missing_invoice_warnings(statement)) == 2


async def test_not_billed_is_audited_voids_open_invoices_and_keeps_paid_ones(real_db, acad) -> None:
    await _enroll(real_db, "enr-1", student_id="kid-1", billing_type="Manual")
    await _invoice(real_db, "inv-oct", enrollment_id="enr-1", period="2026-10")
    await _invoice(
        real_db, "inv-nov", enrollment_id="enr-1", status="partially_paid", balance_due_cents=1
    )
    voided: list[str] = []

    result = await _setter(real_db, voided).execute(
        ACAD,
        SetEnrollmentBillingCommand(
            enrollment_id="enr-1",
            not_billed=True,
            reason="coach_child",
            note="  coach's daughter  ",
            void_open_invoices=True,
            actor_id="owner-1",
        ),
    )

    assert result.voided_invoice_ids == ["inv-oct"]
    assert voided == ["inv-oct"]
    doc = await real_db["enrollments"].find_one({"enrollment_id": "enr-1"})
    assert doc["billing_type"] == "NoCharge"
    assert doc["not_billed_reason"] == "coach_child"
    assert doc["not_billed_note"] == "coach's daughter"
    assert doc["billing_type_before_not_billed"] == "Manual"
    audit = await real_db["billing_audit_log"].find_one({"action": "enrollment_billing_changed"})
    assert audit["actor_id"] == "owner-1"
    assert audit["parent_id"] == "parent-1"
    assert audit["before"]["billing_type"] == "Manual"
    assert audit["after"]["billing_type"] == "NoCharge"
    assert audit["after"]["voided_invoice_ids"] == ["inv-oct"]


async def test_monthly_run_skips_not_billed_and_start_billing_waits_a_month(real_db, acad) -> None:
    await real_db["sessions"].insert_one(
        {
            "academy_id": ACAD,
            "session_id": "sess-1",
            "title": "Juniors",
            "monthly_price_cents": 10_000,
            "days_of_week": ["Tue"],
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "status": "active",
        }
    )
    await real_db["students"].insert_one(
        {"academy_id": ACAD, "student_id": "kid-1", "parent_id": "parent-1", "full_name": "Kid"}
    )
    await _enroll(real_db, "enr-1", student_id="kid-1", billing_type="Manual")
    setter = _setter(real_db, [])
    await setter.execute(
        ACAD,
        SetEnrollmentBillingCommand(
            enrollment_id="enr-1", not_billed=True, reason="owner_child", actor_id="owner-1"
        ),
    )

    def run(at: datetime) -> MongoPaymentRepository:
        return MongoPaymentRepository(
            real_db, clock=lambda: at, ledger_repo=MongoBillingLedgerRepository(real_db)
        )

    assert (await run(NOW).generate_monthly_payments("2026-11")).created == 0

    started = await setter.execute(
        ACAD,
        SetEnrollmentBillingCommand(enrollment_id="enr-1", not_billed=False, actor_id="owner-1"),
    )
    assert started.billing_type == "Manual"
    assert started.skipped_period == "2026-11"
    doc = await real_db["enrollments"].find_one({"enrollment_id": "enr-1"})
    assert "not_billed_reason" not in doc

    # Re-running November still bills nothing; December bills the restored type.
    assert (await run(NOW).generate_monthly_payments("2026-11")).created == 0
    december = datetime(2026, 12, 1, 14, tzinfo=UTC)
    assert (await run(december).generate_monthly_payments("2026-12")).created == 1


async def test_headcounts_leave_out_children_with_only_not_billed_classes(real_db, acad) -> None:
    for student_id in ("kid-billed", "kid-free", "kid-mixed"):
        await real_db["students"].insert_one(
            {"academy_id": ACAD, "student_id": student_id, "parent_id": "parent-1"}
        )
    await _enroll(real_db, "enr-1", student_id="kid-billed")
    await _enroll(real_db, "enr-2", student_id="kid-free", billing_type="NoCharge")
    await _enroll(real_db, "enr-3", student_id="kid-mixed", billing_type="NoCharge")
    await _enroll(real_db, "enr-4", student_id="kid-mixed", session_id="sess-2")

    repo = MongoStudentRepository(real_db)
    assert await repo.not_billed_student_ids(ACAD, None) == {"kid-free"}
    snapshots = await repo.lifecycle_snapshots(
        academy_id=ACAD, student_ids=["kid-billed", "kid-free", "kid-mixed"]
    )
    assert {sid: snap.not_billed for sid, snap in snapshots.items()} == {
        "kid-billed": False,
        "kid-free": True,
        "kid-mixed": False,
    }
    # The child keeps its label (still attending); only the headcount moves.
    assert snapshots["kid-free"].state == snapshots["kid-billed"].state

    page = await repo.list_admin_students(search=None, limit=25, cursor=None)
    assert page.lifecycle_counts.get("not_billed") == 1
    assert sum(page.lifecycle_counts.values()) == 3
    assert {s.student_id: s.not_billed for s in page.students}["kid-free"] is True


async def test_projected_income_leaves_out_not_billed_enrollments(real_db, acad) -> None:
    await real_db["sessions"].insert_one(
        {"academy_id": ACAD, "session_id": "sess-1", "title": "Juniors", "amount_cents": 10_000}
    )
    await _enroll(real_db, "enr-1", student_id="kid-1")
    await _enroll(real_db, "enr-2", student_id="kid-2", billing_type="NoCharge")

    report = await make_projected_income_report(real_db)("2026-11")  # type: ignore[operator]

    assert report["enrollment_count"] == 1
    assert report["total_cents"] == 10_000
    assert report["not_billed_enrollment_count"] == 1


@pytest.mark.parametrize("then_start_billing", [False, True])
async def test_marking_today_never_hides_an_older_months_missing_invoice(
    real_db, acad, then_start_billing: bool
) -> None:
    await _two_november_classes(real_db)
    await real_db["session_occurrences"].update_many(
        {},
        [
            {
                "$set": {
                    "start_at": {
                        "$dateSubtract": {"startDate": "$start_at", "unit": "day", "amount": 28}
                    }
                }
            }
        ],
    )
    await _enroll(real_db, "enr-b", student_id="kid-b", billing_type="Manual")
    await _setter(real_db, []).execute(
        ACAD,
        SetEnrollmentBillingCommand(
            enrollment_id="enr-b", not_billed=True, reason="owner_child", actor_id="owner-1"
        ),
    )
    if then_start_billing:
        # Billing started after the mark: October, before both, was still billed.
        await _setter(real_db, []).execute(
            ACAD,
            SetEnrollmentBillingCommand(
                enrollment_id="enr-b", not_billed=False, actor_id="owner-1"
            ),
        )

    october = await ComputeCoachPayout(
        occurrences=MongoPayableOccurrenceQuery(
            real_db, tuition=MongoInvoicedTuitionReadModel(real_db), academy_timezone=_central
        ),
        rates=MongoCoachRateLookup(real_db),
    ).execute(
        coach_id="coach-1",
        academy_id=ACAD,
        period_start=datetime(2026, 10, 1, 5, tzinfo=UTC),
        period_end=NOV_START,
    )
    assert len(_missing_invoice_warnings(october)) == 2


async def test_a_billed_child_who_left_mid_month_keeps_the_warning(real_db, acad) -> None:
    await _two_november_classes(real_db)
    await _enroll(real_db, "enr-a", student_id="kid-a", billing_type="NoCharge")
    await _enroll(real_db, "enr-b", student_id="kid-b", status="dropped")
    await real_db["enrollments"].update_one(
        {"enrollment_id": "enr-b"}, {"$set": {"updated_at": datetime(2026, 11, 28, tzinfo=UTC)}}
    )

    assert len(_missing_invoice_warnings(await _payroll(real_db))) == 2


async def test_a_billed_child_who_joined_after_the_month_does_not_warn(real_db, acad) -> None:
    await _two_november_classes(real_db)
    await _enroll(real_db, "enr-a", student_id="kid-a", billing_type="NoCharge")
    await _enroll(real_db, "enr-c", student_id="kid-c")
    await real_db["enrollments"].update_one(
        {"enrollment_id": "enr-c"}, {"$set": {"created_at": datetime(2026, 12, 3, tzinfo=UTC)}}
    )

    assert _missing_invoice_warnings(await _payroll(real_db)) == []


async def test_start_billing_does_not_turn_skipped_months_into_warnings(real_db, acad) -> None:
    await _two_november_classes(real_db)
    await _enroll(real_db, "enr-a", student_id="kid-a", billing_type="NoCharge")
    await _setter(real_db, []).execute(
        ACAD,
        SetEnrollmentBillingCommand(enrollment_id="enr-a", not_billed=False, actor_id="owner-1"),
    )

    statement = await _payroll(real_db)
    assert _missing_invoice_warnings(statement) == []
    assert statement.total_minor == 0
