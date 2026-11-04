"""Pre-flight for switching production to multi-academy mode.

Production runs ``APP_TENANCY_MODE=single_academy``. In that mode a signed-in
user's access comes from their ``users`` row (``academy_id`` + ``roles``) via
``_LegacyUserMembershipAdapter`` in ``backend/v2/main.py``. In SaaS mode it
comes ONLY from ``academy_memberships``. Anyone who registered while the app
ran single-academy (public parent registration never wrote a membership) would
be locked out the moment ``V2_SAAS_MODE=true`` ships.

This script answers "is the data ready for the flip?" and, only when asked,
fixes the one gap it can fix safely:

* every academy has a slug (SaaS resolves ``<slug>.<platform_base_domain>``);
* every academy has at least one active owner membership (the owner daily
  brief and the owner-only settings need one);
* every active user whose ``users`` row names an academy has an active
  membership in that academy (matched on any of its id aliases);
* users with no ``academy_id`` at all are listed (they fall back to the
  default academy in single mode and to nothing in SaaS mode).

Default is READ-ONLY. ``--backfill-memberships --apply`` inserts the missing
memberships (academy roles copied from the user row, ``status: active``) with
``$setOnInsert`` only. It never touches an existing membership: a user with a
suspended, removed or invited row under ANY of their ids is reported, not
backfilled. Disabled or deleted accounts are skipped. Rows that would grant
owner/admin/billing are reported for review and only written with
``--include-privileged``. Without ``--apply`` it prints what it would write.
See ``docs/runbooks/enable-multi-academy.md``.

Usage::

    source backend/.venv/bin/activate
    export MONGO_URL=... DB_NAME=academy_manager
    python -m backend.scripts.multi_academy_preflight            # report, exit 1 if not ready
    python -m backend.scripts.multi_academy_preflight --json
    python -m backend.scripts.multi_academy_preflight --backfill-memberships          # dry run
    python -m backend.scripts.multi_academy_preflight --backfill-memberships --apply  # writes
"""

# ruff: noqa: E402

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

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from typing import get_args

from backend.v2.contexts.identity.domain.models import Role
from backend.v2.shared.ids import new_ulid

SAMPLE = 20
#: Only academy roles become membership roles; anything else on a users row
#: (a stray platform role, a typo) is dropped rather than granted.
ACADEMY_ROLES = frozenset(get_args(Role))
#: Roles that can move money or change other people's access. A backfill never
#: grants these by itself: the row is reported for a human to confirm, and
#: only written with --include-privileged.
PRIVILEGED_ROLES = frozenset({"owner", "admin", "billing"})
_DISABLED_STATUSES = frozenset({"disabled", "inactive", "suspended", "deleted"})


def _aliases(doc: dict[str, Any]) -> set[str]:
    return {
        str(value)
        for value in (doc.get("user_id"), doc.get("auth_uid"), doc.get("firebase_uid"))
        if value
    }


def _roles(doc: dict[str, Any]) -> list[str]:
    roles = doc.get("roles")
    if isinstance(roles, list) and roles:
        raw = {str(role) for role in roles if role}
    else:
        legacy = doc.get("role")
        raw = {str(legacy)} if legacy else set()
    return sorted(raw & ACADEMY_ROLES)


def _is_active(doc: dict[str, Any]) -> bool:
    """Mirrors how auth reads a users row: an explicit global_status wins,
    then a disabled-looking status, then the legacy is_active flag."""
    global_status = doc.get("global_status")
    if isinstance(global_status, str) and global_status.lower() != "active":
        return False
    status = doc.get("status")
    if isinstance(status, str) and status.lower() in _DISABLED_STATUSES:
        return False
    return bool(doc.get("is_active", True))


async def audit(db: Any) -> dict[str, Any]:
    academies = [
        {
            "academy_id": doc.get("academy_id"),
            "slug": doc.get("slug"),
            "primary_domain": doc.get("primary_domain"),
            "status": doc.get("status"),
        }
        async for doc in db["academies"].find(
            {}, {"academy_id": 1, "slug": 1, "primary_domain": 1, "status": 1}
        )
    ]
    academy_ids = {a["academy_id"] for a in academies if a["academy_id"]}

    # Every membership, whatever its status, keyed by (academy, user id). A
    # suspended or removed row must block the backfill, not be shadowed by a
    # new active row under another of the user's ids.
    member_status: dict[str, dict[str, str]] = {}
    owners: dict[str, int] = {}
    async for m in db["academy_memberships"].find(
        {}, {"academy_id": 1, "user_id": 1, "roles": 1, "role": 1, "status": 1}
    ):
        academy_id = str(m.get("academy_id") or "")
        status = str(m.get("status") or "")
        member_status.setdefault(academy_id, {})[str(m.get("user_id") or "")] = status
        if status == "active" and "owner" in _roles(m):
            owners[academy_id] = owners.get(academy_id, 0) + 1

    missing: list[dict[str, Any]] = []
    not_active: list[dict[str, Any]] = []
    orphan_users: list[str] = []
    async for user in db["users"].find(
        {},
        {"user_id": 1, "auth_uid": 1, "firebase_uid": 1, "academy_id": 1, "roles": 1,
         "role": 1, "is_active": 1, "status": 1, "global_status": 1},
    ):
        if not _is_active(user):
            continue
        academy_id = user.get("academy_id")
        if not academy_id:
            orphan_users.append(str(user.get("user_id") or user.get("_id")))
            continue
        aliases = _aliases(user)
        statuses = member_status.get(str(academy_id), {})
        existing = {statuses[a] for a in aliases if a in statuses}
        user_id = str(user.get("user_id") or user.get("auth_uid") or user["_id"])
        if "active" in existing:
            continue
        if existing:
            # Suspended / removed / invited: a decision someone made. Report it;
            # never backfill over it.
            not_active.append(
                {"academy_id": str(academy_id), "user_id": user_id, "statuses": sorted(existing)}
            )
            continue
        roles = _roles(user)
        missing.append(
            {
                "academy_id": str(academy_id),
                "user_id": user_id,
                "aliases": sorted(aliases),
                "roles": roles,
                "privileged": bool(set(roles) & PRIVILEGED_ROLES),
                "academy_exists": str(academy_id) in academy_ids,
            }
        )

    checks = {
        "academies_have_slug": [a["academy_id"] for a in academies if not a["slug"]],
        "academies_have_owner": [a for a in sorted(academy_ids) if not owners.get(a)],
        "users_have_membership": missing,
        "memberships_not_active": not_active,
        "users_without_academy": orphan_users,
    }
    blocking = bool(
        checks["academies_have_slug"]
        or checks["academies_have_owner"]
        or checks["users_have_membership"]
        or checks["memberships_not_active"]
    )
    return {"ready": not blocking, "academies": academies, "checks": checks}


