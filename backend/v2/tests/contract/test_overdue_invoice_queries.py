"""Store-level contract for the two reads the late-fee pass depends on (#552).

``ApplyLateFees`` is only as safe as these filters: if the overdue query let a
``paid``/``void``/``draft`` invoice through, or if ``has_active_retry`` missed
a live ladder, the policy would charge a family that owes nothing or one whose
card we are still retrying ourselves.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.domain.dunning import open_initial_dunning_state
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_dunning_state_repo import (
    MongoDunningStateRepository,
)
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 9, 13, 6, 0, tzinfo=UTC)


async def _seed_invoice(
    db,
    *,
    academy_id: str,
    invoice_id: str,
    status: str = "open",
    due_date: date = date(2026, 9, 1),
    balance_due_cents: int = 10_000,
) -> None:
    await db["invoices"].insert_one(
        {
            "academy_id": academy_id,
            "invoice_id": invoice_id,
            "parent_id": f"parent-{invoice_id}",
            "student_id": f"student-{invoice_id}",
            "enrollment_id": f"enr-{invoice_id}",
            "period": "2026-09",
            "status": status,
            "subtotal_cents": 10_000,
            "discount_cents": 0,
            "total_cents": 10_000,
            "balance_due_cents": balance_due_cents,
            "currency": "usd",
            "due_date": datetime.combine(due_date, datetime.min.time(), tzinfo=UTC),
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


@pytest.mark.asyncio
async def test_list_overdue_invoices_returns_only_collectable_past_due_rows(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-open")
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-partial", status="partially_paid")
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-paid", status="paid")
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-void", status="void")
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-draft", status="draft")
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-settled", balance_due_cents=0)
    # Due exactly on the boundary: `due_before` is exclusive, so this one is
    # still inside its grace period and must NOT come back.
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-boundary", due_date=date(2026, 9, 8))
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-future", due_date=date(2026, 9, 30))
    await _seed_invoice(db, academy_id="other-academy", invoice_id="inv-other-tenant")

    with tenant_scope(acad):
        rows = await repo.list_overdue_invoices(due_before=date(2026, 9, 8))

    assert [r.invoice_id for r in rows] == ["inv-open", "inv-partial"]


@pytest.mark.asyncio
async def test_has_active_retry_is_true_only_while_the_ladder_is_running(db, acad) -> None:
    repo = MongoDunningStateRepository(db)
    with tenant_scope(acad):
        for invoice_id, status in (
            ("inv-active", "active"),
            ("inv-dunned", "dunned"),
            ("inv-resolved", "resolved"),
        ):
            state = open_initial_dunning_state(
                academy_id=acad,
                invoice_id=invoice_id,
                parent_id="parent-1",
                enrollment_id=f"enr-{invoice_id}",
                due_at=NOW,
                now=NOW,
            )
            await db["dunning_states"].insert_one(
                {**state.model_dump(mode="python"), "status": status}
            )

        assert await repo.has_active_retry("inv-active") is True
        assert await repo.has_active_retry("inv-dunned") is False
        assert await repo.has_active_retry("inv-resolved") is False
        assert await repo.has_active_retry("inv-no-ladder") is False
