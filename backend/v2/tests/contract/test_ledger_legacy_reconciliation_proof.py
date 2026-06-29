"""P0-5: Ledger-vs-legacy reconciliation proof.

Seeds mixed legacy ``payments`` (multiple parents, succeeded/pending/waived) in a
mongomock database, runs the Phase-4 backfill (dry-run then apply), and asserts the
per-parent legacy balance equals the per-parent ledger balance with zero mismatches.
Then runs the ADR-0011 storage audit and asserts no ledger-shaped payment is missing
from ``ledger_payments``.

This is the runnable reconciliation evidence for the billing-ledger convergence: it
proves the legacy->ledger mapping is balance-preserving without touching production data.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.scripts import backfill_p4_legacy_payments as backfill
from backend.scripts import ledger_payments_storage_audit as storage_audit

ACADEMY = "blno"
_NOW = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)


def _legacy_payment(
    *,
    payment_id: str,
    parent_id: str,
    amount_cents: int,
    status: str,
) -> dict[str, object]:
    return {
        "academy_id": ACADEMY,
        "payment_id": payment_id,
        "parent_id": parent_id,
        "student_id": f"student-{parent_id}",
        "enrollment_id": f"enroll-{payment_id}",
        "amount_cents": amount_cents,
        "status": status,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


@pytest.mark.asyncio
async def test_backfill_reconciles_legacy_and_ledger_balances(db) -> None:
    # Two parents, mix of the three statuses that exist in production (succeeded/pending/waived).
    seed = [
        _legacy_payment(
            payment_id="p-1", parent_id="parent-a", amount_cents=7000, status="succeeded"
        ),
        _legacy_payment(
            payment_id="p-2", parent_id="parent-a", amount_cents=5000, status="pending"
        ),
        _legacy_payment(
            payment_id="p-3", parent_id="parent-b", amount_cents=9000, status="succeeded"
        ),
        _legacy_payment(payment_id="p-4", parent_id="parent-b", amount_cents=3000, status="waived"),
    ]
    await db["payments"].insert_many(seed)

    # Dry-run writes nothing but still reconciles.
    dry = await backfill.backfill_legacy_payments(db, academy_id=ACADEMY, dry_run=True)
    assert dry["total_mismatches"] == 0, dry
    assert dry["fatal_count"] == 0, dry
    assert (
        await db["invoices"].count_documents({"academy_id": ACADEMY}) == 0
    )  # dry-run wrote nothing

    # Apply writes the ledger and must reconcile per-parent legacy==ledger balances.
    applied = await backfill.backfill_legacy_payments(db, academy_id=ACADEMY, dry_run=False)
    assert applied["total_mismatches"] == 0, applied
    assert applied["fatal_count"] == 0, applied

    # Every legacy payment produced a ledger invoice.
    assert await db["invoices"].count_documents({"academy_id": ACADEMY}) == len(seed)

    # Re-running is idempotent (no new fatal mismatches).
    rerun = await backfill.backfill_legacy_payments(db, academy_id=ACADEMY, dry_run=False)
    assert rerun["fatal_count"] == 0, rerun
    assert rerun["total_mismatches"] == 0, rerun


@pytest.mark.asyncio
async def test_storage_audit_reports_no_missing_ledger_payments(db) -> None:
    await db["payments"].insert_many(
        [
            _legacy_payment(
                payment_id="p-1", parent_id="parent-a", amount_cents=7000, status="succeeded"
            ),
            _legacy_payment(
                payment_id="p-2", parent_id="parent-b", amount_cents=9000, status="succeeded"
            ),
        ]
    )
    await backfill.backfill_legacy_payments(db, academy_id=ACADEMY, dry_run=False)

    report = await storage_audit.audit(db)

    # Legacy payments are legacy-shaped (not ledger-shaped), so none should be
    # "ledger-shaped rows stranded in `payments`" — i.e. nothing missing from ledger_payments.
    assert report["missing_from_ledger_payments"] == 0, report
