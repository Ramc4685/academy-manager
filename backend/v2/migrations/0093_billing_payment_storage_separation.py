"""No-op waiver migration: LedgerPayment storage separation (ADR-0011, Phase 1).

Phase 0 audit (2026-06-14) confirmed **0 LedgerPayment-shaped documents** in
the ``payments`` collection.  A LedgerPayment-shaped doc is identified by the
presence of the ``ledger_idempotency_key`` field, which does not exist on any
legacy Payment document.

Because there are no docs to move, the copy → verify → delete sequence
described in ADR-0011 §Decision.2 reduces to a no-op.  This migration records
that fact durably in the migration log and adds a reconciliation assertion so
that if the assumption is ever violated (e.g. someone re-runs a stale webhook
handler that wrote into ``payments`` before this migration ran), the runner
will halt with a clear error rather than silently leaving a cross-leak.

Rollback: none required — no data was moved.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0093_billing_payment_storage_separation"


async def up(db: AsyncIOMotorDatabase) -> None:
    # Reconciliation assertion: payments must contain zero LedgerPayment-shaped docs.
    # A doc is LedgerPayment-shaped iff it carries the ledger_idempotency_key field.
    cross_count = await db["payments"].count_documents(
        {"ledger_idempotency_key": {"$exists": True}}
    )
    if cross_count != 0:
        raise RuntimeError(
            f"ADR-0011 reconciliation failed: found {cross_count} LedgerPayment-shaped "
            "doc(s) in the 'payments' collection.  Phase 0 audit expected 0.  "
            "Inspect those docs, copy them to 'ledger_payments', verify counts, "
            "then remove them from 'payments' before re-running this migration."
        )

    # No documents to migrate — assertion passed, waiver recorded by the runner.
