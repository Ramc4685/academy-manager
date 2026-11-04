"""Report payment allocations left inconsistent by the #931 same-key race.

READ-ONLY. It issues ``find`` calls only: no updates, no deletes, no index
builds, no repairs. Deciding what to do about any row it lists is a manual,
per-case job for the owner.

Before #931, two ``allocate_payment`` callers sharing one allocation
idempotency key could interleave so the loser posted the invoice from the
winner's half-written claim and the winner's rollback then deleted its own
allocation row. The report has three sections:

* ``duplicate_key_groups``: more than one ``payment_allocations`` row under the
  same ``(academy_id, idempotency_key)``. The 0091 unique index should make this
  empty; a non-empty list means the index is missing or was built late (check
  ``index_drift_audit.py``).
* ``posted_invoices_without_allocations``: invoices whose status is ``paid`` or
  ``partially_paid`` with NO allocation row at all, the exact end state #931
  describes. Invoices settled outside the ledger (legacy or Stripe-hosted
  invoices) can also land here, so every row is a candidate for review, not a
  confirmed defect.
* ``stale_pending_claims``: allocation rows still ``allocation_state:
  "pending"`` older than the claim lease (60 s): a caller died between its
  claim and its guarded writes. The next same-key retry heals these; listed so
  a claim nobody retries is not forgotten.

Usage::

    MONGO_URL=... DB_NAME=... python backend/scripts/payment_allocation_claim_audit.py \
        [--academy-id ACADEMY]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

POSTED_STATUSES = ("paid", "partially_paid")
CLAIM_LEASE = timedelta(seconds=60)

_ALLOCATION_FIELDS = (
    "allocation_id",
    "payment_id",
    "invoice_id",
    "amount_cents",
    "allocation_state",
    "claimed_at",
    "created_at",
)
_INVOICE_FIELDS = (
    "invoice_id",
    "parent_id",
    "period",
    "status",
    "total_cents",
    "balance_due_cents",
    "updated_at",
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items() if key != "_id"}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def audit(
    db: Any, *, academy_id: str | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Scan ``payment_allocations`` and posted ``invoices``; write nothing.

    Grouped in Python rather than with ``$group`` so the same code path runs
    under the in-process Mongo the contract tests use.
    """
    now = _as_utc(now or datetime.now(UTC))
    scope: dict[str, Any] = {"academy_id": academy_id} if academy_id else {}

    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    allocated_invoices: set[tuple[str, str]] = set()
    stale_pending: list[dict[str, Any]] = []
    scanned_allocations = 0
    async for doc in db["payment_allocations"].find(scope):
        scanned_allocations += 1
        academy = str(doc.get("academy_id") or "")
        allocated_invoices.add((academy, str(doc.get("invoice_id") or "")))
        key = doc.get("idempotency_key")
        if isinstance(key, str) and key:
            by_key.setdefault((academy, key), []).append(doc)
        claimed_at = doc.get("claimed_at")
        if doc.get("allocation_state") == "pending" and (
            not isinstance(claimed_at, datetime) or _as_utc(claimed_at) + CLAIM_LEASE <= now
        ):
            stale_pending.append(
                {
                    "academy_id": academy,
                    "idempotency_key": key,
                    **{field: _jsonable(doc.get(field)) for field in _ALLOCATION_FIELDS},
                }
            )

    duplicate_groups: list[dict[str, Any]] = []
    for (academy, key), docs in sorted(by_key.items()):
        if len(docs) < 2:
            continue
        docs.sort(key=lambda doc: str(doc.get("allocation_id") or ""))
        duplicate_groups.append(
            {
                "academy_id": academy,
                "idempotency_key": key,
                "row_count": len(docs),
                "surplus_allocated_cents": sum(
                    int(doc.get("amount_cents") or 0) for doc in docs[1:]
                ),
                "allocations": [
                    {field: _jsonable(doc.get(field)) for field in _ALLOCATION_FIELDS}
                    for doc in docs
                ],
            }
        )

    orphaned_invoices: list[dict[str, Any]] = []
    scanned_posted = 0
    async for inv in db["invoices"].find({**scope, "status": {"$in": list(POSTED_STATUSES)}}):
        scanned_posted += 1
        academy = str(inv.get("academy_id") or "")
        if (academy, str(inv.get("invoice_id") or "")) in allocated_invoices:
            continue
        orphaned_invoices.append(
            {
                "academy_id": academy,
                **{field: _jsonable(inv.get(field)) for field in _INVOICE_FIELDS},
            }
        )
    orphaned_invoices.sort(key=lambda row: (row["academy_id"], str(row["invoice_id"])))
    stale_pending.sort(key=lambda row: (row["academy_id"], str(row["allocation_id"])))

    return {
        "academy_id": academy_id,
        "scanned_allocations": scanned_allocations,
        "scanned_posted_invoices": scanned_posted,
        "duplicate_key_group_count": len(duplicate_groups),
        "duplicate_key_groups": duplicate_groups,
        "posted_invoices_without_allocations_count": len(orphaned_invoices),
        "posted_invoices_without_allocations": orphaned_invoices,
        "stale_pending_claim_count": len(stale_pending),
        "stale_pending_claims": stale_pending,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mongo-url", default=os.environ.get("MONGO_URL") or os.environ.get("V2_MONGO_URL")
    )
    parser.add_argument(
        "--db-name", default=os.environ.get("DB_NAME") or os.environ.get("V2_MONGO_DB")
    )
    parser.add_argument("--academy-id", default=None, help="limit the scan to one academy")
    args = parser.parse_args()

    if not args.mongo_url or not args.db_name:
        parser.error("--mongo-url/--db-name or MONGO_URL/DB_NAME is required")

    client = AsyncIOMotorClient(args.mongo_url)
    try:
        report = await audit(client[args.db_name], academy_id=args.academy_id)
        print(json.dumps({"db_name": args.db_name, **report}, indent=2, sort_keys=True))
    finally:
        client.close()
    findings = (
        report["duplicate_key_group_count"]
        + report["posted_invoices_without_allocations_count"]
        + report["stale_pending_claim_count"]
    )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
