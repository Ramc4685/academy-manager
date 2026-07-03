"""Contract tests for billing-health repo read methods (#235).

Covers the new read/query methods added on top of the #224 infrastructure:
- MongoBillingReconciliationRunRepository.list_runs
- MongoBillingLedgerRepository.list_payment_attempts / list_open_failed_attempts
- MongoStripeEventDedup.replay
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_reconciliation_run_repo import (
    MongoBillingReconciliationRunRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_stripe_dedup import (
    MongoStripeEventDedup,
)

NOW = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# reconciliation runs
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_list_runs_returns_newest_first_scoped_to_academy(db, acad) -> None:
    repo = MongoBillingReconciliationRunRepository(db)
    await repo.record_run(
        academy_id=acad, run_id="r-old", started_at=NOW - timedelta(minutes=10), scanned=8
    )
    await repo.record_run(academy_id=acad, run_id="r-new", started_at=NOW, scanned=9)
    await repo.record_run(academy_id="other", run_id="r-other", started_at=NOW, scanned=1)

    runs = await repo.list_runs(acad, limit=10)

    assert [r["run_id"] for r in runs] == ["r-new", "r-old"]
    assert all("_id" not in r for r in runs)
    assert all(r["academy_id"] == acad for r in runs)


@pytest.mark.asyncio
async def test_list_runs_respects_limit(db, acad) -> None:
    repo = MongoBillingReconciliationRunRepository(db)
    for i in range(5):
        await repo.record_run(
            academy_id=acad, run_id=f"r-{i}", started_at=NOW - timedelta(minutes=i)
        )
    runs = await repo.list_runs(acad, limit=2)
    assert len(runs) == 2
    assert runs[0]["run_id"] == "r-0"


# --------------------------------------------------------------------------- #
# payment attempts
# --------------------------------------------------------------------------- #
async def _attempt(repo, *, invoice_id, status, when, code=None):
    # Use a dedicated clock so created_at ordering is deterministic.
    repo._clock = lambda: when
    await repo.record_payment_attempt(
        invoice_id=invoice_id,
        parent_id="parent-1",
        amount_cents=12000,
        currency="usd",
        status=status,
        stripe_payment_intent_id=f"pi_{invoice_id}_{status}",
        stripe_checkout_session_id=None,
        failure_code=code,
        failure_message="Your card was declined." if code else None,
        idempotency_key=f"{invoice_id}:{status}:{when.isoformat()}",
    )


async def _open_invoice(db, acad, invoice_id, status="open"):
    # Minimal invoice doc covering only the fields list_open_failed_attempts reads.
    await db["invoices"].insert_one(
        {
            "invoice_id": invoice_id,
            "academy_id": acad,
            "parent_id": "parent-1",
            "period": "2026-06",
            "status": status,
            "total_cents": 12000,
            "balance_due_cents": 12000,
            "currency": "usd",
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


@pytest.mark.asyncio
async def test_list_payment_attempts_newest_first(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    await _attempt(
        repo,
        invoice_id="inv-1",
        status="failed",
        when=NOW - timedelta(days=1),
        code="card_declined",
    )
    await _attempt(repo, invoice_id="inv-1", status="failed", when=NOW, code="insufficient_funds")
    await _attempt(repo, invoice_id="inv-2", status="succeeded", when=NOW)

    attempts = await repo.list_payment_attempts("inv-1")

    assert [a["failure_code"] for a in attempts] == ["insufficient_funds", "card_declined"]
    assert all(a["invoice_id"] == "inv-1" for a in attempts)


@pytest.mark.asyncio
async def test_list_payment_attempts_tenant_scoped(db, acad, other_acad) -> None:
    # other_acad fixture overrides the context to "other-academy"; record under it.
    repo = MongoBillingLedgerRepository(db)
    await _attempt(repo, invoice_id="inv-x", status="failed", when=NOW, code="card_declined")
    # Switch back to acad and confirm we can't see other-academy's attempts.
    from backend.v2.shared.tenancy.context import _current as _tv

    token = _tv.set(acad)
    try:
        assert await repo.list_payment_attempts("inv-x") == []
    finally:
        _tv.reset(token)


@pytest.mark.asyncio
async def test_list_open_failed_attempts_includes_only_failed_latest(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    # inv-failed: open invoice, latest attempt failed -> included
    await _open_invoice(db, acad, "inv-failed", status="open")
    await _attempt(repo, invoice_id="inv-failed", status="failed", when=NOW, code="card_declined")
    # inv-recovered: latest attempt succeeded -> excluded
    await _open_invoice(db, acad, "inv-recovered", status="partially_paid")
    await _attempt(
        repo,
        invoice_id="inv-recovered",
        status="failed",
        when=NOW - timedelta(days=1),
        code="card_declined",
    )
    await _attempt(repo, invoice_id="inv-recovered", status="succeeded", when=NOW)
    # inv-paid: paid invoice -> excluded even if a failed attempt exists
    await _open_invoice(db, acad, "inv-paid", status="paid")
    await _attempt(repo, invoice_id="inv-paid", status="failed", when=NOW, code="card_declined")

    rows = await repo.list_open_failed_attempts()

    ids = [r["invoice_id"] for r in rows]
    assert ids == ["inv-failed"]
    row = rows[0]
    assert row["latest_decline_code"] == "card_declined"
    assert row["balance_due_cents"] == 12000
    assert row["attempt_count"] == 1


@pytest.mark.asyncio
async def test_list_open_failed_attempts_requires_action_included(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    await _open_invoice(db, acad, "inv-ra", status="open")
    await _attempt(repo, invoice_id="inv-ra", status="requires_action", when=NOW)
    rows = await repo.list_open_failed_attempts()
    assert [r["invoice_id"] for r in rows] == ["inv-ra"]


@pytest.mark.asyncio
async def test_list_open_failed_attempts_newest_first_and_limit(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    for i in range(3):
        await _open_invoice(db, acad, f"inv-{i}", status="open")
        await _attempt(
            repo,
            invoice_id=f"inv-{i}",
            status="failed",
            when=NOW - timedelta(days=i),
            code="card_declined",
        )

    rows = await repo.list_open_failed_attempts()
    assert [r["invoice_id"] for r in rows] == ["inv-0", "inv-1", "inv-2"]

    limited = await repo.list_open_failed_attempts(limit=2)
    assert [r["invoice_id"] for r in limited] == ["inv-0", "inv-1"]


@pytest.mark.asyncio
async def test_list_open_failed_attempts_tenant_scoped(db, acad, other_acad) -> None:
    # other_acad fixture sets the tenant context to "other-academy"; write there.
    repo = MongoBillingLedgerRepository(db)
    await _open_invoice(db, other_acad, "inv-other", status="open")
    await _attempt(repo, invoice_id="inv-other", status="failed", when=NOW, code="card_declined")

    from backend.v2.shared.tenancy.context import _current as _tv

    token = _tv.set(acad)
    try:
        assert await repo.list_open_failed_attempts() == []
    finally:
        _tv.reset(token)


# --------------------------------------------------------------------------- #
# unmatched invoices (legacy match queue input)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_list_unmatched_invoices_excludes_allocated_and_orders_newest_first(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    await _open_invoice(db, acad, "inv-old")
    await db["invoices"].update_one(
        {"academy_id": acad, "invoice_id": "inv-old"},
        {"$set": {"created_at": NOW - timedelta(days=1)}},
    )
    await _open_invoice(db, acad, "inv-new")
    # inv-matched has a payment allocation -> excluded
    await _open_invoice(db, acad, "inv-matched")
    await db["payment_allocations"].insert_one(
        {"academy_id": acad, "invoice_id": "inv-matched", "amount_cents": 12000}
    )
    # allocation from another tenant does not count as matched
    await db["payment_allocations"].insert_one(
        {"academy_id": "other-academy", "invoice_id": "inv-new", "amount_cents": 12000}
    )
    # paid invoices are never in the queue
    await _open_invoice(db, acad, "inv-paid", status="paid")

    rows = await repo.list_unmatched_invoices()

    assert [r["invoice_id"] for r in rows] == ["inv-new", "inv-old"]
    assert rows[0]["balance_due_cents"] == 12000
    assert rows[0]["status"] == "open"

    limited = await repo.list_unmatched_invoices(limit=1)
    assert [r["invoice_id"] for r in limited] == ["inv-new"]


# --------------------------------------------------------------------------- #
# webhook replay
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_replay_resets_quarantined_event(db) -> None:
    await db["stripe_webhook_events"].create_index("event_id", unique=True)
    dedup = MongoStripeEventDedup(db)
    await dedup.store_received(
        {"id": "evt_q", "type": "payment_intent.succeeded", "data": {"object": {"id": "pi_1"}}},
        raw_payload=b"{}",
        academy_id="acad",
    )
    await dedup.mark_quarantined("evt_q", "parent mismatch")

    replayed = await dedup.replay("evt_q", academy_id="acad")

    assert replayed is True
    doc = await db["stripe_webhook_events"].find_one({"event_id": "evt_q"})
    assert doc["status"] == "received"
    assert doc["error_message"] is None
    assert doc["retry_count"] == 0
    assert doc["next_retry_at"] is not None
    assert doc["processing_locked_until"] is None


@pytest.mark.asyncio
async def test_replay_returns_false_for_wrong_academy(db) -> None:
    await db["stripe_webhook_events"].create_index("event_id", unique=True)
    dedup = MongoStripeEventDedup(db)
    await dedup.store_received(
        {"id": "evt_q2", "type": "payment_intent.succeeded", "data": {"object": {"id": "pi_2"}}},
        raw_payload=b"{}",
        academy_id="acad",
    )
    await dedup.mark_quarantined("evt_q2", "parent mismatch")

    assert await dedup.replay("evt_q2", academy_id="other") is False
    doc = await db["stripe_webhook_events"].find_one({"event_id": "evt_q2"})
    assert doc["status"] == "quarantined"


@pytest.mark.asyncio
async def test_replay_returns_false_when_not_quarantined(db) -> None:
    await db["stripe_webhook_events"].create_index("event_id", unique=True)
    dedup = MongoStripeEventDedup(db)
    await dedup.store_received(
        {"id": "evt_r", "type": "payment_intent.succeeded", "data": {"object": {"id": "pi_3"}}},
        raw_payload=b"{}",
        academy_id="acad",
    )
    assert await dedup.replay("evt_r", academy_id="acad") is False
