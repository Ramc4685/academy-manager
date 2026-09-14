"""Review monthly invoice keys stuck at ``repair_failed`` (#599).

Invoices recovered before PR #494 keep the old shape, and their tuition line
is written with ``$setOnInsert`` — so recovery cannot rewrite them, and every
monthly generation run re-reports the same keys as ``repair_failed`` forever.
This script is how an operator ends that: look at what each key actually
points at, then record a judgement the generator honours.

Read-only by default. It prints, per ``repair_failed`` key, the key itself and
the ledger invoice behind it — header, lines, the payment the key claimed, and
every credit application/ledger entry charged against that payment — which is
what deciding "this invoice is fine, stop flagging it" needs.

``--mark-reviewed`` is the only write, and it touches nothing but
``billing_invoice_keys``: no invoice, line, payment or credit is changed. A
reviewed key is skipped by the generator until the invoice behind it is
modified, at which point the review lapses and the key is flagged again.

Usage::

    MONGO_URL=... DB_NAME=... python backend/scripts/monthly_invoice_key_repair_review.py

    MONGO_URL=... DB_NAME=... python backend/scripts/monthly_invoice_key_repair_review.py \
        --mark-reviewed enr_b53dd4ac66b54db9a75e 2026-07 \
        --reason "pre-#494 shape; invoice and payments verified correct" \
        --reviewed-by ops@example.com
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

from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import (  # noqa: E402
    MONTHLY_KEY_STATUS_REPAIR_FAILED,
    mark_monthly_invoice_key_reviewed,
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items() if key != "_id"}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


async def _find_all(db: Any, collection: str, query: dict[str, Any]) -> list[dict[str, Any]]:
    return [_jsonable(doc) async for doc in db[collection].find(query)]


async def audit(db: Any) -> dict[str, Any]:
    """Every ``repair_failed`` monthly invoice key, with what it points at.

    Scans all academies: this is an ops script run outside a request, so there
    is no tenant context to inherit. Each key's own ``academy_id`` scopes every
    lookup made for it.
    """
    keys: list[dict[str, Any]] = []
    async for key in db["billing_invoice_keys"].find({"status": MONTHLY_KEY_STATUS_REPAIR_FAILED}):
        academy_id = str(key.get("academy_id") or "")
        enrollment_id = str(key.get("enrollment_id") or "")
        period = str(key.get("period") or "")
        payment_id = str(key.get("payment_id") or "")
        invoice_id = f"inv-monthly-{enrollment_id}-{period}"
        invoice = await db["invoices"].find_one(
            {"academy_id": academy_id, "invoice_id": invoice_id}
        )
        keys.append(
            {
                "key": _jsonable(key),
                "invoice_id": invoice_id,
                "invoice": _jsonable(invoice) if invoice is not None else None,
                "invoice_lines": await _find_all(
                    db, "invoice_lines", {"academy_id": academy_id, "invoice_id": invoice_id}
                ),
                # The key's payment_id is what credit was applied against, so
                # allocations are keyed by it rather than by the invoice id.
                "payments": await _find_all(
                    db, "payments", {"academy_id": academy_id, "payment_id": payment_id}
                ),
                "credit_applications": await _find_all(
                    db,
                    "credit_applications",
                    {"academy_id": academy_id, "invoice_id": payment_id},
                ),
                "account_credit_ledger": await _find_all(
                    db,
                    "account_credit_ledger",
                    {"academy_id": academy_id, "invoice_id": payment_id},
                ),
            }
        )
    keys.sort(key=lambda entry: (entry["key"].get("period") or "", entry["invoice_id"]))
    return {"repair_failed_key_count": len(keys), "repair_failed_keys": keys}


async def mark_reviewed(
    db: Any,
    *,
    enrollment_id: str,
    period: str,
    reason: str,
    reviewed_by: str,
    academy_id: str | None,
    now: datetime,
) -> dict[str, Any]:
    """Record a judgement on exactly one ``repair_failed`` key."""
    query: dict[str, Any] = {
        "enrollment_id": enrollment_id,
        "period": period,
        "status": MONTHLY_KEY_STATUS_REPAIR_FAILED,
    }
    if academy_id:
        query["academy_id"] = academy_id
    matches = [doc async for doc in db["billing_invoice_keys"].find(query)]
    if not matches:
        return {"marked": False, "error": "no repair_failed key matches that enrollment/period"}
    if len(matches) > 1:
        return {
            "marked": False,
            "error": "several academies have that enrollment/period; pass --academy-id",
            "academy_ids": sorted(str(doc.get("academy_id") or "") for doc in matches),
        }
    resolved_academy_id = str(matches[0].get("academy_id") or "")
    marked = await mark_monthly_invoice_key_reviewed(
        db,
        academy_id=resolved_academy_id,
        enrollment_id=enrollment_id,
        period=period,
        reason=reason,
        reviewed_by=reviewed_by,
        now=now,
    )
    return {
        "marked": marked,
        "academy_id": resolved_academy_id,
        "enrollment_id": enrollment_id,
        "period": period,
        "reason": reason,
        "reviewed_by": reviewed_by,
        "reviewed_at": now.isoformat(),
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
        "--mark-reviewed",
        nargs=2,
        metavar=("ENROLLMENT_ID", "PERIOD"),
        help="accept one repair_failed key so the generator stops re-reporting it",
    )
    parser.add_argument(
        "--reason", help="why the key is acceptable (required with --mark-reviewed)"
    )
    parser.add_argument("--reviewed-by", default=os.environ.get("USER") or "unknown")
    parser.add_argument(
        "--academy-id", help="disambiguate when two academies share an enrollment id"
    )
    args = parser.parse_args()

    if not args.mongo_url or not args.db_name:
        parser.error("--mongo-url/--db-name or MONGO_URL/DB_NAME is required")
    if args.mark_reviewed and not (args.reason or "").strip():
        parser.error("--reason is required with --mark-reviewed")

    client = AsyncIOMotorClient(args.mongo_url)
    try:
        db = client[args.db_name]
        if args.mark_reviewed:
            enrollment_id, period = args.mark_reviewed
            report = await mark_reviewed(
                db,
                enrollment_id=enrollment_id,
                period=period,
                reason=args.reason.strip(),
                reviewed_by=args.reviewed_by,
                academy_id=args.academy_id,
                now=datetime.now(UTC),
            )
            print(json.dumps({"db_name": args.db_name, **report}, indent=2, sort_keys=True))
            return 0 if report["marked"] else 1
        report = await audit(db)
        print(json.dumps({"db_name": args.db_name, **report}, indent=2, sort_keys=True))
    finally:
        client.close()
    return 1 if report["repair_failed_key_count"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
