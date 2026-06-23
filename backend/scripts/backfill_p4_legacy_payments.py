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
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

if __file__.startswith("<"):
    ROOT = Path.cwd()
else:
    ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "backend" / ".env")

import motor.motor_asyncio  # noqa: E402

from backend.v2.shared.config import get_settings  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PAID_STATUSES = {"succeeded", "paid"}
OPEN_STATUSES = {"pending", "failed", "unpaid", "expired"}
PARTIAL_STATUSES = {"partially_paid", "partial"}
VOID_STATUSES = {"waived"}
LEGACY_STATUSES = PAID_STATUSES | OPEN_STATUSES | PARTIAL_STATUSES | VOID_STATUSES
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


def _int_cents(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise ValueError(f"Invalid cents value: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise ValueError(f"Invalid cents value: {value!r}")
    if isinstance(value, Decimal):
        raise ValueError(f"Invalid cents value: {value!r}")
    if isinstance(value, str):
        trimmed = value.strip()
        if not trimmed:
            raise ValueError(f"Invalid cents value: {value!r}")
        if trimmed.startswith(("+", "-")):
            if not trimmed[1:].isdigit():
                raise ValueError(f"Invalid cents value: {value!r}")
            return int(trimmed)
        if not trimmed.isdigit():
            raise ValueError(f"Invalid cents value: {value!r}")
        return int(trimmed)
    raise ValueError(f"Invalid cents value: {value!r}")


def _legacy_total_cents(doc: dict[str, Any]) -> int:
    if doc.get("final_amount_cents") is not None:
        return max(_int_cents(doc.get("final_amount_cents")), 0)
    amount_cents = _int_cents(doc.get("amount_cents"))
    discount_cents = _int_cents(doc.get("discount_cents"))
    return max(amount_cents - discount_cents, 0)


def _legacy_paid_cents(doc: dict[str, Any], *, total_cents: int, status: str) -> int:
    explicit_paid = doc.get("amount_received_cents")
    if explicit_paid is None:
        explicit_paid = doc.get("paid_amount_cents")
    if status in PAID_STATUSES:
        if explicit_paid is None:
            return total_cents
        if isinstance(explicit_paid, str):
            if explicit_paid.strip() in {"", "0"}:
                return total_cents
        elif (
            isinstance(explicit_paid, int)
            and not isinstance(explicit_paid, bool)
            and explicit_paid == 0
        ):
            return total_cents
    return max(_int_cents(explicit_paid), 0)


def _invoice_status_from_legacy(status: str, *, total_cents: int, paid_cents: int) -> str:
    if status in VOID_STATUSES:
        return "void"
    if total_cents == 0 or paid_cents >= total_cents:
        return "paid"
    if paid_cents > 0 or status in PARTIAL_STATUSES:
        return "partially_paid"
    return "open"


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
    amount_cents: int = _int_cents(doc.get("amount_cents"))
    discount_cents: int = _int_cents(doc.get("discount_cents"))
    has_final_amount: bool = doc.get("final_amount_cents") is not None
    total_cents: int = _legacy_total_cents(doc)
    paid_cents = _legacy_paid_cents(doc, total_cents=total_cents, status=status)
    balance_due_cents = 0 if status in VOID_STATUSES else max(total_cents - paid_cents, 0)
    invoice_status = _invoice_status_from_legacy(
        status,
        total_cents=total_cents,
        paid_cents=paid_cents,
    )
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

    invoice: dict[str, Any] = {
        "invoice_id": invoice_id,
        "invoice_number": doc.get("invoice_number") or invoice_id,
        "academy_id": doc["academy_id"],
        "parent_id": parent_id,
        "student_id": doc.get("student_id"),
        "enrollment_id": doc.get("enrollment_id"),
        "period": period,
        "status": invoice_status,
        "subtotal_cents": total_cents if has_final_amount else amount_cents,
        "discount_cents": 0 if has_final_amount else discount_cents,
        "total_cents": total_cents,
        "balance_due_cents": balance_due_cents,
        "currency": currency,
        "due_date": datetime.combine(_due_date_from(doc), time.min, tzinfo=UTC),
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
        "unit_amount_cents": total_cents if has_final_amount else amount_cents,
        "amount_cents": total_cents if has_final_amount else amount_cents,
        "source_type": "legacy_payment",
        "source_id": payment_id,
        "created_at": created_at,
    }

    ledger_payment: dict[str, Any] | None = None
    allocation: dict[str, Any] | None = None

    if paid_cents > 0 and status not in VOID_STATUSES:
        lp_payment_id = f"lp-from-{payment_id}"
        lp_amount_cents = paid_cents
        allocation_amount_cents = min(paid_cents, total_cents)
        unapplied_amount_cents = max(paid_cents - allocation_amount_cents, 0)
        paid_at: datetime = doc.get("paid_at") or created_at
        if paid_at.tzinfo is None:
            paid_at = paid_at.replace(tzinfo=UTC)

        ledger_payment = {
            "payment_id": lp_payment_id,
            "academy_id": doc["academy_id"],
            "parent_id": parent_id,
            "amount_cents": lp_amount_cents,
            "unapplied_amount_cents": unapplied_amount_cents,
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
            "amount_cents": allocation_amount_cents,
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
    """Sum of legacy unpaid balances across open/partial legacy payment docs."""
    total = 0
    for doc in docs:
        status = (doc.get("status") or "").lower()
        if status in PAID_STATUSES | VOID_STATUSES:
            continue
        if status not in OPEN_STATUSES | PARTIAL_STATUSES:
            continue
        total_cents = _legacy_total_cents(doc)
        paid_cents = _legacy_paid_cents(doc, total_cents=total_cents, status=status)
        total += max(total_cents - paid_cents, 0)
    return total


def _ledger_balance_for_parent(invoices: list[dict[str, Any]]) -> int:
    return sum(int(inv.get("balance_due_cents") or 0) for inv in invoices)


def _status_keys_from_counts(counts: dict[str, int]) -> list[str]:
    status_keys = []
    for key in counts:
        if key.startswith("status_"):
            status_keys.append(key.removeprefix("status_"))
    return sorted(status_keys)


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
    try:
        result = await backfill_legacy_payments(
            db,
            academy_id=academy_id,
            dry_run=dry_run,
        )
    finally:
        client.close()
    return result["fatal_count"]


async def backfill_legacy_payments(
    db: Any,
    *,
    academy_id: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Run a single backfill pass against an injected database.

    Returns a result payload including fatal_count and already_backfilled.
    """
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

        if status not in LEGACY_STATUSES:
            skipped_unknown += 1
            logger.warning("Unknown status %r on payment_id=%s — skipping", status, payment_id)
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

        parent_legacy_docs[parent_id].append(doc)
        invoice = mapped["invoice"]
        line = mapped["line"]

        existing_invoice = await db[INVOICES_COLLECTION].find_one(
            {"academy_id": academy_id, "invoice_id": invoice["invoice_id"]}
        )
        if existing_invoice is not None:
            parent_new_invoices[parent_id].append(existing_invoice)
        else:
            invoices_to_write.append(invoice)
            parent_new_invoices[parent_id].append(invoice)

        existing_line = await db[INVOICE_LINES_COLLECTION].find_one(
            {"academy_id": academy_id, "line_id": line["line_id"]}
        )
        if existing_line is None:
            lines_to_write.append(line)

        ledger_payment = mapped["ledger_payment"]
        has_existing_ledger_payment = False
        if ledger_payment is not None:
            existing_lp = await db[LEDGER_PAYMENTS_COLLECTION].find_one(
                {"academy_id": academy_id, "payment_id": ledger_payment["payment_id"]}
            )
            if existing_lp is not None:
                has_existing_ledger_payment = True
            else:
                lp_to_write.append(ledger_payment)

        allocation = mapped["allocation"]
        has_existing_allocation = False
        if allocation is not None:
            existing_allocation = await db[ALLOCATIONS_COLLECTION].find_one(
                {"academy_id": academy_id, "allocation_id": allocation["allocation_id"]}
            )
            if existing_allocation is not None:
                has_existing_allocation = True
            else:
                alloc_to_write.append(allocation)

        has_existing_line = existing_line is not None
        if (
            existing_invoice is not None
            and has_existing_line
            and (ledger_payment is None or has_existing_ledger_payment)
            and (allocation is None or has_existing_allocation)
        ):
            already_backfilled += 1

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
    for status in _status_keys_from_counts(counts):
        print(f"  {status:<16} {counts.get(f'status_{status}', 0):>4}")
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

    fatal_count = len(errors) + total_mismatches
    return {
        "fatal_count": fatal_count,
        "already_backfilled": already_backfilled,
        "counts": counts,
        "skipped_deleted": skipped_deleted,
        "skipped_unknown_status": skipped_unknown,
        "to_write": {
            "invoices": len(invoices_to_write),
            "invoice_lines": len(lines_to_write),
            "ledger_payments": len(lp_to_write),
            "allocations": len(alloc_to_write),
        },
        "total_mismatches": total_mismatches,
    }


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
