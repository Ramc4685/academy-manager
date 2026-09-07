"""Issue #669: ``ApplyEnrollmentMove`` against the real Mongo repositories.

Uses the real ledger, credit ledger, idempotency store and the
``sessions``-backed schedule reader on mongomock, so the line upsert,
``create_invoice`` idempotency and credit persistence are the production ones.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.apply_enrollment_move import (
    MOVE_CREDIT_TYPE,
    MOVE_LINE_TYPE,
    MOVE_SOURCE_TYPE,
    ApplyEnrollmentMove,
    ApplyEnrollmentMoveCommand,
)
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_move_schedule_reader import (
    MongoMoveScheduleReader,
)
from backend.v2.contexts.billing.infrastructure.mongo_tuition_discount_repo import (
    MongoTuitionDiscountRepository,
)
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore

NOW = datetime(2026, 9, 9, 15, 0, tzinfo=UTC)
EFFECTIVE = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)


async def _seed_session(db, acad: str, session_id: str, *, price: int, day: str) -> None:
    await db["sessions"].insert_one(
        {
            "session_id": session_id,
            "academy_id": acad,
            "title": session_id,
            "timezone": "America/Chicago",
            "amount_cents": price,
            "start_date": "2026-08-01",
            "end_date": "2026-12-31",
            "days_of_week": [day],
            "start_time": "18:00",
            "end_time": "19:00",
            "status": "active",
        }
    )


async def _seed_invoice(
    ledger: MongoBillingLedgerRepository, acad: str, *, status: str = "open"
) -> LedgerInvoice:
    invoice = LedgerInvoice(
        invoice_id="inv-enr-1-2026-09",
        academy_id=acad,
        parent_id="par-1",
        student_id="stu-1",
        enrollment_id="enr-1",
        period="2026-09",
        status=status,  # type: ignore[arg-type]
        subtotal_cents=8000,
        total_cents=8000,
        balance_due_cents=0 if status == "paid" else 8000,
        due_date=date(2026, 9, 8),
        created_at=NOW,
        updated_at=NOW,
    )
    line = InvoiceLine(
        line_id="line-tuition-sep",
        academy_id=acad,
        invoice_id=invoice.invoice_id,
        line_type="tuition",
        description="September tuition",
        quantity=1,
        unit_amount_cents=8000,
        amount_cents=8000,
        created_at=NOW,
    )
    return await ledger.create_invoice(
        invoice, lines=[line], idempotency_key="monthly:enr-1:2026-09"
    )


async def _tz() -> str | None:
    return "America/Chicago"


def _use_case(db) -> ApplyEnrollmentMove:
    return ApplyEnrollmentMove(
        ledger=MongoBillingLedgerRepository(db),
        credits=MongoCreditLedgerRepository(db),
        schedules=MongoMoveScheduleReader(db),
        discounts=MongoTuitionDiscountRepository(db),
        idempotency_store=MongoIdempotencyStore(db),
        academy_timezone=_tz,
        clock=lambda: NOW,
    )


def _cmd(**overrides) -> ApplyEnrollmentMoveCommand:
    base = {
        "enrollment_id": "enr-1",
        "from_session_id": "sess-a",
        "to_session_id": "sess-b",
        "effective_at": EFFECTIVE,
        "reason": "schedule change",
        "actor_id": "admin-1",
    }
    base.update(overrides)
    return ApplyEnrollmentMoveCommand(**base)


@pytest.mark.asyncio
async def test_move_to_dearer_session_adds_line_to_open_invoice_once(db, acad) -> None:
    # Saturdays in Sept 2026: 5, 12, 19, 26 → 3 of 4 remain after Sept 10.
    await _seed_session(db, acad, "sess-a", price=8000, day="Sat")
    await _seed_session(db, acad, "sess-b", price=12000, day="Sun")
    ledger = MongoBillingLedgerRepository(db)
    await _seed_invoice(ledger, acad)

    first = await _use_case(db).execute(_cmd())
    second = await _use_case(db).execute(_cmd())

    assert first.outcome == "debited"
    assert first.delta_cents == 3000
    assert second == first
    invoice = await ledger.get_invoice("inv-enr-1-2026-09")
    assert invoice is not None
    assert invoice.total_cents == 11000
    assert invoice.balance_due_cents == 11000
    assert invoice.status == "open"
    lines = await ledger.get_lines_for_invoice(invoice.invoice_id)
    move_lines = [line for line in lines if line.line_type == MOVE_LINE_TYPE]
    assert len(move_lines) == 1
    assert move_lines[0].amount_cents == 3000
    assert move_lines[0].source_id == first.idempotency_key
    assert await db["account_credit_ledger"].count_documents({}) == 0
    # The key is tenant-scoped in the global idempotency store.
    assert acad in first.idempotency_key


@pytest.mark.asyncio
async def test_move_to_cheaper_session_credits_parent_ledger(db, acad) -> None:
    """A PAID period invoice cannot be reduced, so the money comes back as a
    credit. (An open, unpaid one is reduced in place — see the test below.)"""
    await _seed_session(db, acad, "sess-a", price=12000, day="Sat")
    await _seed_session(db, acad, "sess-b", price=8000, day="Sun")
    ledger = MongoBillingLedgerRepository(db)
    await _seed_invoice(ledger, acad, status="paid")
    credits = MongoCreditLedgerRepository(db)

    result = await _use_case(db).execute(_cmd())
    await _use_case(db).execute(_cmd())

    assert result.outcome == "credited"
    assert result.delta_cents == -3000
    assert await credits.balance_for_parent("par-1") == 3000
    docs = [doc async for doc in db["account_credit_ledger"].find({"academy_id": acad})]
    assert len(docs) == 1
    assert docs[0]["type"] == MOVE_CREDIT_TYPE
    assert docs[0]["source_type"] == MOVE_SOURCE_TYPE
    assert docs[0]["enrollment_id"] == "enr-1"
    invoice = await ledger.get_invoice("inv-enr-1-2026-09")
    assert invoice is not None and invoice.total_cents == 8000


@pytest.mark.asyncio
async def test_paid_invoice_gets_separate_open_adjustment_invoice(db, acad) -> None:
    await _seed_session(db, acad, "sess-a", price=8000, day="Sat")
    await _seed_session(db, acad, "sess-b", price=12000, day="Sun")
    ledger = MongoBillingLedgerRepository(db)
    await _seed_invoice(ledger, acad, status="paid")

    first = await _use_case(db).execute(_cmd())
    second = await _use_case(db).execute(_cmd())

    assert first.outcome == "adjustment_invoiced"
    assert second.invoice_id == first.invoice_id
    paid = await ledger.get_invoice("inv-enr-1-2026-09")
    assert paid is not None and paid.status == "paid" and paid.total_cents == 8000
    adjustments = [
        inv
        for inv in await ledger.list_invoices_for_enrollment("enr-1")
        if inv.source_type == MOVE_SOURCE_TYPE
    ]
    assert len(adjustments) == 1
    adjustment = adjustments[0]
    assert adjustment.status == "open"
    assert adjustment.balance_due_cents == 3000
    assert adjustment.period == "2026-09"
    # Shape the dunning worker's ``prepare_due_states`` query selects on.
    doc = await db["invoices"].find_one({"invoice_id": adjustment.invoice_id})
    assert doc is not None
    assert doc["enrollment_id"] == "enr-1"
    assert doc["status"] == "open"
    assert doc["idempotency_key"] == first.idempotency_key
    lines = await ledger.get_lines_for_invoice(adjustment.invoice_id)
    assert [line.amount_cents for line in lines] == [3000]


@pytest.mark.asyncio
async def test_no_invoice_for_period_is_a_noop(db, acad) -> None:
    await _seed_session(db, acad, "sess-a", price=8000, day="Sat")
    await _seed_session(db, acad, "sess-b", price=12000, day="Sun")

    result = await _use_case(db).execute(_cmd())

    assert result.outcome == "no_invoice"
    assert await db["invoices"].count_documents({}) == 0
    assert await db["account_credit_ledger"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_other_tenant_invoice_is_invisible(db, acad, other_acad) -> None:
    await _seed_session(db, other_acad, "sess-a", price=8000, day="Sat")
    await _seed_session(db, other_acad, "sess-b", price=12000, day="Sun")
    await _seed_invoice(MongoBillingLedgerRepository(db), other_acad)

    # ``other_acad`` is the active tenant here; a request for ``acad`` sees nothing.
    from backend.v2.shared.tenancy.context import _current as _tv

    token = _tv.set(acad)
    try:
        result = await _use_case(db).execute(_cmd())
    finally:
        _tv.reset(token)

    assert result.outcome == "no_invoice"


@pytest.mark.asyncio
async def test_move_to_cheaper_session_reduces_a_still_open_invoice(db, acad) -> None:
    """#669 review: autopay charges the invoice balance, so an open, unpaid
    invoice must come DOWN rather than leave the old amount to be charged."""
    await _seed_session(db, acad, "sess-a", price=12000, day="Sat")
    await _seed_session(db, acad, "sess-b", price=8000, day="Sun")
    ledger = MongoBillingLedgerRepository(db)
    await _seed_invoice(ledger, acad)

    result = await _use_case(db).execute(_cmd())

    assert result.outcome == "credited" and result.delta_cents == -3000
    invoice = await ledger.get_invoice("inv-enr-1-2026-09")
    assert invoice is not None
    assert invoice.total_cents == invoice.balance_due_cents == 5000
    assert await db["account_credit_ledger"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_delta_is_net_of_the_stored_tuition_discount(db, acad) -> None:
    await _seed_session(db, acad, "sess-a", price=8000, day="Sat")
    await _seed_session(db, acad, "sess-b", price=12000, day="Sun")
    ledger = MongoBillingLedgerRepository(db)
    await _seed_invoice(ledger, acad)
    await db["enrollment_discounts"].insert_one(
        {
            "discount_id": "disc-1",
            "academy_id": acad,
            "enrollment_id": "enr-1",
            "student_id": "stu-1",
            "category": "sibling",
            "kind": "percent",
            "percent_bps": 2000,
            "effective_start": "2026-01-01",
            "status": "active",
        }
    )

    result = await _use_case(db).execute(_cmd())

    # Gross the delta would be 3000; net of the 20% policy it is 2400.
    assert result.delta_cents == 2400


@pytest.mark.asyncio
async def test_a_session_without_a_schedule_refuses(db, acad) -> None:
    await db["sessions"].insert_one(
        {
            "session_id": "sess-a",
            "academy_id": acad,
            "title": "open ended",
            "timezone": "America/Chicago",
            "amount_cents": 8000,
            "status": "active",
        }
    )
    await _seed_session(db, acad, "sess-b", price=12000, day="Sun")
    ledger = MongoBillingLedgerRepository(db)
    await _seed_invoice(ledger, acad)

    result = await _use_case(db).execute(_cmd())

    assert result.outcome == "schedule_unavailable"
    invoice = await ledger.get_invoice("inv-enr-1-2026-09")
    assert invoice is not None and invoice.total_cents == 8000


@pytest.mark.asyncio
async def test_move_adjustment_is_not_mistaken_for_the_period_invoice(db, acad) -> None:
    """#669 review: the adjustment shares (enrollment_id, period) with the
    monthly invoice and is newer, so the generator's lookup must skip it."""
    from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import (
        MongoMonthlyBillingGenerator,
    )
    from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
        MongoPaymentRepository,
    )

    await _seed_session(db, acad, "sess-a", price=8000, day="Sat")
    await _seed_session(db, acad, "sess-b", price=12000, day="Sun")
    ledger = MongoBillingLedgerRepository(db)
    await _seed_invoice(ledger, acad, status="paid")

    adjustment = await _use_case(db).execute(_cmd())
    assert adjustment.outcome == "adjustment_invoiced"

    generator = MongoMonthlyBillingGenerator(MongoPaymentRepository(db))
    found = await generator._find_existing_invoice_for_enrollment_period(
        enrollment_id="enr-1", period="2026-09"
    )
    assert found == "inv-enr-1-2026-09"