async def backfill_memberships(
    db: Any,
    missing: list[dict[str, Any]],
    *,
    apply: bool,
    include_privileged: bool = False,
) -> dict[str, int]:
    planned = [
        row
        for row in missing
        if row["academy_exists"] and row["roles"] and (include_privileged or not row["privileged"])
    ]
    if not apply:
        return {"would_write": len(planned), "written": 0, "skipped": len(missing) - len(planned)}
    written = 0
    now = datetime.now(UTC)
    for row in planned:
        # Any existing row under ANY of the user's ids blocks the insert.
        result = await db["academy_memberships"].update_one(
            {"academy_id": row["academy_id"], "user_id": {"$in": row["aliases"]}},
            {
                "$setOnInsert": {
                    "membership_id": str(new_ulid()),
                    "academy_id": row["academy_id"],
                    "user_id": row["user_id"],
                    "roles": row["roles"],
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                    "backfilled_by": "multi_academy_preflight",
                }
            },
            upsert=True,
        )
        written += 1 if result.upserted_id is not None else 0
    return {"would_write": len(planned), "written": written, "skipped": len(missing) - len(planned)}


def _print_report(report: dict[str, Any]) -> None:
    checks = report["checks"]
    print(f"Academies: {len(report['academies'])}")
    for academy in report["academies"]:
        print(f"  - {academy['academy_id']}  slug={academy['slug']}  status={academy['status']}")
    rows = [
        ("Every academy has a slug", checks["academies_have_slug"]),
        ("Every academy has an active owner membership", checks["academies_have_owner"]),
        ("Every active user has a membership in their academy", checks["users_have_membership"]),
        ("No active user is blocked by a non-active membership", checks["memberships_not_active"]),
    ]
    for title, failures in rows:
        verdict = "PASS" if not failures else f"FAIL ({len(failures)})"
        print(f"[{verdict}] {title}")
        for item in failures[:SAMPLE]:
            print(f"    {item}")
    orphans = checks["users_without_academy"]
    privileged = [r for r in checks["users_have_membership"] if r["privileged"]]
    if privileged:
        print(
            f"[REVIEW] {len(privileged)} missing membership(s) would grant owner/admin/billing; "
            "confirm each by hand, then pass --include-privileged"
        )
    print(f"[INFO] Active users with no academy_id: {len(orphans)} {orphans[:SAMPLE]}")
    print("READY" if report["ready"] else "NOT READY")


async def _run(args: argparse.Namespace) -> int:
    mongo_url = args.mongo_url or os.environ.get("MONGO_URL")
    db_name = args.db or os.environ.get("DB_NAME") or os.environ.get("V2_MONGO_DB")
    if not mongo_url or not db_name:
        print("MONGO_URL and DB_NAME are required", file=sys.stderr)
        return 2
    client: Any = AsyncIOMotorClient(mongo_url)
    try:
        db = client[db_name]
        report = await audit(db)
        if args.backfill_memberships:
            report["backfill"] = await backfill_memberships(
                db,
                report["checks"]["users_have_membership"],
                apply=args.apply,
                include_privileged=args.include_privileged,
            )
            if args.apply:
                report = {**await audit(db), "backfill": report["backfill"]}
        if args.json:
            print(json.dumps(report, default=str, indent=2))
        else:
            _print_report(report)
            if "backfill" in report:
                print(f"Backfill: {report['backfill']}")
        return 0 if report["ready"] else 1
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mongo-url")
    parser.add_argument("--db")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--backfill-memberships", action="store_true")
    parser.add_argument("--apply", action="store_true", help="write the backfill (default: dry run)")
    parser.add_argument(
        "--include-privileged",
        action="store_true",
        help="also backfill rows granting owner/admin/billing (review the dry run first)",
    )
    args = parser.parse_args(argv)
    if args.apply and not args.backfill_memberships:
        parser.error("--apply only applies to --backfill-memberships")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
