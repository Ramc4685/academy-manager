"""Diff a database's live indexes against what the migrations say they are (#836).

Read-only. Production migrations are applied by hand and the database predates
the v2 migrations, so it can carry indexes this repo has never heard of — and
tests, which build a clean database, can never see them. One such index (a
full unique ``(session_id, student_id)`` on ``enrollments``) silently blocked
re-adding a dropped student until #835.

Two steps, because the expected set is built by replaying every migration
against ``mongomock``, which is a dev dependency the production image lacks:

1. On the target (needs only ``motor``)::

       python backend/scripts/index_drift_audit.py --dump > live.json

2. Locally::

       python backend/scripts/index_drift_audit.py --check live.json

Exit status 1 when something needs a decision:

* **missing** — a migration index absent from a collection that exists (a
  collection Mongo has not created yet is reported, not failed);
* **changed** — same name, different key/unique/partial filter;
* **unexpected unique** — a unique index no migration creates and
  ``KNOWN_LEGACY_UNIQUE`` does not explain. Add an entry there only with the
  reason it is harmless; that is the owner's sign-off, in code.

Unexpected NON-unique indexes are listed but never fail: they cost write
throughput, not correctness. Run after every by-hand migration apply.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

IndexSet = dict[str, dict[str, dict[str, Any]]]

#: Unique indexes found in production on 2026-09-20 that no migration creates,
#: each judged inert at the time (#836). Removing one from the database is an
#: owner decision; removing one from this list makes the audit fail until the
#: index is gone.
KNOWN_LEGACY_UNIQUE: dict[str, str] = {
    "payments.enrollment_id_1_period_1": (
        "`payments` is insert-frozen (Phase 5, ledger-native). One doc already "
        "holds (null, null): any new insert without both fields would E11000."
    ),
    "coach_payouts.coach_id_1_period_1": "Pre-v2 collection; empty, unwritten by v2.",
    "invites.token_1": "Pre-v2 collection; empty, unwritten by v2.",
    "payment_refunds.stripe_refund_id_1": "Pre-v2 collection; empty, unwritten by v2.",
    "waiver_acceptances.parent_user_id_1_child_id_1_waiver_version_1": (
        "Partial on `child_id`, a field v2 never writes."
    ),
    "waiver_versions.version_1": (
        "Global on `version`. Single-tenant today; revisit before a second "
        "tenant publishes waivers."
    ),
    "users.email_1": "Overlaps users_normalized_email_unique; every user has an email.",
    "users.auth_provider_1_auth_uid_1": "Partial on legacy auth fields v2 never writes.",
    "legacy_payments_archive.legacy_payment_archive_unique": (
        "Created by backend/scripts/archive_legacy_payments.py, not a migration."
    ),
}


def _shape(spec: dict[str, Any]) -> tuple[Any, ...]:
    key = tuple(
        (name, int(direction) if isinstance(direction, (int, float)) else direction)
        for name, direction in spec.get("key", [])
    )
    partial = json.dumps(spec.get("partial"), sort_keys=True, default=str)
    return (key, bool(spec.get("unique")), partial)


@dataclass
class DriftReport:
    missing: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unexpected_unique: list[str] = field(default_factory=list)
    allowlisted_unique: list[str] = field(default_factory=list)
    unexpected_plain: list[str] = field(default_factory=list)
    absent_collections: list[str] = field(default_factory=list)
    stale_allowlist: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing or self.changed or self.unexpected_unique)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, **self.__dict__}


def diff_indexes(
    live: IndexSet,
    expected: IndexSet,
    known_legacy_unique: dict[str, str] | None = None,
) -> DriftReport:
    allow = KNOWN_LEGACY_UNIQUE if known_legacy_unique is None else known_legacy_unique
    report = DriftReport()

    for collection, indexes in sorted(expected.items()):
        if not indexes:
            continue
        if collection not in live:
            report.absent_collections.append(collection)
            continue
        live_shapes = {_shape(spec) for spec in live[collection].values()}
        for name, spec in sorted(indexes.items()):
            found = live[collection].get(name)
            if found is None:
                # Same definition under another name still does the job.
                if _shape(spec) not in live_shapes:
                    report.missing.append(f"{collection}.{name}")
            elif _shape(found) != _shape(spec):
                report.changed.append(f"{collection}.{name}")

    seen: set[str] = set()
    for collection, indexes in sorted(live.items()):
        wanted = expected.get(collection, {})
        wanted_shapes = {_shape(spec) for spec in wanted.values()}
        for name, spec in sorted(indexes.items()):
            if name in wanted or _shape(spec) in wanted_shapes:
                continue
            ref = f"{collection}.{name}"
            if not spec.get("unique"):
                report.unexpected_plain.append(ref)
            elif ref in allow:
                seen.add(ref)
                report.allowlisted_unique.append(ref)
            else:
                report.unexpected_unique.append(ref)

    report.stale_allowlist = sorted(set(allow) - seen)
    return report


async def dump_indexes(db: Any) -> IndexSet:
    out: IndexSet = {}
    for collection in sorted(await db.list_collection_names()):
        info = await db[collection].index_information()
        out[collection] = {
            name: {
                "key": [[k, d] for k, d in spec.get("key", [])],
                "unique": bool(spec.get("unique")),
                "sparse": bool(spec.get("sparse")),
                "partial": spec.get("partialFilterExpression"),
            }
            for name, spec in info.items()
            if name != "_id_"
        }
    return out


async def expected_indexes() -> IndexSet:
    """Replay every migration against an empty mongomock database."""
    import mongomock_motor

    from backend.v2.migrations import runner

    db: Any = mongomock_motor.AsyncMongoMockClient()["index_drift_expected"]
    for module in runner._discover_migrations():
        await module.up(db)
    return await dump_indexes(db)


async def _dump(args: argparse.Namespace) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient

    if not args.mongo_url or not args.db_name:
        print("--mongo-url/--db-name or MONGO_URL/DB_NAME is required", file=sys.stderr)
        return 2
    client: Any = AsyncIOMotorClient(args.mongo_url)
    try:
        print(json.dumps(await dump_indexes(client[args.db_name]), default=str))
    finally:
        client.close()
    return 0


async def _check(live: IndexSet) -> int:
    report = diff_indexes(live, await expected_indexes())
    print(json.dumps(report.as_dict(), indent=2))
    return 0 if report.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dump", action="store_true", help="print live indexes as JSON")
    mode.add_argument("--check", metavar="LIVE_JSON", help="diff a dump against the migrations")
    parser.add_argument(
        "--mongo-url", default=os.environ.get("MONGO_URL") or os.environ.get("V2_MONGO_URL")
    )
    parser.add_argument(
        "--db-name", default=os.environ.get("DB_NAME") or os.environ.get("V2_MONGO_DB")
    )
    args = parser.parse_args()
    if args.dump:
        return asyncio.run(_dump(args))
    return asyncio.run(_check(json.loads(Path(args.check).read_text())))


if __name__ == "__main__":
    raise SystemExit(main())
