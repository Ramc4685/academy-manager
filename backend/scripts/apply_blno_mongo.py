#!/usr/bin/env python3
"""Apply reviewed BLNO Mongo document bundle to local or production Mongo.

Default mode is dry-run. Writes require ``--apply``. Production writes also
require ``--target production --confirm-production <academy_id>``.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from motor.motor_asyncio import AsyncIOMotorClient

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = REPO_ROOT / ".local" / "blno" / "mongo_documents" / "_mongo_import_bundle.json"
LOCAL_MONGO_HOSTS = {"127.0.0.1", "localhost", "::1", "mongo"}

IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "academies": ("academy_id",),
    "academy_settings": ("settings_id",),
    "billing_policies": ("policy_id",),
    # `email` is unique in both local and prod Mongo. Importing by user_id can
    # collide with an existing admin/parent account for the same email.
    "users": ("email",),
    "academy_memberships": ("membership_id",),
    "sessions": ("session_id",),
    "session_occurrences": ("occurrence_id",),
    "students": ("student_id",),
    "enrollments": ("enrollment_id",),
    "payments": ("payment_id",),
    "payment_events": ("event_id",),
    "attendance": ("attendance_id",),
    "move_log": ("move_id",),
    "expenses": ("expense_id",),
    "coach_rates": ("rate_id",),
    "waiver_templates": ("template_id",),
    "dues_snapshots": ("dues_snapshot_id",),
}

COMPOSITE_FILTERS: dict[str, tuple[str, ...]] = {
    "platform_roles": ("user_id", "role"),
    "payout_rules": ("academy_id", "coach_id", "rule_type"),
    "waiver_versions": ("academy_id", "version"),
    "waiver_acceptances": ("academy_id", "student_id", "waiver_version_id"),
}

DATETIME_FIELDS = {
    "accepted_at",
    "created_at",
    "due_at",
    "end_at",
    "effective_from",
    "effective_until",
    "granted_at",
    "incurred_on",
    "marked_at",
    "moved_at",
    "paid_at",
    "payment_date",
    "published_at",
    "start_at",
    "timestamp",
    "updated_at",
    "waiver_date",
}


def load_bundle(path: str | Path) -> dict[str, Any]:
    bundle_path = Path(path)
    with bundle_path.open(encoding="utf-8") as f:
        bundle = json.load(f)
    if not isinstance(bundle, dict):
        raise SystemExit("Bundle must be a JSON object")
    if not isinstance(bundle.get("manifest"), dict):
        raise SystemExit("Bundle missing manifest object")
    if not isinstance(bundle.get("collections"), dict):
        raise SystemExit("Bundle missing collections object")
    return bundle


def build_upsert_filter(collection: str, doc: Mapping[str, Any]) -> dict[str, Any]:
    fields = IDENTITY_FIELDS.get(collection) or COMPOSITE_FILTERS.get(collection)
    if not fields:
        raise ValueError(f"No upsert identity configured for collection {collection!r}")
    missing = [field for field in fields if doc.get(field) in (None, "")]
    if missing:
        raise ValueError(f"Missing identity fields for {collection}: {', '.join(missing)}")
    return {field: doc[field] for field in fields}


def validate_write_request(
    *,
    target: str,
    mongo_url: str,
    apply: bool,
    confirm_production: str | None,
    academy_id: str,
) -> None:
    if not apply:
        return
    host = (urlparse(mongo_url).hostname or "").lower()
    if target == "local":
        if host not in LOCAL_MONGO_HOSTS:
            raise SystemExit(f"Refusing local write against non-local Mongo host: {host!r}")
        return
    if target == "production":
        if confirm_production != academy_id:
            raise SystemExit(
                "Production apply requires --confirm-production matching academy_id "
                f"{academy_id!r}"
            )
        return
    raise SystemExit(f"Unsupported target: {target}")


def _parse_datetime(value: str) -> datetime | str:
    raw = value.strip()
    if not raw:
        return value
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return value


def coerce_for_mongo(doc: Any, *, key: str | None = None) -> Any:
    if isinstance(doc, list):
        return [coerce_for_mongo(item) for item in doc]
    if isinstance(doc, dict):
        return {k: coerce_for_mongo(v, key=k) for k, v in doc.items()}
    if isinstance(doc, str) and key in DATETIME_FIELDS:
        return _parse_datetime(doc)
    return doc


def collection_counts(bundle: Mapping[str, Any]) -> dict[str, int]:
    collections = bundle["collections"]
    return {name: len(docs) for name, docs in collections.items()}


def override_academy_id(bundle: Mapping[str, Any], academy_id: str) -> dict[str, Any]:
    cloned = copy.deepcopy(bundle)
    cloned["manifest"]["academy_id"] = academy_id
    for docs in cloned["collections"].values():
        if not isinstance(docs, list):
            continue
        for doc in docs:
            if isinstance(doc, dict) and "academy_id" in doc:
                doc["academy_id"] = academy_id
    return cloned


async def apply_bundle(db: Any, bundle: Mapping[str, Any], *, dry_run: bool) -> dict[str, int]:
    results: dict[str, int] = {}
    for collection, docs in bundle["collections"].items():
        if not isinstance(docs, list):
            raise SystemExit(f"Collection {collection!r} must contain a list of documents")
        count = 0
        for raw_doc in docs:
            if not isinstance(raw_doc, dict):
                raise SystemExit(f"Collection {collection!r} contains a non-object document")
            selector = build_upsert_filter(collection, raw_doc)
            if not dry_run:
                doc = coerce_for_mongo(raw_doc)
                await db[collection].replace_one(selector, doc, upsert=True)
            count += 1
        results[collection] = count
    return results


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle", default=str(DEFAULT_BUNDLE), help="Path to _mongo_import_bundle.json"
    )
    parser.add_argument(
        "--mongo-url", default=os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
    )
    parser.add_argument("--db-name", default=os.environ.get("DB_NAME", "academy_manager_local"))
    parser.add_argument("--target", choices=["local", "production"], default="local")
    parser.add_argument(
        "--apply", action="store_true", help="Actually write to Mongo. Omit for dry-run."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Explicit no-write mode; this is the default."
    )
    parser.add_argument(
        "--academy-id-override",
        default=None,
        help="Rewrite academy_id in memory before applying. Useful for local default-academy testing.",
    )
    parser.add_argument(
        "--confirm-production",
        default=None,
        help="Required for production apply; must equal manifest academy_id.",
    )
    args = parser.parse_args()

    bundle = load_bundle(args.bundle)
    if args.academy_id_override:
        bundle = override_academy_id(bundle, args.academy_id_override)
    manifest = bundle["manifest"]
    academy_id = str(manifest.get("academy_id") or "")
    if not academy_id:
        raise SystemExit("Bundle manifest missing academy_id")

    validate_write_request(
        target=args.target,
        mongo_url=args.mongo_url,
        apply=args.apply,
        confirm_production=args.confirm_production,
        academy_id=academy_id,
    )

    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "target": args.target,
                "db_name": args.db_name,
                "academy_id": academy_id,
                "counts": collection_counts(bundle),
            },
            indent=2,
        )
    )
    if not args.apply:
        return

    client = AsyncIOMotorClient(args.mongo_url)
    try:
        db = client[args.db_name]
        results = await apply_bundle(db, bundle, dry_run=False)
    finally:
        client.close()
    print(json.dumps({"applied": results}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
