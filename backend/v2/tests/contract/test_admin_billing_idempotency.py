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


def _use_cases(db):
    return compose_admin(
        db,
        outbox=_FakeOutbox(),  # type: ignore[arg-type]
        idempotency_store=MongoIdempotencyStore(db),
        stripe=FakeStripeGateway(),
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
