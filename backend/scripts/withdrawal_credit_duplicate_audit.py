"""Report duplicate approved early-withdrawal credits per enrollment (#690).

Read-only. Migration ``0174_early_withdrawal_credit_unique_index`` cannot
build its unique index while duplicates exist, and duplicates are exactly
what the check-then-create race produced, so run this first.

Each duplicate group lists every APPROVED ``EARLY_WITHDRAWAL_CREDIT`` an
enrollment holds, with the amount, the balance still spendable and any
recorded applications — which is what deciding "void this one" by hand
needs. ``surplus_remaining_cents`` is the money at risk in that group: the
balance of every credit past the first. A clean run —
``duplicate_group_count`` of 0 — is also the answer to whether the race
ever fired in production.

Usage::

    MONGO_URL=... DB_NAME=... python backend/scripts/withdrawal_credit_duplicate_audit.py
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

EARLY_WITHDRAWAL_CREDIT_TYPE = "EARLY_WITHDRAWAL_CREDIT"
APPROVED_STATUS = "APPROVED"

_CREDIT_FIELDS = (
    "credit_id",
    "parent_id",
    "student_id",
    "enrollment_id",
    "amount_cents",
    "remaining_amount_cents",
    "currency",
    "reason",
    "approved_by",
    "approved_at",
    "expires_at",
    "created_at",
    "applications",
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items() if key != "_id"}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


async def audit(db: Any) -> dict[str, Any]:
    """Group approved withdrawal credits by ``(academy_id, enrollment_id)``.

    Grouped in Python rather than with ``$group`` so the same code path runs
    under the in-process Mongo the contract tests use.
    """
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    scanned = 0
    async for doc in db["account_credit_ledger"].find(
        {
            "type": EARLY_WITHDRAWAL_CREDIT_TYPE,
            "status": APPROVED_STATUS,
            "enrollment_id": {"$type": "string"},
        }
    ):
        scanned += 1
        key = (doc["academy_id"], doc["enrollment_id"])
        grouped.setdefault(key, []).append(doc)

    duplicate_groups: list[dict[str, Any]] = []
    for (academy_id, enrollment_id), docs in sorted(grouped.items()):
        if len(docs) < 2:
            continue
        docs.sort(key=lambda doc: str(doc.get("credit_id") or ""))
        credits = [{field: _jsonable(doc.get(field)) for field in _CREDIT_FIELDS} for doc in docs]
        duplicate_groups.append(
            {
                "academy_id": academy_id,
                "enrollment_id": enrollment_id,
                "credit_count": len(docs),
                "surplus_remaining_cents": sum(
                    int(doc.get("remaining_amount_cents") or 0) for doc in docs[1:]
                ),
                "credits": credits,
            }
        )

    return {
        "scanned_approved_withdrawal_credits": scanned,
        "duplicate_group_count": len(duplicate_groups),
        "surplus_remaining_cents": sum(
            group["surplus_remaining_cents"] for group in duplicate_groups
        ),
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
