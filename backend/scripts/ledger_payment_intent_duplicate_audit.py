"""Report duplicate ``(academy_id, stripe_payment_intent_id)`` ledger payments (#679).

Read-only. Migration ``0173_ledger_payment_intent_unique_index`` cannot build
its unique index while duplicates exist, and duplicates are exactly what the
webhook-replay bug produced, so run this first.

Each duplicate group lists every payment that shares the intent together with
its ``payment_allocations`` rows and any ``account_credit_ledger`` entry it
generated (overpayment credits are stamped ``source_id=<payment_id>``), which
is what a by-hand reconciliation needs. A clean run — ``duplicate_group_count``
of 0 — is also the answer to whether the bug ever fired in production.

Usage::

    MONGO_URL=... DB_NAME=... python backend/scripts/ledger_payment_intent_duplicate_audit.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

_PAYMENT_FIELDS = (
    "payment_id",
    "parent_id",
    "amount_cents",
    "unapplied_amount_cents",
    "currency",
    "status",
    "payment_method",
    "stripe_invoice_id",
    "paid_at",
    "created_at",
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items() if key != "_id"}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


async def _payment_context(db: Any, doc: dict[str, Any]) -> dict[str, Any]:
    academy_id = doc["academy_id"]
    payment_id = doc["payment_id"]
    allocations = [
        _jsonable(alloc)
        async for alloc in db["payment_allocations"].find(
            {"academy_id": academy_id, "payment_id": payment_id}
        )
    ]
    credits = [
        _jsonable(credit)
        async for credit in db["account_credit_ledger"].find(
            {"academy_id": academy_id, "source_id": payment_id}
        )
    ]
    summary = {field: _jsonable(doc.get(field)) for field in _PAYMENT_FIELDS}
    summary["allocations"] = allocations
    summary["credits"] = credits
    return summary


async def audit(db: Any) -> dict[str, Any]:
    """Group ledger payments by ``(academy_id, stripe_payment_intent_id)``.

    Grouped in Python rather than with ``$group`` so the same code path runs
    under the in-process Mongo the contract tests use.
    """
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    scanned = 0
    async for doc in db["ledger_payments"].find(
        {"stripe_payment_intent_id": {"$type": "string"}}
    ):
        scanned += 1
        key = (doc["academy_id"], doc["stripe_payment_intent_id"])
        grouped.setdefault(key, []).append(doc)

    duplicate_groups: list[dict[str, Any]] = []
    for (academy_id, intent_id), docs in sorted(grouped.items()):
        if len(docs) < 2:
            continue
        docs.sort(key=lambda doc: str(doc.get("payment_id") or ""))
        duplicate_groups.append(
            {
                "academy_id": academy_id,
                "stripe_payment_intent_id": intent_id,
                "payment_count": len(docs),
                "payments": [await _payment_context(db, doc) for doc in docs],
            }
        )

    return {
        "scanned_payments_with_intent": scanned,
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_groups": duplicate_groups,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mongo-url", default=os.environ.get("MONGO_URL") or os.environ.get("V2_MONGO_URL")
    )
    parser.add_argument(
        "--db-name", default=os.environ.get("DB_NAME") or os.environ.get("V2_MONGO_DB")
    )
    args = parser.parse_args()

    if not args.mongo_url or not args.db_name:
        parser.error("--mongo-url/--db-name or MONGO_URL/DB_NAME is required")

    client = AsyncIOMotorClient(args.mongo_url)
    try:
        report = await audit(client[args.db_name])
        print(json.dumps({"db_name": args.db_name, **report}, indent=2, sort_keys=True))
    finally:
        client.close()
    return 1 if report["duplicate_group_count"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
