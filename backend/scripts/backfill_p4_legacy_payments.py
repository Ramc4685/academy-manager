"""Phase 4 backfill: migrate legacy Payment documents into the AR ledger.

Each legacy Payment becomes:
  - one LedgerInvoice  (collection: invoices)
  - one InvoiceLine    (collection: invoice_lines)
  - one LedgerPayment  (collection: ledger_payments)  — succeeded only
  - one PaymentAllocation (collection: payment_allocations) — succeeded only

Idempotent: invoice_id = "inv-from-{payment_id}" is checked before writing.
Legacy docs are identified by the absence of both `ledger_idempotency_key`
and `unapplied_amount_cents` fields.

Usage:
    source backend/.venv/bin/activate
    python -m backend.scripts.backfill_p4_legacy_payments \\
        --academy-id blno [--dry-run]
"""

from __future__ import annotations

import logging
import sys
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")

import motor.motor_asyncio  # noqa: E402

from backend.v2.shared.config import get_settings  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LEGACY_STATUSES = {"succeeded", "pending", "waived"}
INVOICES_COLLECTION = "invoices"
INVOICE_LINES_COLLECTION = "invoice_lines"
LEDGER_PAYMENTS_COLLECTION = "ledger_payments"
ALLOCATIONS_COLLECTION = "payment_allocations"
PAYMENTS_COLLECTION = "payments"


# ---------------------------------------------------------------------------
# Mapping helpers (pure, no I/O — also used by unit tests)
# ---------------------------------------------------------------------------


def _period_from(doc: dict[str, Any]) -> str:
    """Return period string; fall back to month of created_at."""
    period = doc.get("period")
    if period:
        return str(period)
    created_at: datetime = doc["created_at"]
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at.strftime("%Y-%m")


def _due_date_from(doc: dict[str, Any]) -> date:
    """Use created_at date as due_date; legacy payments have no due date."""
    created_at: datetime = doc["created_at"]
    if isinstance(created_at, datetime):
        return created_at.date()
    return created_at  # type: ignore[return-value]


def _parent_id_from(doc: dict[str, Any]) -> str | None:
    return doc.get("parent_id") or doc.get("parent_user_id")


