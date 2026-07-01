from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.v2.contexts.billing.infrastructure.mongo_dunning_state_repo import (
    MongoDunningStateRepository,
)
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


async def _seed_invoice(
    db,
    *,
    academy_id: str,
    invoice_id: str,
    enrollment_id: str,
    invoice_status: str = "open",
    autopay_status: str = "active",
    due_date: date = date(2026, 7, 1),
) -> None:
    await db["invoices"].insert_one(
        {
            "academy_id": academy_id,
            "invoice_id": invoice_id,
            "parent_id": f"parent-{invoice_id}",
            "student_id": f"student-{invoice_id}",
            "enrollment_id": enrollment_id,
            "period": "2026-07",
            "status": invoice_status,
            "subtotal_cents": 10_000,
            "discount_cents": 0,
            "total_cents": 10_000,
            "balance_due_cents": 10_000,
            "currency": "usd",
            "due_date": datetime.combine(due_date, datetime.min.time(), tzinfo=UTC),
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    await db["student_billing_enrollments"].insert_one(
        {
            "academy_id": academy_id,
            "enrollment_id": enrollment_id,
            "student_id": f"student-{invoice_id}",
            "parent_id": f"parent-{invoice_id}",
            "session_type_id": "session-type-1",
            "billing_start_date": datetime(2026, 7, 1, tzinfo=UTC),
            "status": "active",
            "autopay_enrollment_status": autopay_status,
            "enrolled_at": NOW,
            "updated_at": NOW,
        }
    )


@pytest.mark.asyncio
async def test_prepare_due_states_only_selects_due_open_autopay_active_invoices(db, acad) -> None:
    repo = MongoDunningStateRepository(db)
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-due", enrollment_id="enr-due")
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-future",
        enrollment_id="enr-future",
        due_date=date(2026, 7, 9),
    )
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-paid",
        enrollment_id="enr-paid",
        invoice_status="paid",
    )
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-paused",
        enrollment_id="enr-paused",
        autopay_status="paused",
    )

    assert await repo.prepare_due_states(now=NOW, limit=100) == 1
    claimed = await repo.claim_next_due(now=NOW, worker_id="worker-1")

    assert claimed is not None
    invoice, state = claimed
    assert invoice.invoice_id == "inv-due"
    assert state.invoice_id == "inv-due"
    assert await db["dunning_states"].count_documents({"academy_id": acad}) == 1


@pytest.mark.asyncio
async def test_claim_and_finish_are_idempotent_across_worker_runs(db, acad) -> None:
    repo = MongoDunningStateRepository(db)
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-due", enrollment_id="enr-due")
    await repo.prepare_due_states(now=NOW, limit=100)

    first = await repo.claim_next_due(now=NOW, worker_id="worker-1")
    second = await repo.claim_next_due(now=NOW, worker_id="worker-2")
    assert first is not None
    assert second is None

    _invoice, state = first
    finished = await repo.finish_attempt(
        state=state,
        succeeded=False,
        failure_code="insufficient_funds",
        now=NOW,
    )
    assert finished.next_attempt_at == NOW + timedelta(days=3)
    assert await repo.claim_next_due(now=NOW, worker_id="worker-3") is None


@pytest.mark.asyncio
async def test_dunning_state_repository_is_tenant_isolated(db, acad) -> None:
    repo = MongoDunningStateRepository(db)
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-a", enrollment_id="enr-a")
    with tenant_scope("other-academy"):
        await _seed_invoice(
            db,
            academy_id="other-academy",
            invoice_id="inv-b",
            enrollment_id="enr-b",
        )
        other_repo = MongoDunningStateRepository(db)
        assert await other_repo.prepare_due_states(now=NOW, limit=100) == 1
        other_claimed = await other_repo.claim_next_due(now=NOW, worker_id="worker-other")
        assert other_claimed is not None
        assert other_claimed[0].invoice_id == "inv-b"

    assert await repo.prepare_due_states(now=NOW, limit=100) == 1
    claimed = await repo.claim_next_due(now=NOW, worker_id="worker-a")
    assert claimed is not None
    assert claimed[0].invoice_id == "inv-a"
