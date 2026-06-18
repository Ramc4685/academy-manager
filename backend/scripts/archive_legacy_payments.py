"""Archive and remove legacy ``payments`` rows after ledger backfill.

This is the final Phase 5 cleanup step. It is deliberately not part of app
startup migrations because it deletes rows from the old collection. Run it only
after ``backfill_p4_legacy_payments`` and launch-readiness reconciliation pass.

Dry run:
    python -m backend.scripts.archive_legacy_payments --academy-id blno

Apply:
    python -m backend.scripts.archive_legacy_payments --academy-id blno --apply
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
from pymongo.errors import DuplicateKeyError

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.backfill_p4_legacy_payments import is_legacy_payment  # noqa: E402

PAYMENTS_COLLECTION = "payments"
ARCHIVE_COLLECTION = "legacy_payments_archive"


async def archive_legacy_payments(
    db: Any,
    *,
    academy_id: str,
    apply: bool,
) -> dict[str, Any]:
    await db[ARCHIVE_COLLECTION].create_index(
        [("academy_id", 1), ("payment_id", 1)],
        unique=True,
        name="legacy_payment_archive_unique",
        partialFilterExpression={"payment_id": {"$type": "string"}},
    )

    blockers: list[dict[str, str]] = []
    archiveable: list[dict[str, Any]] = []
    ledger_shaped = 0
    legacy_shaped = 0

    cursor = db[PAYMENTS_COLLECTION].find({"academy_id": academy_id})
    async for doc in cursor:
        payment_id = str(doc.get("payment_id") or doc.get("_id") or "")
        if not payment_id:
            blockers.append({"payment_id": "", "reason": "payment_id missing"})
            continue

        if is_legacy_payment(doc):
            legacy_shaped += 1
            invoice = await db["invoices"].find_one(
                {
                    "academy_id": academy_id,
                    "$or": [
                        {"invoice_id": f"inv-from-{payment_id}"},
                        {"backfill_payment_id": payment_id},
                    ],
                },
                {"_id": 1},
            )
            if invoice is None:
                blockers.append(
                    {
                        "payment_id": payment_id,
                        "reason": "legacy payment has no backfilled ledger invoice",
                    }
                )
                continue
        else:
            ledger_shaped += 1
            copied = await db["ledger_payments"].find_one(
                {"academy_id": academy_id, "payment_id": payment_id},
                {"_id": 1},
            )
            if copied is None:
                blockers.append(
                    {
                        "payment_id": payment_id,
                        "reason": "ledger-shaped payment was not copied to ledger_payments",
                    }
                )
                continue

        archiveable.append(doc)

    archived = 0
    deleted = 0
    if apply and not blockers:
        archived_at = datetime.now(UTC)
        for doc in archiveable:
            original_id = doc.pop("_id", None)
            archive_doc = {
                **doc,
                "original_id": original_id,
                "archived_at": archived_at,
                "archive_reason": "legacy_payment_collection_retired",
                "original_collection": PAYMENTS_COLLECTION,
            }
            try:
                await db[ARCHIVE_COLLECTION].insert_one(archive_doc)
                archived += 1
            except DuplicateKeyError:
                # Idempotent rerun: the archive row already exists.
                pass
            result = await db[PAYMENTS_COLLECTION].delete_one(
                {"academy_id": academy_id, "payment_id": archive_doc["payment_id"]}
            )
            deleted += int(getattr(result, "deleted_count", 0))

    return {
        "academy_id": academy_id,
        "mode": "apply" if apply else "dry-run",
        "legacy_shaped": legacy_shaped,
        "ledger_shaped": ledger_shaped,
        "archiveable": len(archiveable),
        "archived": archived,
        "deleted_from_payments": deleted,
        "blockers": blockers,
        "status": "blocked" if blockers else "ready",
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mongo-url", default=os.environ.get("MONGO_URL") or os.environ.get("V2_MONGO_URL")
    )
    parser.add_argument(
        "--db-name", default=os.environ.get("DB_NAME") or os.environ.get("V2_MONGO_DB")
    )
    parser.add_argument("--academy-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.mongo_url or not args.db_name:
        parser.error("--mongo-url/--db-name or MONGO_URL/DB_NAME is required")

    client = AsyncIOMotorClient(args.mongo_url)
    try:
        result = await archive_legacy_payments(
            client[args.db_name],
            academy_id=args.academy_id,
            apply=args.apply,
        )
    finally:
        client.close()

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 1 if result["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
