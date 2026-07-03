#!/usr/bin/env python3
"""Audit or remove stale tuition subscription setup rows.

This is intentionally dry-run by default. It targets only the old setup-mode
bookkeeping rows left in the tuition `subscriptions` collection after app-owned
autopay moved setup completion off subscription charging.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from typing import Any

_SCRIPTS_DEV_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DEV_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DEV_DIR)

from mongo_guard import assert_local_mongo_url  # noqa: E402

STAGING_DB_NAME = "academy_manager_saas_staging"
DEFAULT_DB_NAME = os.environ.get("SAAS_STAGING_DB_NAME", STAGING_DB_NAME)


def _real_stripe_subscription_id(value: object) -> str | None:
    text = str(value or "").strip()
    return text if text.startswith("sub_") else None


def select_cleanup_candidates(
    subscription_rows: Sequence[Mapping[str, Any]],
    enrollments_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return stale setup-bookkeeping rows safe to remove.

    A candidate must be an incomplete local tuition subscription with no real
    Stripe subscription id, a Checkout session id, and an enrollment that is no
    longer linked to a Stripe subscription.
    """

    candidates: list[dict[str, Any]] = []
    for row in subscription_rows:
        if str(row.get("status") or "") != "incomplete":
            continue
        if str(row.get("stripe_subscription_id") or "").strip():
            continue
        if not str(row.get("stripe_checkout_session_id") or "").strip():
            continue
        enrollment_id = str(row.get("enrollment_id") or "").strip()
        if not enrollment_id:
            continue
        enrollment = enrollments_by_id.get(enrollment_id)
        if enrollment is None:
            continue
        if _real_stripe_subscription_id(enrollment.get("stripe_subscription_id")):
            continue
        candidates.append(dict(row))
    return candidates


def delete_filter(subscription_ids: Sequence[str]) -> dict[str, Any]:
    """Build a defensive delete filter for already-reviewed candidate ids."""

    return {
        "subscription_id": {"$in": list(subscription_ids)},
        "stripe_subscription_id": {"$exists": False},
        "status": "incomplete",
    }


def candidate_subscription_ids(candidates: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return validated subscription ids for destructive cleanup."""

    ids: list[str] = []
    for row in candidates:
        subscription_id = str(row.get("subscription_id") or "").strip()
        if not subscription_id:
            raise SystemExit("candidate missing subscription_id; aborting cleanup")
        ids.append(subscription_id)
    if len(set(ids)) != len(ids):
        raise SystemExit("duplicate candidate subscription_id; aborting cleanup")
    return ids


def build_report(
    *, candidates: Sequence[Mapping[str, Any]], applied: bool
) -> dict[str, Any]:
    rows = [
        {
            "subscription_id": row.get("subscription_id"),
            "academy_id": row.get("academy_id"),
            "parent_id": row.get("parent_id"),
            "enrollment_id": row.get("enrollment_id"),
            "stripe_checkout_session_id": row.get("stripe_checkout_session_id"),
            "created_at": str(row.get("created_at") or ""),
        }
        for row in candidates
    ]
    return {
        "result": "applied" if applied else "dry_run",
        "candidate_count": len(rows),
        "candidates": rows,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mongo-url",
        default=os.environ.get("MONGO_URL"),
        help="MongoDB URL. Defaults to MONGO_URL.",
    )
    parser.add_argument(
        "--db-name",
        default=DEFAULT_DB_NAME,
        help=(
            "Mongo database name. Defaults to SAAS_STAGING_DB_NAME or "
            f"{STAGING_DB_NAME}."
        ),
    )
    parser.add_argument(
        "--academy-id",
        default=None,
        help="Optional academy_id filter.",
    )
    parser.add_argument(
        "--expected-count",
        type=int,
        default=None,
        help="Abort if the candidate count differs.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete the selected stale rows. Dry-run is the default.",
    )
    parser.add_argument(
        "--confirm-delete-stale-subscriptions",
        action="store_true",
        help="Required with --apply.",
    )
    return parser.parse_args(argv)


def _candidate_query(academy_id: str | None) -> dict[str, Any]:
    query: dict[str, Any] = {
        "status": "incomplete",
        "stripe_subscription_id": {"$exists": False},
        "stripe_checkout_session_id": {"$type": "string"},
    }
    if academy_id:
        query["academy_id"] = academy_id
    return query


def run(args: argparse.Namespace) -> int:
    if not args.mongo_url:
        raise SystemExit("MONGO_URL is required via --mongo-url or environment.")
    assert_local_mongo_url(args.mongo_url)
    if args.apply and not args.confirm_delete_stale_subscriptions:
        raise SystemExit("--apply requires --confirm-delete-stale-subscriptions")

    from pymongo import MongoClient

    client: MongoClient[Any] = MongoClient(
        args.mongo_url, serverSelectionTimeoutMS=5_000
    )
    db = client[args.db_name]
    subscription_rows = list(
        db["subscriptions"].find(_candidate_query(args.academy_id))
    )
    enrollment_ids = sorted(
        {
            str(row.get("enrollment_id") or "")
            for row in subscription_rows
            if row.get("enrollment_id")
        }
    )
    enrollment_rows = list(
        db["student_billing_enrollments"].find(
            {"enrollment_id": {"$in": enrollment_ids}},
            {"_id": False, "enrollment_id": True, "stripe_subscription_id": True},
        )
    )
    enrollments_by_id = {str(row["enrollment_id"]): row for row in enrollment_rows}
    candidates = select_cleanup_candidates(subscription_rows, enrollments_by_id)

    if args.expected_count is not None and len(candidates) != args.expected_count:
        report = build_report(candidates=candidates, applied=False)
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        raise SystemExit(
            f"candidate count {len(candidates)} did not match expected {args.expected_count}"
        )

    if args.apply and candidates:
        ids = candidate_subscription_ids(candidates)
        result = db["subscriptions"].delete_many(delete_filter(ids))
        if result.deleted_count != len(ids):
            raise SystemExit(
                f"deleted {result.deleted_count} rows, expected {len(ids)}; investigate manually"
            )
        applied = True
    else:
        applied = False

    print(
        json.dumps(
            build_report(candidates=candidates, applied=applied),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(list(argv or sys.argv[1:])))


if __name__ == "__main__":
    raise SystemExit(main())
