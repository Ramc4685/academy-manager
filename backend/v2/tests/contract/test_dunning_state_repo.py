from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.v2.contexts.billing.application.use_cases.process_dunning_retries import (
    ProcessDunningRetries,
)
from backend.v2.contexts.billing.domain.dunning import open_initial_dunning_state
from backend.v2.contexts.billing.infrastructure.mongo_dunning_state_repo import (
    MongoDunningStateRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_student_billing_enrollment_repo import (
    MongoStudentBillingEnrollmentRepository,
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
    balance_due_cents: int = 10_000,
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
            "balance_due_cents": balance_due_cents,
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


@pytest.mark.asyncio
async def test_prepare_due_states_overfetches_past_existing_rows_until_limit_created(
    db, acad
) -> None:
    repo = MongoDunningStateRepository(db)
    for idx in range(1, 6):
        await _seed_invoice(
            db,
            academy_id=acad,
            invoice_id=f"inv-{idx}",
            enrollment_id=f"enr-{idx}",
        )
    for idx in range(1, 4):
        state = open_initial_dunning_state(
            academy_id=acad,
            invoice_id=f"inv-{idx}",
            parent_id=f"parent-inv-{idx}",
            enrollment_id=f"enr-{idx}",
            due_at=NOW,
            now=NOW,
        )
        await db["dunning_states"].insert_one(state.model_dump(mode="python"))

    assert await repo.prepare_due_states(now=NOW, limit=2) == 2

    created_ids = {
        row["invoice_id"]
        async for row in db["dunning_states"].find(
            {"academy_id": acad},
            {"invoice_id": 1},
        )
    }
    assert created_ids == {"inv-1", "inv-2", "inv-3", "inv-4", "inv-5"}


@pytest.mark.asyncio
async def test_paid_void_no_balance_and_paused_states_are_suppressed_without_blocking_claim(
    db, acad
) -> None:
    repo = MongoDunningStateRepository(db)
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-paid", enrollment_id="enr-paid")
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-void", enrollment_id="enr-void")
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-zero",
        enrollment_id="enr-zero",
    )
    await _seed_invoice(
        db,
        academy_id=acad,
        invoice_id="inv-paused",
        enrollment_id="enr-paused",
    )
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-valid", enrollment_id="enr-valid")
    await repo.prepare_due_states(now=NOW, limit=10)
    await db["invoices"].update_one({"invoice_id": "inv-paid"}, {"$set": {"status": "paid"}})
    await db["invoices"].update_one({"invoice_id": "inv-void"}, {"$set": {"status": "void"}})
    await db["invoices"].update_one({"invoice_id": "inv-zero"}, {"$set": {"balance_due_cents": 0}})
    await db["student_billing_enrollments"].update_one(
        {"enrollment_id": "enr-paused"},
        {"$set": {"autopay_enrollment_status": "paused"}},
    )

    claimed = await repo.claim_next_due(now=NOW, worker_id="worker-1")

    assert claimed is not None
    assert claimed[0].invoice_id == "inv-valid"
    for idx in range(2, 8):
        await repo.claim_next_due(now=NOW, worker_id=f"worker-{idx}")
    suppressed = {
        row["invoice_id"]: row["suppression_reason"]
        async for row in db["dunning_states"].find({"status": "suppressed"})
    }
    assert suppressed == {
        "inv-paid": "invoice_not_chargeable",
        "inv-void": "invoice_not_chargeable",
        "inv-zero": "invoice_not_chargeable",
        "inv-paused": "autopay_not_active",
    }


@pytest.mark.asyncio
async def test_processing_and_succeeded_payment_attempts_block_new_dunning_charge(db, acad) -> None:
    repo = MongoDunningStateRepository(db)
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-processing", enrollment_id="enr-p")
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-succeeded", enrollment_id="enr-s")
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-valid", enrollment_id="enr-v")
    await repo.prepare_due_states(now=NOW, limit=10)
    await db["payment_attempts"].insert_many(
        [
            {
                "academy_id": acad,
                "attempt_id": "attempt-processing",
                "invoice_id": "inv-processing",
                "parent_id": "parent-inv-processing",
                "amount_cents": 10_000,
                "currency": "usd",
                "status": "processing",
                "idempotency_key": "attempt-processing",
                "created_at": NOW,
                "updated_at": NOW,
            },
            {
                "academy_id": acad,
                "attempt_id": "attempt-succeeded",
                "invoice_id": "inv-succeeded",
                "parent_id": "parent-inv-succeeded",
                "amount_cents": 10_000,
                "currency": "usd",
                "status": "succeeded",
                "idempotency_key": "attempt-succeeded",
                "created_at": NOW,
                "updated_at": NOW,
            },
        ]
    )

    claimed = await repo.claim_next_due(now=NOW, worker_id="worker-1")

    assert claimed is not None
    assert claimed[0].invoice_id == "inv-valid"
    processing_state = await db["dunning_states"].find_one({"invoice_id": "inv-processing"})
    succeeded_state = await db["dunning_states"].find_one({"invoice_id": "inv-succeeded"})
    assert processing_state["status"] == "active"
    assert processing_state["next_attempt_at"] is None
    assert processing_state["suppression_reason"] == "payment_processing"
    assert succeeded_state["status"] == "resolved"


@pytest.mark.asyncio
async def test_parked_processing_state_resumes_after_latest_attempt_fails(db, acad) -> None:
    repo = MongoDunningStateRepository(db)
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-processing", enrollment_id="enr-p")
    await repo.prepare_due_states(now=NOW, limit=10)
    await db["payment_attempts"].insert_one(
        {
            "academy_id": acad,
            "attempt_id": "attempt-processing",
            "invoice_id": "inv-processing",
            "parent_id": "parent-inv-processing",
            "amount_cents": 10_000,
            "currency": "usd",
            "status": "processing",
            "idempotency_key": "attempt-processing",
            "created_at": NOW,
            "updated_at": NOW,
        }
    )

    assert await repo.claim_next_due(now=NOW, worker_id="parking-worker") is None
    parked_state = await db["dunning_states"].find_one({"invoice_id": "inv-processing"})
    assert parked_state["status"] == "active"
    assert parked_state["next_attempt_at"] is None
    assert parked_state["suppression_reason"] == "payment_processing"

    await db["payment_attempts"].update_one(
        {"attempt_id": "attempt-processing"},
        {"$set": {"status": "failed", "updated_at": NOW + timedelta(minutes=5)}},
    )

    claimed = await repo.claim_next_due(now=NOW + timedelta(minutes=5), worker_id="retry-worker")

    assert claimed is not None
    invoice, state = claimed
    assert invoice.invoice_id == "inv-processing"
    assert state.invoice_id == "inv-processing"
    assert state.status == "processing"
    assert state.processing_attempt_no == 1
    assert state.processing_worker_id == "retry-worker"


@pytest.mark.asyncio
async def test_retryable_parked_states_are_rechecked(db, acad) -> None:
    repo = MongoDunningStateRepository(db)
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-connect", enrollment_id="enr-connect")
    await repo.prepare_due_states(now=NOW, limit=10)
    await db["dunning_states"].update_one(
        {"invoice_id": "inv-connect"},
        {
            "$set": {
                "next_attempt_at": None,
                "suppression_reason": "connected_account_not_ready",
                "suppressed_at": NOW,
            }
        },
    )

    claimed = await repo.claim_next_due(now=NOW + timedelta(minutes=5), worker_id="retry-worker")

    assert claimed is not None
    invoice, state = claimed
    assert invoice.invoice_id == "inv-connect"
    assert state.status == "processing"
    assert state.processing_worker_id == "retry-worker"


@pytest.mark.asyncio
async def test_fresh_processing_claim_is_not_reclaimed_but_stale_processing_is(db, acad) -> None:
    repo = MongoDunningStateRepository(db)
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-fresh", enrollment_id="enr-fresh")
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-stale", enrollment_id="enr-stale")
    await repo.prepare_due_states(now=NOW, limit=10)
    fresh = await repo.claim_next_due(now=NOW, worker_id="fresh-worker")
    stale = await repo.claim_next_due(now=NOW, worker_id="stale-worker")
    assert fresh is not None
    assert stale is not None
    await db["dunning_states"].update_one(
        {"invoice_id": stale[0].invoice_id},
        {
            "$set": {
                "processing_started_at": NOW - timedelta(hours=2),
                "lease_expires_at": NOW - timedelta(minutes=1),
            }
        },
    )

    reclaimed = await repo.claim_next_due(now=NOW, worker_id="reclaim-worker")

    assert reclaimed is not None
    assert reclaimed[0].invoice_id == stale[0].invoice_id
    assert reclaimed[1].processing_worker_id == "reclaim-worker"


class _AlwaysFailsCharge:
    async def execute(self, invoice_id: str, retry_scope: str | None = None):
        return {
            "success": False,
            "invoice_id": invoice_id,
            "status": "open",
            "balance_due_cents": 10_000,
            "decline_code": "insufficient_funds",
        }


@pytest.mark.asyncio
async def test_worker_with_real_mongo_repos_terminally_disables_enrollment(db, acad) -> None:
    repo = MongoDunningStateRepository(db)
    enrollments = MongoStudentBillingEnrollmentRepository(db)
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-terminal", enrollment_id="enr-term")
    await repo.prepare_due_states(now=NOW, limit=10)
    await db["dunning_states"].update_one(
        {"invoice_id": "inv-terminal"},
        {
            "$set": {
                "attempt_count": 3,
                "first_attempt_at": NOW - timedelta(days=7),
                "next_attempt_at": NOW,
            }
        },
    )

    result = await ProcessDunningRetries(
        dunning=repo,
        charge_invoice=_AlwaysFailsCharge(),
        enrollment_autopay=enrollments,
        clock=lambda: NOW,
    ).execute(limit=10, worker_id="worker-1")

    assert result.dunned == 1
    assert result.autopay_disabled == 1
    enrollment = await db["student_billing_enrollments"].find_one({"enrollment_id": "enr-term"})
    state = await db["dunning_states"].find_one({"invoice_id": "inv-terminal"})
    assert enrollment["autopay_enrollment_status"] == "disabled"
    assert state["autopay_disable_status"] == "succeeded"
    assert state["autopay_disabled_at"] is not None


@pytest.mark.asyncio
async def test_checkout_mint_failure_does_not_reopen_a_paid_invoice(db, acad) -> None:
    """Issue #426 regression.

    Pay-link mint failures share `payment_attempts` with charge outcomes. A
    mint failure written AFTER a genuine `succeeded` charge must not become the
    invoice's "latest status" — otherwise the sweep skips resolve and keeps
    escalating an invoice that just paid, ending at the terminal rung that
    disables the parent's autopay.
    """
    repo = MongoDunningStateRepository(db)
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-succeeded", enrollment_id="enr-s")
    await _seed_invoice(db, academy_id=acad, invoice_id="inv-valid", enrollment_id="enr-v")
    await repo.prepare_due_states(now=NOW, limit=10)
    await db["payment_attempts"].insert_many(
        [
            {
                "academy_id": acad,
                "attempt_id": "attempt-succeeded",
                "invoice_id": "inv-succeeded",
                "parent_id": "parent-inv-succeeded",
                "amount_cents": 10_000,
                "currency": "usd",
                "status": "succeeded",
                "idempotency_key": "attempt-succeeded",
                "created_at": NOW - timedelta(hours=1),
                "updated_at": NOW - timedelta(hours=1),
            },
            {
                # Newer, but not a charge outcome — an admin re-sent the
                # invoice while Connect was broken.
                "academy_id": acad,
                "attempt_id": "attempt-mint",
                "invoice_id": "inv-succeeded",
                "parent_id": "parent-inv-succeeded",
                "amount_cents": 10_000,
                "currency": "usd",
                "status": "checkout_mint_failed",
                "failure_code": "connected_account_not_ready",
                "idempotency_key": "attempt-mint",
                "created_at": NOW,
                "updated_at": NOW,
            },
        ]
    )

    claimed = await repo.claim_next_due(now=NOW, worker_id="worker-1")

    assert claimed is not None
    assert claimed[0].invoice_id == "inv-valid", "the paid invoice must not be re-claimed"
    succeeded_state = await db["dunning_states"].find_one({"invoice_id": "inv-succeeded"})
    assert succeeded_state["status"] == "resolved"


class _CountingCollection:
    """Delegating wrapper that counts queries against one collection."""

    def __init__(self, coll, counters: dict[str, int]) -> None:
        self._coll = coll
        self._counters = counters

    def find_one(self, *args, **kwargs):
        self._counters["find_one"] += 1
        return self._coll.find_one(*args, **kwargs)

    def find(self, *args, **kwargs):
        self._counters["find"] += 1
        return self._coll.find(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._coll, name)


class _CountingDb:
    def __init__(self, db, collection_name: str, counters: dict[str, int]) -> None:
        self._db = db
        self._collection_name = collection_name
        self._counters = counters

    def __getitem__(self, name):
        coll = self._db[name]
        if name == self._collection_name:
            return _CountingCollection(coll, self._counters)
        return coll

    def __getattr__(self, name):
        return getattr(self._db, name)


@pytest.mark.asyncio
async def test_prepare_due_states_batches_enrollment_lookups(db, acad) -> None:
    """Issue #513: the hourly scan must not pay one enrollment query per open

    invoice. A page of due invoices resolves autopay eligibility with a single
    batched query, and a steady-state tick (every invoice already holding a
    dunning state) issues no enrollment queries at all.
    """
    for idx in range(1, 6):
        await _seed_invoice(
            db,
            academy_id=acad,
            invoice_id=f"inv-{idx}",
            enrollment_id=f"enr-{idx}",
            autopay_status="active" if idx % 2 else "paused",
        )
    counters = {"find_one": 0, "find": 0}
    repo = MongoDunningStateRepository(_CountingDb(db, "student_billing_enrollments", counters))

    assert await repo.prepare_due_states(now=NOW, limit=100) == 3

    assert counters["find_one"] == 0, "per-invoice enrollment find_one is the N+1 (#513)"
    assert counters["find"] == 1, "one page of invoices must need one enrollment query"

    # Steady-state tick: nothing new to create, and eligibility for the
    # paused stragglers is still resolved in one batched query.
    assert await repo.prepare_due_states(now=NOW, limit=100) == 0
    assert counters["find_one"] == 0
    assert counters["find"] == 2


@pytest.mark.asyncio
async def test_prepare_due_states_pages_and_stops_at_limit(db, acad, monkeypatch) -> None:
    for idx in range(1, 8):
        await _seed_invoice(
            db,
            academy_id=acad,
            invoice_id=f"inv-{idx:02d}",
            enrollment_id=f"enr-{idx:02d}",
        )
    # Force multiple pages to exercise the mid-stream limit exit.
    monkeypatch.setattr(MongoDunningStateRepository, "prepare_batch_size", 3)
    repo = MongoDunningStateRepository(db)

    assert await repo.prepare_due_states(now=NOW, limit=4) == 4

    created_ids = sorted(
        [
            row["invoice_id"]
            async for row in db["dunning_states"].find({"academy_id": acad}, {"invoice_id": 1})
        ]
    )
    assert created_ids == ["inv-01", "inv-02", "inv-03", "inv-04"]

    # The remaining invoices are picked up by the next tick.
    assert await repo.prepare_due_states(now=NOW, limit=10) == 3


@pytest.mark.asyncio
async def test_migration_0156_indexes_the_dunning_invoice_scan(db) -> None:
    import importlib

    module = importlib.import_module("backend.v2.migrations.0156_dunning_scan_invoice_index")
    await module.up(db)

    info = await db["invoices"].index_information()
    assert "academy_invoice_status_due_date" in info
