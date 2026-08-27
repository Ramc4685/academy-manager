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
        "charge_enrollment_id": "enroll-1",
        "charge_amount_cents": 4_000,
    }
    with tenant_scope("other-academy"):
        assert await MongoBillingLedgerRepository(db).billing_setup_by_parent() == {}


@pytest.mark.asyncio
async def test_billing_setup_excludes_draft_and_void_balances(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    for invoice_id, status, created_at in (
        ("inv-void", "void", datetime(2026, 4, 1, tzinfo=UTC)),
        ("inv-draft", "draft", datetime(2026, 4, 2, tzinfo=UTC)),
        ("inv-open", "open", datetime(2026, 5, 1, tzinfo=UTC)),
    ):
        invoice = _invoice(
            invoice_id=invoice_id,
            parent_id="parent-a",
            academy_id=acad,
            created_at=created_at,
        ).model_copy(update={"status": status})
        await repo.create_invoice(invoice, lines=[], idempotency_key=f"key-{invoice_id}")

    assert await repo.outstanding_by_parent() == {"parent-a": 12_000}
    assert await repo.billing_setup_by_parent() == {
        "parent-a": {
            "outstanding_cents": 12_000,
            "charge_invoice_id": "inv-open",
            "charge_enrollment_id": "enroll-1",
            "charge_amount_cents": 12_000,
        }
    }


# ---------------------------------------------------------------------------
# list_undelivered_invoices_for_period (issue #430)
# ---------------------------------------------------------------------------


async def _seed(repo, acad: str, invoice_id: str, **updates) -> None:
    invoice = _invoice(
        invoice_id=invoice_id,
        parent_id="parent-a",
        academy_id=acad,
        created_at=updates.pop("created_at", datetime(2026, 5, 1, tzinfo=UTC)),
    ).model_copy(update=updates)
    await repo.create_invoice(invoice, lines=[], idempotency_key=f"key-{invoice_id}")


@pytest.mark.asyncio
async def test_undelivered_query_excludes_already_sent_invoices(db, acad) -> None:
    """delivery_status is the idempotency key for the auto-email pass — a
    re-run must not email a parent their invoice twice."""
    repo = MongoBillingLedgerRepository(db)
    await _seed(repo, acad, "inv-fresh")
    await _seed(repo, acad, "inv-sent", delivery_status="sent")
    await _seed(repo, acad, "inv-retry", delivery_status="delivery_failed")

    rows = await repo.list_undelivered_invoices_for_period("2026-05")

    assert sorted(inv.invoice_id for inv in rows) == ["inv-fresh", "inv-retry"]


@pytest.mark.asyncio
async def test_undelivered_query_is_scoped_to_the_period(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    await _seed(repo, acad, "inv-may")
    await _seed(repo, acad, "inv-april", period="2026-04")

    rows = await repo.list_undelivered_invoices_for_period("2026-05")

    assert [inv.invoice_id for inv in rows] == ["inv-may"]


@pytest.mark.asyncio
async def test_undelivered_query_skips_settled_and_unpayable_invoices(db, acad) -> None:
    """A zero-balance or void invoice has nothing to collect, so emailing a
    pay link for it would just confuse the parent."""
    repo = MongoBillingLedgerRepository(db)
    await _seed(repo, acad, "inv-owing")
    await _seed(repo, acad, "inv-settled", status="paid", balance_due_cents=0)
    await _seed(repo, acad, "inv-void", status="void", balance_due_cents=12_000)
    await _seed(repo, acad, "inv-partial", status="partially_paid", balance_due_cents=4_000)

    rows = await repo.list_undelivered_invoices_for_period("2026-05")

    assert sorted(inv.invoice_id for inv in rows) == ["inv-owing", "inv-partial"]


@pytest.mark.asyncio
async def test_undelivered_query_returns_oldest_first_and_honours_the_limit(db, acad) -> None:
    """A period with more invoices than one pass can send must drain from the
    oldest, not re-send the same head page every tick."""
    repo = MongoBillingLedgerRepository(db)
    await _seed(repo, acad, "inv-3", created_at=datetime(2026, 5, 3, tzinfo=UTC))
    await _seed(repo, acad, "inv-1", created_at=datetime(2026, 5, 1, tzinfo=UTC))
    await _seed(repo, acad, "inv-2", created_at=datetime(2026, 5, 2, tzinfo=UTC))

    rows = await repo.list_undelivered_invoices_for_period("2026-05", limit=2)

    assert [inv.invoice_id for inv in rows] == ["inv-1", "inv-2"]


@pytest.mark.asyncio
async def test_undelivered_query_does_not_cross_academies(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    await _seed(repo, acad, "inv-mine")
    with tenant_scope("academy-other"):
        await _seed(repo, "academy-other", "inv-theirs")

    rows = await repo.list_undelivered_invoices_for_period("2026-05")

    assert [inv.invoice_id for inv in rows] == ["inv-mine"]
