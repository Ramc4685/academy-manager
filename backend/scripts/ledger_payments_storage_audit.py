"""Audit and optionally apply the ADR-0011 ledger payment storage copy.

Default mode is dry-run. It reports how many ledger-shaped rows still exist in
the legacy ``payments`` collection and how many are missing from
``ledger_payments``. Writes happen only with ``--apply`` and use the same
copy-only migration as application startup. This script never deletes from
``payments``.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

_migration = importlib.import_module("backend.v2.migrations.0128_ledger_payments_storage")


async def audit(db: Any) -> dict[str, int]:
    query = _migration._LEDGER_PAYMENT_SHAPE
    source_count = await db["payments"].count_documents(query)
    dest_count = await db["ledger_payments"].count_documents({})
    missing_count = 0
    async for doc in db["payments"].find(query, {"academy_id": 1, "payment_id": 1}):
        exists = await db["ledger_payments"].find_one(
            {"academy_id": doc["academy_id"], "payment_id": doc["payment_id"]},
            {"_id": 1},
        )
        if exists is None:
            missing_count += 1
    return {
        "legacy_ledger_shaped_payments": source_count,
        "ledger_payments": dest_count,
        "missing_from_ledger_payments": missing_count,
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
        "--apply", action="store_true", help="Apply copy-only migration before the final audit."
    )
    args = parser.parse_args()

    if not args.mongo_url or not args.db_name:
        parser.error("--mongo-url/--db-name or MONGO_URL/DB_NAME is required")

    client = AsyncIOMotorClient(args.mongo_url)
    try:
        db = client[args.db_name]
        before = await audit(db)
        if args.apply:
            await _migration.up(db)
        after = await audit(db)
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "db_name": args.db_name,
                    "before": before,
                    "after": after,
                    "deleted_from_payments": 0,
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
