from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.domain.ledger import LedgerInvoice
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.shared.tenancy import tenant_scope


def _now() -> datetime:
    return datetime(2026, 5, 16, 9, 0, tzinfo=UTC)


def _invoice(
    *, invoice_id: str, parent_id: str, academy_id: str, created_at: datetime
) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id=academy_id,
        parent_id=parent_id,
        student_id="student-1",
        enrollment_id="enroll-1",
        period="2026-05",
        status="open",
        subtotal_cents=12_000,
        discount_cents=0,
        total_cents=12_000,
        balance_due_cents=12_000,
        currency="usd",
        due_date=date(2026, 5, 31),
        created_at=created_at,
        updated_at=created_at,
    )


@pytest.mark.asyncio
async def test_list_invoices_for_parent_returns_only_that_parents_invoices(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    await repo.create_invoice(
        _invoice(
            invoice_id="inv-a1",
            parent_id="parent-a",
            academy_id=acad,
            created_at=datetime(2026, 5, 1, tzinfo=UTC),
        ),
        lines=[],
        idempotency_key="key-a1",
    )
    await repo.create_invoice(
        _invoice(
            invoice_id="inv-a2",
            parent_id="parent-a",
            academy_id=acad,
            created_at=datetime(2026, 5, 10, tzinfo=UTC),
        ),
        lines=[],
        idempotency_key="key-a2",
    )
    await repo.create_invoice(
        _invoice(
            invoice_id="inv-b1",
            parent_id="parent-b",
            academy_id=acad,
            created_at=datetime(2026, 5, 5, tzinfo=UTC),
        ),
        lines=[],
        idempotency_key="key-b1",
    )

    rows = await repo.list_invoices_for_parent("parent-a")
    # Newest first (created_at desc).
    assert [inv.invoice_id for inv in rows] == ["inv-a2", "inv-a1"]
    assert all(inv.parent_id == "parent-a" for inv in rows)


@pytest.mark.asyncio
async def test_list_invoices_for_parent_is_tenant_isolated(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    await repo.create_invoice(
        _invoice(
            invoice_id="inv-a1",
            parent_id="parent-a",
            academy_id=acad,
            created_at=_now(),
        ),
        lines=[],
        idempotency_key="key-a1",
    )

    assert [inv.invoice_id for inv in await repo.list_invoices_for_parent("parent-a")] == ["inv-a1"]

    with tenant_scope("other-academy"):
        other_repo = MongoBillingLedgerRepository(db)
        assert await other_repo.list_invoices_for_parent("parent-a") == []


@pytest.mark.asyncio
async def test_billing_setup_targets_exact_oldest_invoice_and_is_tenant_isolated(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    oldest = _invoice(
        invoice_id="inv-oldest",
        parent_id="parent-a",
        academy_id=acad,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    ).model_copy(update={"balance_due_cents": 4_000, "total_cents": 4_000, "subtotal_cents": 4_000})
    newer = _invoice(
        invoice_id="inv-newer",
        parent_id="parent-a",
        academy_id=acad,
        created_at=datetime(2026, 5, 10, tzinfo=UTC),
    ).model_copy(update={"balance_due_cents": 6_000, "total_cents": 6_000, "subtotal_cents": 6_000})
    await repo.create_invoice(oldest, lines=[], idempotency_key="key-oldest")
    await repo.create_invoice(newer, lines=[], idempotency_key="key-newer")

    rows = await repo.billing_setup_by_parent()

    assert rows["parent-a"] == {
        "outstanding_cents": 10_000,
        "charge_invoice_id": "inv-oldest",
        "charge_amount_cents": 4_000,
    }
    with tenant_scope("other-academy"):
        assert await MongoBillingLedgerRepository(db).billing_setup_by_parent() == {}
