"""Idempotency of admin money-movement composition closures.

These exercise the real ``compose_admin`` closures (not route fakes) against an
in-process Mongo + the production ``MongoIdempotencyStore`` and a fake Stripe.
A retry of the SAME operation must not move money twice nor double-count the
invoice/ledger projections.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.tenancy.context import tenant_scope

ACAD = "acad"  # pinned via env in the admin_db fixture so compose_admin resolves it
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


class _FakeOutbox:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def append(self, event: object) -> None:
        self.events.append(event)


@pytest.fixture
def admin_db(monkeypatch):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    monkeypatch.delenv("V2_PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.delenv("PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.setenv("V2_DEFAULT_ACADEMY_ID", ACAD)
    monkeypatch.setenv("DEFAULT_ACADEMY_ID", ACAD)
    get_settings.cache_clear()
    try:
        client = mongomock_motor.AsyncMongoMockClient()
        yield client["test_db"]
    finally:
        get_settings.cache_clear()


def _use_cases(db, *, stripe=None):
    return compose_admin(
        db,
        outbox=_FakeOutbox(),  # type: ignore[arg-type]
        idempotency_store=MongoIdempotencyStore(db),
        stripe=stripe or FakeStripeGateway(),
    )


async def _seed_refundable_invoice(db) -> None:
    await db["invoices"].insert_one(
        {
            "invoice_id": "inv-r",
            "academy_id": ACAD,
            "parent_id": "parent-1",
            "student_id": "student-1",
            "enrollment_id": "enroll-1",
            "period": "2026-06",
            "status": "paid",
            "subtotal_cents": 20_000,
            "discount_cents": 0,
            "total_cents": 20_000,
            "balance_due_cents": 0,
            "refunded_cents": 0,
            "currency": "usd",
            "due_date": date(2026, 6, 30).isoformat(),
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    await db["payments"].insert_one(
        {
            "payment_id": "pay-r",
            "academy_id": ACAD,
            "parent_id": "parent-1",
            "session_id": "sess-1",
            "stripe_payment_intent_id": "pi_pay-r",
            "amount_cents": 20_000,
            "currency": "usd",
            "status": "succeeded",
            "refunded_cents": 0,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    await db["payment_allocations"].insert_one(
        {
            "allocation_id": "alloc-r",
            "academy_id": ACAD,
            "payment_id": "pay-r",
            "invoice_id": "inv-r",
            "amount_cents": 20_000,
            "created_at": NOW,
        }
    )


@pytest.mark.asyncio
async def test_issue_invoice_refund_retry_does_not_double_count(admin_db) -> None:
    await _seed_refundable_invoice(admin_db)
    admin = _use_cases(admin_db)

    with tenant_scope(ACAD):
        first = await admin.issue_invoice_refund(
            invoice_id="inv-r", amount_cents=5_000, reason="duplicate", actor_id="admin-1"
        )
        second = await admin.issue_invoice_refund(
            invoice_id="inv-r", amount_cents=5_000, reason="duplicate", actor_id="admin-1"
        )
        invoice = await admin_db["invoices"].find_one({"academy_id": ACAD, "invoice_id": "inv-r"})
        payment = await admin_db["payments"].find_one({"academy_id": ACAD, "payment_id": "pay-r"})
        audit_count = await admin_db["billing_audit_log"].count_documents(
            {"academy_id": ACAD, "invoice_id": "inv-r"}
        )

    assert first == second  # the retry replays the original result
    # Money moved exactly once.
    assert invoice is not None and invoice["refunded_cents"] == 5_000
    assert payment is not None and payment["refunded_cents"] == 5_000
    assert audit_count == 1


async def _seed_open_invoice(db) -> None:
    await db["invoices"].insert_one(
        {
            "invoice_id": "inv-m",
            "academy_id": ACAD,
            "parent_id": "parent-1",
            "student_id": "student-1",
            "enrollment_id": "enroll-1",
            "period": "2026-06",
            "status": "open",
            "subtotal_cents": 7_000,
            "discount_cents": 0,
            "total_cents": 7_000,
            "balance_due_cents": 7_000,
            "refunded_cents": 0,
            "currency": "usd",
            "due_date": date(2026, 6, 30).isoformat(),
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


@pytest.mark.asyncio
async def test_record_manual_payment_retry_does_not_double_record(admin_db) -> None:
    await _seed_open_invoice(admin_db)
    admin = _use_cases(admin_db)

    with tenant_scope(ACAD):
        first = await admin.record_manual_payment(
            invoice_id="inv-m",
            amount_cents=2_500,
            payment_method="check",
            reference_number="1001",
            notes="Front desk payment",
            actor_id="admin-1",
        )
        second = await admin.record_manual_payment(
            invoice_id="inv-m",
            amount_cents=2_500,
            payment_method="check",
            reference_number="1001",
            notes="Front desk payment",
            actor_id="admin-1",
        )
        invoice = await admin_db["invoices"].find_one({"academy_id": ACAD, "invoice_id": "inv-m"})
        payment_count = await admin_db["ledger_payments"].count_documents({"academy_id": ACAD})
        audit_count = await admin_db["billing_audit_log"].count_documents(
            {"academy_id": ACAD, "invoice_id": "inv-m"}
        )

    assert first == second  # the retry replays the original result
    # Money recorded exactly once.
    assert payment_count == 1
    assert invoice is not None and invoice["balance_due_cents"] == 4_500
    assert audit_count == 1


@pytest.mark.asyncio
async def test_billing_setup_autopay_retry_converges_state_and_audit(admin_db) -> None:
    await admin_db["billing_audit_log"].create_index(
        [("academy_id", 1), ("audit_id", 1)], unique=True
    )
    await admin_db["parent_billing_customers"].insert_one(
        {
            "academy_id": ACAD,
            "parent_id": "parent-1",
            "payment_method_label": "Visa",
            "payment_method_last4": "4242",
        }
    )
    await admin_db["student_billing_enrollments"].insert_one(
        {
            "academy_id": ACAD,
            "enrollment_id": "enroll-paused",
            "parent_id": "parent-1",
            "student_id": "student-1",
            "session_type_id": "session-type-1",
            "billing_start_date": NOW,
            "status": "active",
            "autopay_enrollment_status": "paused",
            "enrolled_at": NOW,
            "updated_at": NOW,
        }
    )
    admin = _use_cases(admin_db)

    with tenant_scope(ACAD):
        first = await admin.enable_billing_setup_autopay(
            parent_id="parent-1", actor_id="admin-1", request_id="request-autopay-0001"
        )
        second = await admin.enable_billing_setup_autopay(
            parent_id="parent-1", actor_id="admin-1", request_id="request-autopay-0001"
        )
        enrollment = await admin_db["student_billing_enrollments"].find_one(
            {"academy_id": ACAD, "enrollment_id": "enroll-paused"}
        )
        audits = await admin_db["billing_audit_log"].count_documents(
            {"academy_id": ACAD, "action": "autopay_resumed"}
        )

    assert first == second == {"eligible_count": 1, "enabled_count": 1}
    assert enrollment is not None
    assert enrollment["autopay_enrollment_status"] == "active"
    assert enrollment["billing_setup_resume_operation_id"].endswith("parent-1:request-autopay-0001")
    assert audits == 1

    await admin_db["parent_billing_customers"].delete_one(
        {"academy_id": ACAD, "parent_id": "parent-1"}
    )
    with tenant_scope(ACAD), pytest.raises(ValueError, match="no_saved_payment_method"):
        await admin.enable_billing_setup_autopay(
            parent_id="parent-1", actor_id="admin-1", request_id="request-autopay-0001"
        )


class _BillingSetupStripe(FakeStripeGateway):
    async def get_default_payment_method(self, *, academy_id: str, parent_id: str):
        return "cus-parent-1", "pm-parent-1"


@pytest.mark.asyncio
async def test_billing_setup_charge_claim_and_result_are_replayable(admin_db) -> None:
    stripe = _BillingSetupStripe()
    await admin_db["billing_audit_log"].create_index(
        [("academy_id", 1), ("audit_id", 1)], unique=True
    )
    await admin_db["parent_billing_customers"].insert_one(
        {
            "academy_id": ACAD,
            "parent_id": "parent-1",
            "payment_method_label": "Visa",
            "payment_method_last4": "4242",
        }
    )
    await admin_db["academy_connected_accounts"].insert_one(
        {
            "academy_id": ACAD,
            "stripe_account_id": "acct-ready",
            "status": "active",
            "capabilities": {},
            "charges_enabled": True,
            "payouts_enabled": True,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    await admin_db["student_billing_enrollments"].insert_one(
        {
            "academy_id": ACAD,
            "enrollment_id": "enroll-charge",
            "parent_id": "parent-1",
            "student_id": "student-1",
            "session_type_id": "session-type-1",
            "billing_start_date": NOW,
            "status": "active",
            "autopay_enrollment_status": "active",
            "enrolled_at": NOW,
            "updated_at": NOW,
        }
    )
    await admin_db["invoices"].insert_one(
        {
            "academy_id": ACAD,
            "invoice_id": "inv-charge",
            "parent_id": "parent-1",
            "student_id": "student-1",
            "enrollment_id": "enroll-charge",
            "period": "2026-07",
            "status": "open",
            "subtotal_cents": 5000,
            "discount_cents": 0,
            "total_cents": 5000,
            "balance_due_cents": 5000,
            "currency": "usd",
            "due_date": date(2026, 7, 31).isoformat(),
            "version": 0,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    admin = _use_cases(admin_db, stripe=stripe)

    with tenant_scope(ACAD):
        first = await admin.charge_billing_setup_balance(
            parent_id="parent-1",
            invoice_id="inv-charge",
            expected_amount_cents=5000,
            request_id="request-charge-0001",
            actor_id="admin-1",
        )
        second = await admin.charge_billing_setup_balance(
            parent_id="parent-1",
            invoice_id="inv-charge",
            expected_amount_cents=5000,
            request_id="request-charge-0001",
            actor_id="admin-1",
        )

    assert first == second
    assert first["success"] is True
    assert first["charged_amount_cents"] == 5000
    assert len(stripe.off_session_payment_intents) == 1
    assert await admin_db["ledger_payments"].count_documents({"academy_id": ACAD}) == 1
    assert (
        await admin_db["billing_audit_log"].count_documents(
            {"academy_id": ACAD, "action": "admin_charge_initiated"}
        )
        == 1
    )


class _BillingSetupProcessingStripe(_BillingSetupStripe):
    async def create_off_session_payment_intent(self, **kwargs):
        pi_id, _, _ = await super().create_off_session_payment_intent(**kwargs)
        return pi_id, "processing", None


@pytest.mark.asyncio
async def test_billing_setup_processing_audit_records_attempted_not_received_amount(
    admin_db,
) -> None:
    stripe = _BillingSetupProcessingStripe()
    await admin_db["billing_audit_log"].create_index(
        [("academy_id", 1), ("audit_id", 1)], unique=True
    )
    await admin_db["parent_billing_customers"].insert_one(
        {
            "academy_id": ACAD,
            "parent_id": "parent-1",
            "payment_method_label": "Bank",
            "payment_method_last4": "6789",
        }
    )
    await admin_db["academy_connected_accounts"].insert_one(
        {
            "academy_id": ACAD,
            "stripe_account_id": "acct-ready",
            "status": "active",
            "capabilities": {},
            "charges_enabled": True,
            "payouts_enabled": True,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    await admin_db["student_billing_enrollments"].insert_one(
        {
            "academy_id": ACAD,
            "enrollment_id": "enroll-processing",
            "parent_id": "parent-1",
            "student_id": "student-1",
            "session_type_id": "session-type-1",
            "billing_start_date": NOW,
            "status": "active",
            "autopay_enrollment_status": "active",
            "enrolled_at": NOW,
            "updated_at": NOW,
        }
    )
    await admin_db["invoices"].insert_one(
        {
            "academy_id": ACAD,
            "invoice_id": "inv-processing",
            "parent_id": "parent-1",
            "student_id": "student-1",
            "enrollment_id": "enroll-processing",
            "period": "2026-07",
            "status": "open",
            "subtotal_cents": 5000,
            "discount_cents": 0,
            "total_cents": 5000,
            "balance_due_cents": 5000,
            "currency": "usd",
            "due_date": date(2026, 7, 31).isoformat(),
            "version": 0,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    admin = _use_cases(admin_db, stripe=stripe)

    with tenant_scope(ACAD):
        result = await admin.charge_billing_setup_balance(
            parent_id="parent-1",
            invoice_id="inv-processing",
            expected_amount_cents=5000,
            request_id="request-processing-0001",
            actor_id="admin-1",
        )
        audit = await admin_db["billing_audit_log"].find_one(
            {"academy_id": ACAD, "action": "admin_charge_initiated"}
        )

    assert result["processing"] is True
    assert result["charged_amount_cents"] == 0
    assert result["attempted_amount_cents"] == 5000
    assert audit is not None and audit["after"]["attempted_amount_cents"] == 5000
