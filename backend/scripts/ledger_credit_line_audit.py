"""Find monthly invoices whose applied account credit lives only in the header.

Before the ``account_credit`` invoice line existed, the monthly generator spent
a family's account credit on the month's charge and recorded it ONLY as
``total_cents = net - applied_credit``. Any later ``recompute_totals`` (a late
fee, an admin-added line, the ACH autopay discount, the ``create_invoice``
back-fill) rebuilt the total from the lines and so billed the credit again,
while the credit itself stayed consumed.

Read-only by default. Every non-void ``inv-monthly-*`` invoice whose charge
consumed credit (per ``account_credit_ledger.applications``, the source of
truth, or the ``credit_applications`` projection, whichever is larger) and has
no ``account_credit`` line is reported in one of three buckets:

* ``at_risk`` — the header is still net of the credit, so nothing has been
  over-billed YET, but the next recompute will. These are the only invoices
  ``--apply`` touches: it inserts the missing credit line (``$setOnInsert``,
  keyed by a deterministic ``line_id``) and leaves the header alone, because
  the header is already right.
* ``overcharged`` — the header total is above what the lines, the discount
  and the credit add up to. ``overcharged_cents`` is the excess;
  ``collected_excess_cents`` is how much of it has already been paid. Never
  written to: correcting a paid or part-paid invoice is an owner decision
  (refund, credit, or restate).
* ``mismatch`` — the header is BELOW that figure. Usually the separate tuition
  discount double count (branch fix/ledger-discount-double-count), not this
  bug. Reported so nothing is hidden; never written to.

Usage::

    MONGO_URL=... DB_NAME=... python backend/scripts/ledger_credit_line_audit.py
    MONGO_URL=... DB_NAME=... python backend/scripts/ledger_credit_line_audit.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.v2.contexts.billing.domain.ledger import (  # noqa: E402
    ACCOUNT_CREDIT_SOURCE_TYPE,
)

MONTHLY_INVOICE_PREFIX = "inv-monthly-"
MONTHLY_LINE_PREFIX = "line-monthly-"
TUITION_DISCOUNT_SOURCE_TYPE = "tuition_discount"


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def _applied_credit_by_key(db: Any) -> dict[tuple[str, str], int]:
    """``(academy_id, payment_id) -> applied cents``, the larger of both sources."""
    source: dict[tuple[str, str], int] = {}
    async for doc in db["account_credit_ledger"].find(
        {"applications.0": {"$exists": True}}, {"academy_id": 1, "applications": 1}
    ):
        for application in doc.get("applications") or []:
            key = (str(doc.get("academy_id") or ""), str(application.get("invoice_id") or ""))
            source[key] = source.get(key, 0) + _int(application.get("amount_cents"))
    projected: dict[tuple[str, str], int] = {}
    async for doc in db["credit_applications"].find(
        {}, {"academy_id": 1, "invoice_id": 1, "amount_cents": 1}
    ):
        key = (str(doc.get("academy_id") or ""), str(doc.get("invoice_id") or ""))
        projected[key] = projected.get(key, 0) + _int(doc.get("amount_cents"))
    return {
        key: max(source.get(key, 0), projected.get(key, 0)) for key in set(source) | set(projected)
    }


async def audit(db: Any, *, apply: bool = False, now: datetime | None = None) -> dict[str, Any]:
    applied_by_key = await _applied_credit_by_key(db)
    buckets: dict[str, list[dict[str, Any]]] = {"at_risk": [], "overcharged": [], "mismatch": []}
    scanned = 0
    with_credit_line = 0
    lines_inserted = 0
    stamp = now or datetime.now(UTC)

    async for invoice in db["invoices"].find(
        {
            "invoice_id": {"$regex": f"^{MONTHLY_INVOICE_PREFIX}"},
            "status": {"$ne": "void"},
            "is_deleted": {"$ne": True},
        }
    ):
        scanned += 1
        academy_id = str(invoice.get("academy_id") or "")
        invoice_id = str(invoice["invoice_id"])
        tuition_line_id = MONTHLY_LINE_PREFIX + invoice_id[len(MONTHLY_INVOICE_PREFIX) :]
        lines = [
            line
            async for line in db["invoice_lines"].find(
                {"academy_id": academy_id, "invoice_id": invoice_id}
            )
        ]
        if any(line.get("source_type") == ACCOUNT_CREDIT_SOURCE_TYPE for line in lines):
            with_credit_line += 1
            continue
        tuition = next((line for line in lines if line.get("line_id") == tuition_line_id), None)
        payment_id = str((tuition or {}).get("source_id") or "")
        applied = applied_by_key.get((academy_id, payment_id), 0) if payment_id else 0
        if applied <= 0:
            continue

        charges = sum(
            _int(line.get("amount_cents"))
            for line in lines
            if line.get("source_type") != TUITION_DISCOUNT_SOURCE_TYPE
        )
        discount_line = sum(
            abs(_int(line.get("amount_cents")))
            for line in lines
            if line.get("source_type") == TUITION_DISCOUNT_SOURCE_TYPE
        )
        # Generator shape mirrors the discount line in discount_cents; the net
        # shape carries it only on the line; either way it comes off once.
        discount = max(_int(invoice.get("discount_cents")), discount_line)
        expected_total = max(charges - discount - applied, 0)
        total = _int(invoice.get("total_cents"))
        balance = _int(invoice.get("balance_due_cents"))
        allocated = max(total - balance, 0)
        row = {
            "academy_id": academy_id,
            "invoice_id": invoice_id,
            "invoice_number": invoice.get("invoice_number"),
            "parent_id": invoice.get("parent_id"),
            "period": invoice.get("period"),
            "status": invoice.get("status"),
            "payment_id": payment_id,
            "applied_credit_cents": applied,
            "charges_cents": charges,
            "discount_cents": discount,
            "total_cents": total,
            "expected_total_cents": expected_total,
            "balance_due_cents": balance,
            "allocated_cents": allocated,
        }
        if total == expected_total:
            buckets["at_risk"].append(row)
            if apply:
                result = await db["invoice_lines"].update_one(
                    {"academy_id": academy_id, "line_id": f"{tuition_line_id}-credit"},
                    {
                        "$setOnInsert": {
                            "academy_id": academy_id,
                            "line_id": f"{tuition_line_id}-credit",
                            "invoice_id": invoice_id,
                            "line_type": "credit",
                            "description": "Account credit applied",
                            "quantity": 1,
                            "unit_amount_cents": -applied,
                            "amount_cents": -applied,
                            "source_type": ACCOUNT_CREDIT_SOURCE_TYPE,
                            "source_id": payment_id,
                            "created_at": stamp,
                        }
                    },
                    upsert=True,
                )
                if result.upserted_id is not None:
                    lines_inserted += 1
        elif total > expected_total:
            excess = total - expected_total
            buckets["overcharged"].append(
                {
                    **row,
                    "overcharged_cents": excess,
                    "collected_excess_cents": max(allocated - expected_total, 0),
                }
            )
        else:
            buckets["mismatch"].append({**row, "short_cents": expected_total - total})

    return {
        "mode": "apply" if apply else "read_only",
        "scanned_monthly_invoices": scanned,
        "invoices_with_credit_line": with_credit_line,
        "at_risk_count": len(buckets["at_risk"]),
        "overcharged_count": len(buckets["overcharged"]),
        "overcharged_cents": sum(r["overcharged_cents"] for r in buckets["overcharged"]),
        "collected_excess_cents": sum(r["collected_excess_cents"] for r in buckets["overcharged"]),
        "mismatch_count": len(buckets["mismatch"]),
        "credit_lines_inserted": lines_inserted,
        **buckets,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mongo-url", default=os.environ.get("MONGO_URL") or os.environ.get("V2_MONGO_URL")
    )
    parser.add_argument(
        "--db-name", default=os.environ.get("DB_NAME") or os.environ.get("V2_MONGO_DB")
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="insert the missing credit line on at_risk invoices only (header untouched)",
    )
    args = parser.parse_args()

    if not args.mongo_url or not args.db_name:
        parser.error("--mongo-url/--db-name or MONGO_URL/DB_NAME is required")

    client = AsyncIOMotorClient(args.mongo_url)
    try:
        report = await audit(client[args.db_name], apply=args.apply)
        print(json.dumps({"db_name": args.db_name, **report}, indent=2, sort_keys=True))
    finally:
        client.close()
    return 1 if report["overcharged_count"] or report["mismatch_count"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
