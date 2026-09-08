"""Issue #651 end-to-end through composition with mongomock: generator skips
paused enrollments, dues follow-up skips autopay families, void suppresses the
ladder, and the real EnrollmentBillingSync adapter voids future invoices."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.composition.lifecycle_billing import compose_enrollment_billing_sync
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY = "acad-651"
NOW = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


class _NoopStripe:
    pass


def _admin(db: Any):
    return compose_admin(
        db,
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=_NoopStripe(),  # type: ignore[arg-type]
    )


@pytest.fixture
def mongo_db(monkeypatch):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    monkeypatch.delenv("V2_DEFAULT_ACADEMY_ID", raising=False)
    monkeypatch.delenv("DEFAULT_ACADEMY_ID", raising=False)
    get_settings.cache_clear()
    try:
        yield mongomock_motor.AsyncMongoMockClient()["test_db"]
    finally:
        get_settings.cache_clear()


def _invoice_doc(invoice_id: str, *, enrollment_id: str, period: str, status: str = "open") -> dict:
    return {
        "academy_id": ACADEMY,
        "invoice_id": invoice_id,
        "parent_id": "parent-1",
        "student_id": "stu-1",
        "enrollment_id": enrollment_id,
        "period": period,
        "status": status,
        "subtotal_cents": 7000,
        "discount_cents": 0,
        "total_cents": 7000,
        "balance_due_cents": 0 if status == "paid" else 7000,
        "currency": "usd",
        "due_date": datetime(2026, 9, 8, tzinfo=UTC),
        "created_at": NOW,
        "updated_at": NOW,
    }


@pytest.mark.asyncio
async def test_adapter_voids_future_invoices_disables_autopay_and_suppresses_ladder(
    mongo_db,
) -> None:
    await mongo_db["academies"].insert_one({"academy_id": ACADEMY, "timezone": "America/Chicago"})
    await mongo_db["invoices"].insert_many(
        [
            _invoice_doc("inv-sep", enrollment_id="enr-1", period="2026-09"),
            _invoice_doc("inv-oct", enrollment_id="enr-1", period="2026-10"),
        ]
    )
    await mongo_db["student_billing_enrollments"].insert_one(
        {
            "academy_id": ACADEMY,
            "enrollment_id": "enr-1",
            "student_id": "stu-1",
            "status": "active",
            "autopay_enrollment_status": "active",
            "enrolled_at": NOW,
            "updated_at": NOW,
        }
    )
    await mongo_db["dunning_states"].insert_one(
        {
            "academy_id": ACADEMY,
            "invoice_id": "inv-oct",
            "parent_id": "parent-1",
            "enrollment_id": "enr-1",
            "status": "active",
            "attempt_count": 0,
            "next_attempt_at": NOW,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )

    with tenant_scope(ACADEMY):
        outcome = await compose_enrollment_billing_sync(mongo_db).apply(
            enrollment_id="enr-1",
            transition="cancelled",
            effective_at=datetime(2026, 9, 15, tzinfo=UTC),
            reason="moving",
            actor_id="admin-1",
        )

    assert outcome["voided_invoice_ids"] == ["inv-oct"]
    assert outcome["autopay_applied"] is True
    sep = await mongo_db["invoices"].find_one({"invoice_id": "inv-sep"})
    oct_ = await mongo_db["invoices"].find_one({"invoice_id": "inv-oct"})
    assert sep["status"] == "open"
    assert oct_["status"] == "void" and oct_["void_reason"] == "moving"
    enrollment = await mongo_db["student_billing_enrollments"].find_one({"enrollment_id": "enr-1"})
    assert enrollment["autopay_enrollment_status"] == "disabled"
    ladder = await mongo_db["dunning_states"].find_one({"invoice_id": "inv-oct"})
    assert ladder["status"] == "suppressed"


@pytest.mark.asyncio
async def test_void_invoice_suppresses_its_ladder(mongo_db) -> None:
    await mongo_db["invoices"].insert_one(
        _invoice_doc("inv-x", enrollment_id="enr-x", period="2026-10")
    )
    await mongo_db["dunning_states"].insert_one(
        {
            "academy_id": ACADEMY,
            "invoice_id": "inv-x",
            "parent_id": "parent-1",
            "enrollment_id": "enr-x",
            "status": "active",
            "attempt_count": 0,
            "next_attempt_at": NOW,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    admin = _admin(mongo_db)
    with tenant_scope(ACADEMY):
        await admin.void_billing_invoice(invoice_id="inv-x", reason="duplicate")
    invoice = await mongo_db["invoices"].find_one({"invoice_id": "inv-x"})
    assert invoice["status"] == "void" and invoice["void_reason"] == "duplicate"
    ladder = await mongo_db["dunning_states"].find_one({"invoice_id": "inv-x"})
    assert ladder["status"] == "suppressed"


@pytest.mark.asyncio
async def test_dues_followup_skips_autopay_active_families(mongo_db) -> None:
    await mongo_db["invoices"].insert_many(
        [
            {
                **_invoice_doc("inv-auto", enrollment_id="enr-auto", period="2026-09"),
                "parent_id": "parent-auto",
            },
            {
                **_invoice_doc("inv-manual", enrollment_id="enr-manual", period="2026-09"),
                "parent_id": "parent-manual",
            },
        ]
    )
    await mongo_db["student_billing_enrollments"].insert_many(
        [
            {
                "academy_id": ACADEMY,
                "enrollment_id": "enr-auto",
                "student_id": "s",
                "status": "active",
                "autopay_enrollment_status": "active",
                "enrolled_at": NOW,
                "updated_at": NOW,
            },
            {
                "academy_id": ACADEMY,
                "enrollment_id": "enr-manual",
                "student_id": "s",
                "status": "active",
                "autopay_enrollment_status": "offered",
                "enrolled_at": NOW,
                "updated_at": NOW,
            },
        ]
    )
    admin = _admin(mongo_db)
    with tenant_scope(ACADEMY):
        rows = await admin.list_dues_followup()
    assert [r["parent_id"] for r in rows] == ["parent-manual"]


@pytest.mark.asyncio
async def test_monthly_generation_never_invoices_a_paused_enrollment(mongo_db) -> None:
    await mongo_db["sessions"].insert_one(
        {
            "academy_id": ACADEMY,
            "session_id": "sess-1",
            "title": "Juniors",
            "status": "active",
            "monthly_fee_cents": 7000,
            "capacity": 10,
            "created_at": NOW,
        }
    )
    await mongo_db["students"].insert_one(
        {
            "academy_id": ACADEMY,
            "student_id": "stu-p",
            "full_name": "Paused Kid",
            "parent_id": "parent-p",
        }
    )
    await mongo_db["enrollments"].insert_one(
        {
            "academy_id": ACADEMY,
            "enrollment_id": "enr-p",
            "session_id": "sess-1",
            "student_id": "stu-p",
            "status": "paused",
            "created_at": NOW,
        }
    )
    admin = _admin(mongo_db)
    with tenant_scope(ACADEMY):
        result = await admin.generate_monthly_payments.execute(
            admin.generate_monthly_payments.__class__.__init__.__annotations__
            and __import__(
                "backend.v2.contexts.billing.application.use_cases.admin_payment_ops",
                fromlist=["GenerateMonthlyPaymentsCommand"],
            ).GenerateMonthlyPaymentsCommand(period="2026-10")
        )
    assert await mongo_db["invoices"].count_documents({"enrollment_id": "enr-p"}) == 0
    skipped = [d for d in result.skipped_details if d.enrollment_id == "enr-p"]
    assert skipped and skipped[0].reason_code == "enrollment_paused"
