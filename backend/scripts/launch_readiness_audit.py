"""Read-only launch audit for single-academy production hardening.

This script produces JSON evidence for the remaining launch gates that can be
checked from configuration and MongoDB. It does not mutate data. Use it against
staging/prod-like databases before applying the ledger payment migration and
again after the migration has run.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.ledger_payments_storage_audit import (
    audit as audit_ledger_payments,
)

EXPECTED_LAUNCH_FLAGS = {
    "APP_TENANCY_MODE": "single_academy",
    "ENABLE_PLATFORM_ROUTES": "false",
    "ENABLE_OWNER_ROLE": "false",
    "ENABLE_STUDENT_LOGIN": "false",
}

REQUIRED_INDEXES = {
    "academy_memberships": {
        "membership_academy_user_unique",
        "membership_user_status",
        "membership_academy_roles_status",
    },
    "ledger_payments": {
        "academy_ledger_payment_idempotency_unique",
        "academy_ledger_payment_id_unique",
        "academy_ledger_payment_parent_paid_at",
    },
    "stripe_webhook_events": {
        "event_id_unique",
        "stripe_event_admin_status",
    },
    "support_access_grants": {
        "support_access_grants_academy_user_status_expires",
    },
}


def audit_environment(env: Mapping[str, str | None]) -> dict[str, Any]:
    failures: list[dict[str, str | None]] = []
    observed: dict[str, str | None] = {}

    for key, expected in EXPECTED_LAUNCH_FLAGS.items():
        value = _normalized(env.get(key))
        observed[key] = value
        if value != expected:
            failures.append({"key": key, "expected": expected, "actual": value})

    primary_academy_id = _clean(env.get("PRIMARY_ACADEMY_ID"))
    observed["PRIMARY_ACADEMY_ID"] = primary_academy_id
    if not primary_academy_id:
        failures.append(
            {"key": "PRIMARY_ACADEMY_ID", "expected": "non-empty", "actual": primary_academy_id}
        )

    cors_origins = _clean(env.get("CORS_ORIGINS") or env.get("V2_CORS_ORIGINS"))
    observed["CORS_ORIGINS"] = cors_origins
    if not cors_origins or "*" in {origin.strip() for origin in cors_origins.split(",")}:
        failures.append(
            {
                "key": "CORS_ORIGINS",
                "expected": "explicit non-wildcard origin list",
                "actual": cors_origins,
            }
        )

    return {
        "status": "pass" if not failures else "fail",
        "observed": observed,
        "failures": failures,
    }


async def audit_database(db: Any, *, primary_academy_id: str) -> dict[str, Any]:
    ledger = await audit_ledger_payments(db)
    indexes = await audit_required_indexes(db)
    memberships = await audit_parent_memberships(db, primary_academy_id=primary_academy_id)

    failures: list[dict[str, Any]] = []
    if ledger["missing_from_ledger_payments"] != 0:
        failures.append(
            {
                "check": "ledger_payment_storage",
                "message": "ledger-shaped payments are still missing from ledger_payments",
                "missing": ledger["missing_from_ledger_payments"],
            }
        )
    if indexes["missing"]:
        failures.append(
            {
                "check": "required_indexes",
                "message": "required launch indexes are missing",
                "missing": indexes["missing"],
            }
        )

    return {
        "status": "pass" if not failures else "fail",
        "primary_academy_id": primary_academy_id,
        "ledger_payments": ledger,
        "required_indexes": indexes,
        "parent_membership_review": memberships,
        "failures": failures,
    }


async def audit_required_indexes(db: Any) -> dict[str, Any]:
    observed: dict[str, list[str]] = {}
    missing: dict[str, list[str]] = {}

    for collection_name, required in REQUIRED_INDEXES.items():
        indexes = await db[collection_name].index_information()
        names = sorted(str(name) for name in indexes)
        observed[collection_name] = names
        missing_names = sorted(required.difference(names))
        if missing_names:
            missing[collection_name] = missing_names

    return {
        "status": "pass" if not missing else "fail",
        "observed": observed,
        "missing": missing,
    }


async def audit_parent_memberships(db: Any, *, primary_academy_id: str) -> dict[str, Any]:
    query = {
        "academy_id": primary_academy_id,
        "roles": "parent",
        "status": "active",
        "$or": [
            {"invited_by": {"$exists": False}},
            {"invited_by": None},
            {"invited_by": ""},
        ],
    }
    count = await db["academy_memberships"].count_documents(query)
    samples: list[dict[str, Any]] = []
    async for doc in (
        db["academy_memberships"]
        .find(
            query,
            {
                "_id": 0,
                "membership_id": 1,
                "academy_id": 1,
                "user_id": 1,
                "roles": 1,
                "status": 1,
                "invited_by": 1,
                "accepted_at": 1,
            },
        )
        .limit(20)
    ):
        samples.append(doc)

    return {
        "status": "manual_review" if count else "pass",
        "active_parent_memberships_without_inviter": count,
        "sample_limit": 20,
        "samples": samples,
        "note": (
            "Rows here are not automatically unsafe; they lack durable inviter/admin "
            "provenance and should be reviewed before launch."
        ),
    }


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalized(value: str | None) -> str | None:
    cleaned = _clean(value)
    return cleaned.lower() if cleaned is not None else None


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mongo-url", default=os.environ.get("MONGO_URL") or os.environ.get("V2_MONGO_URL")
    )
    parser.add_argument(
        "--db-name", default=os.environ.get("DB_NAME") or os.environ.get("V2_MONGO_DB")
    )
    parser.add_argument(
        "--primary-academy-id",
        default=os.environ.get("PRIMARY_ACADEMY_ID") or os.environ.get("V2_PRIMARY_ACADEMY_ID"),
    )
    parser.add_argument(
        "--env-only",
        action="store_true",
        help="Only check launch environment flags; do not connect to MongoDB.",
    )
    args = parser.parse_args()

    env_audit = audit_environment(os.environ)
    result: dict[str, Any] = {
        "status": env_audit["status"],
        "environment": env_audit,
    }

    primary_academy_id = _clean(args.primary_academy_id)
    if not args.env_only:
        if not args.mongo_url or not args.db_name:
            parser.error("--mongo-url/--db-name or MONGO_URL/DB_NAME is required")
        if not primary_academy_id:
            parser.error("--primary-academy-id or PRIMARY_ACADEMY_ID is required")

        client = AsyncIOMotorClient(args.mongo_url)
        try:
            db = client[args.db_name]
            database_audit = await audit_database(db, primary_academy_id=primary_academy_id)
            result["database"] = database_audit
            if env_audit["status"] == "fail" or database_audit["status"] == "fail":
                result["status"] = "fail"
            else:
                result["status"] = "pass"
        finally:
            client.close()

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