def map_legacy_payment(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a legacy Payment doc to ledger records.

    Returns a dict with keys: invoice, line, ledger_payment (optional),
    allocation (optional).  Returns None if the doc should be skipped.
    """
    payment_id: str = doc.get("payment_id") or str(doc.get("_id", ""))
    status: str = (doc.get("status") or "").lower()

    if status not in LEGACY_STATUSES:
        return None

    parent_id = _parent_id_from(doc)
    period = _period_from(doc)
    amount_cents: int = int(doc.get("amount_cents") or 0)
    discount_cents: int = int(doc.get("discount_cents") or 0)
    total_cents: int = max(0, amount_cents - discount_cents)
    currency: str = str(doc.get("currency") or "usd")
    created_at: datetime = doc["created_at"]
    updated_at: datetime = doc.get("updated_at") or created_at

    # Ensure tz-aware
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)

    invoice_id = f"inv-from-{payment_id}"
    line_id = f"line-from-{payment_id}"

    # Status mapping
    if status == "pending":
        invoice_status = "open"
        balance_due_cents = amount_cents
    elif status == "succeeded":
        invoice_status = "paid"
        balance_due_cents = 0
    else:  # waived
        invoice_status = "void"
        balance_due_cents = 0

    invoice: dict[str, Any] = {
        "invoice_id": invoice_id,
        "academy_id": doc["academy_id"],
        "parent_id": parent_id,
        "student_id": doc.get("student_id"),
        "enrollment_id": doc.get("enrollment_id"),
        "period": period,
        "status": invoice_status,
        "subtotal_cents": amount_cents,
        "discount_cents": discount_cents,
        "total_cents": total_cents,
        "balance_due_cents": balance_due_cents,
        "currency": currency,
        "due_date": _due_date_from(doc),
        "pdf_artifact_id": None,
        "delivery_status": "not_sent",
        "sent_at": None,
        "last_sent_at": None,
        "finalized_at": None,
        "created_at": created_at,
        "updated_at": updated_at,
        # Backfill provenance marker
        "backfill_source": "legacy_payment",
        "backfill_payment_id": payment_id,
    }

    line: dict[str, Any] = {
        "line_id": line_id,
        "invoice_id": invoice_id,
        "academy_id": doc["academy_id"],
        "line_type": "tuition",
        "description": f"Monthly tuition {period}",
        "quantity": 1,
        "unit_amount_cents": amount_cents,
        "amount_cents": amount_cents,
        "source_type": "legacy_payment",
        "source_id": payment_id,
        "created_at": created_at,
    }

    ledger_payment: dict[str, Any] | None = None
    allocation: dict[str, Any] | None = None

    if status == "succeeded":
        lp_payment_id = f"lp-from-{payment_id}"
        lp_amount_cents = int(doc.get("paid_amount_cents") or amount_cents)
        paid_at: datetime = doc.get("paid_at") or created_at
        if paid_at.tzinfo is None:
            paid_at = paid_at.replace(tzinfo=UTC)

        ledger_payment = {
            "payment_id": lp_payment_id,
            "academy_id": doc["academy_id"],
            "parent_id": parent_id,
            "amount_cents": lp_amount_cents,
            "unapplied_amount_cents": 0,
            "currency": currency,
            "status": "succeeded",
            "payment_method": doc.get("payment_method") or "unknown",
            "stripe_payment_intent_id": doc.get("stripe_payment_intent_id"),
            "paid_at": paid_at,
            "recorded_by": None,
            "notes": None,
            "created_at": created_at,
            "updated_at": updated_at,
        }

        allocation = {
            "allocation_id": f"alloc-from-{payment_id}",
            "academy_id": doc["academy_id"],
            "payment_id": lp_payment_id,
            "invoice_id": invoice_id,
            "amount_cents": lp_amount_cents,
            "created_at": created_at,
        }

    return {
        "invoice": invoice,
        "line": line,
        "ledger_payment": ledger_payment,
        "allocation": allocation,
    }


def is_legacy_payment(doc: dict[str, Any]) -> bool:
    """True if doc is a legacy Payment (not a LedgerPayment)."""
    return "ledger_idempotency_key" not in doc and "unapplied_amount_cents" not in doc


# ---------------------------------------------------------------------------
# Reconciliation helpers
# ---------------------------------------------------------------------------


def _legacy_balance_for_parent(docs: list[dict[str, Any]]) -> int:
    """Sum of balance_due_cents from legacy docs (pending → amount, else 0)."""
    total = 0
    for doc in docs:
        status = (doc.get("status") or "").lower()
        if status == "pending":
            total += int(doc.get("amount_cents") or 0)
    return total


def _ledger_balance_for_parent(invoices: list[dict[str, Any]]) -> int:
    return sum(int(inv.get("balance_due_cents") or 0) for inv in invoices)


# ---------------------------------------------------------------------------
# Main async logic
# ---------------------------------------------------------------------------


async def run_backfill(
    *,
    academy_id: str,
    dry_run: bool,
) -> int:
    """Run the backfill and print the reconciliation report.

    Returns the number of fatal mapping errors (exits non-zero if > 0).
    """
    s = get_settings()
    client = motor.motor_asyncio.AsyncIOMotorClient(s.mongo_url)
    db = client[s.mongo_db]

    # Fetch all legacy payments for this academy
    raw_cursor = db[PAYMENTS_COLLECTION].find({"academy_id": academy_id})
    all_docs: list[dict[str, Any]] = await raw_cursor.to_list(length=None)

    legacy_docs = [d for d in all_docs if is_legacy_payment(d)]

    # Counters
    counts: dict[str, int] = defaultdict(int)
    counts["total"] = len(legacy_docs)
    skipped_deleted = 0
    skipped_unknown = 0
    already_backfilled = 0
    errors: list[str] = []

    # Prepare write batches
    invoices_to_write: list[dict[str, Any]] = []
    lines_to_write: list[dict[str, Any]] = []
    lp_to_write: list[dict[str, Any]] = []
    alloc_to_write: list[dict[str, Any]] = []

    # Per-parent tracking for reconciliation
    parent_legacy_docs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    parent_new_invoices: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for doc in legacy_docs:
        payment_id = str(doc.get("payment_id") or doc.get("_id", ""))

        if doc.get("is_deleted"):
            skipped_deleted += 1
            counts["skipped_deleted"] += 1
            continue

        status = (doc.get("status") or "").lower()
        counts[f"status_{status}"] += 1

        parent_id = _parent_id_from(doc) or "unknown"
        parent_legacy_docs[parent_id].append(doc)

        if status not in LEGACY_STATUSES:
            skipped_unknown += 1
            logger.warning("Unknown status %r on payment_id=%s — skipping", status, payment_id)
            continue

        # Idempotency check
        invoice_id = f"inv-from-{payment_id}"
        existing = await db[INVOICES_COLLECTION].find_one({"invoice_id": invoice_id})
        if existing is not None:
            already_backfilled += 1
            # Still track for reconciliation
            parent_new_invoices[parent_id].append(existing)
            continue

        try:
            mapped = map_legacy_payment(doc)
        except Exception as exc:
            errors.append(f"payment_id={payment_id}: {exc}")
            logger.error("Mapping error for payment_id=%s: %s", payment_id, exc)
            continue

        if mapped is None:
            skipped_unknown += 1
            logger.warning("No mapping for payment_id=%s (status=%r)", payment_id, status)
            continue

        invoices_to_write.append(mapped["invoice"])
        lines_to_write.append(mapped["line"])
        parent_new_invoices[parent_id].append(mapped["invoice"])

        if mapped["ledger_payment"] is not None:
            lp_to_write.append(mapped["ledger_payment"])
        if mapped["allocation"] is not None:
            alloc_to_write.append(mapped["allocation"])

    # Write phase
    if not dry_run:
        if invoices_to_write:
            await db[INVOICES_COLLECTION].insert_many(invoices_to_write, ordered=False)
        if lines_to_write:
            await db[INVOICE_LINES_COLLECTION].insert_many(lines_to_write, ordered=False)
        if lp_to_write:
            await db[LEDGER_PAYMENTS_COLLECTION].insert_many(lp_to_write, ordered=False)
        if alloc_to_write:
            await db[ALLOCATIONS_COLLECTION].insert_many(alloc_to_write, ordered=False)

    # ---------------------------------------------------------------------------
    # Print report
    # ---------------------------------------------------------------------------
    mode_label = "[DRY RUN] Would write" if dry_run else "Wrote"

    print("\n=== BACKFILL REPORT ===")
    print(f"Total legacy payments found: {counts['total']}")
    print(f"  succeeded:              {counts.get('status_succeeded', 0)}")
    print(f"  pending:                {counts.get('status_pending', 0)}")
    print(f"  waived:                 {counts.get('status_waived', 0)}")
    print(f"  skipped (deleted):      {skipped_deleted}")
    print(f"  skipped (unknown status): {skipped_unknown}")
    print(f"Already backfilled (idempotent skip): {already_backfilled}")
    print(f"{mode_label}:")
    print(f"  invoices:           {len(invoices_to_write)}")
    print(f"  invoice_lines:      {len(lines_to_write)}")
    print(f"  ledger_payments:    {len(lp_to_write)}")
    print(f"  payment_allocations:{len(alloc_to_write)}")

    # ---------------------------------------------------------------------------
    # Balance reconciliation
    # ---------------------------------------------------------------------------
    print("\n=== BALANCE RECONCILIATION ===")
    header = f"{'Parent':<36} | {'Legacy balance':>14} | {'Ledger balance':>14} | Match?"
    print(header)
    print("-" * len(header))

    total_mismatches = 0
    for parent_id in sorted(parent_legacy_docs.keys()):
        legacy_bal = _legacy_balance_for_parent(parent_legacy_docs[parent_id])
        ledger_bal = _ledger_balance_for_parent(parent_new_invoices.get(parent_id, []))
        match = legacy_bal == ledger_bal
        if not match:
            total_mismatches += 1
        mark = "OK" if match else "MISMATCH"
        short_pid = parent_id[:34]
        print(f"{short_pid:<36} | {legacy_bal:>14} | {ledger_bal:>14} | {mark}")

    print(f"\nTotal mismatches: {total_mismatches}")

    if errors:
        print("\n=== ERRORS ===")
        for err in errors:
            print(f"  ERROR: {err}")

    client.close()
    return len(errors) + total_mismatches


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main(*, academy_id: str, dry_run: bool) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    fatal_count = await run_backfill(academy_id=academy_id, dry_run=dry_run)
    if fatal_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(
        description="Backfill legacy Payment documents into the AR ledger (Phase 4)."
    )
    parser.add_argument("--academy-id", required=True, help="Academy ID to backfill")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without writing to MongoDB",
    )
    args = parser.parse_args()
    asyncio.run(main(academy_id=args.academy_id, dry_run=args.dry_run))
