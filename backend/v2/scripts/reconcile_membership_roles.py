"""Reconcile ``academy_memberships.roles`` against the ``users`` directory.

PR #502 made role replacements/removals mirror into ``academy_memberships``
(the collection ``LoadAuthClaims`` builds SaaS claims from), but shipped no
backfill: a demotion applied BEFORE that fix rewrote only the ``users`` doc,
so the membership row still serves the old, higher role — live admin claims
for staff the directory says are parents (issue #508).

This script walks every ``users`` doc, resolves its membership rows through
the same alias set and ownership check the write path uses
(``MongoUserRepository._membership_aliases`` / ``_membership_is_foreign``),
and reports each membership row whose privilege ceiling exceeds the
directory's. With ``--fix`` it rewrites those rows — by their own ``_id``,
never by the alias filter — to the directory's role list.

Alias collisions fail closed, exactly as ``_replace_membership_roles`` does:
every correction here is a narrowing, and a foreign-owned row that matched
the alias query is one auth can still resolve, so an account whose alias set
collides with another account's primary ``user_id`` is reported and left for
a human instead of half-corrected.

Usage::

    python -m backend.v2.scripts.reconcile_membership_roles              # report only
    python -m backend.v2.scripts.reconcile_membership_roles --fix        # correct
    python -m backend.v2.scripts.reconcile_membership_roles --academy-id X --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.identity.domain.errors import RoleRevocationFailed
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import (
    _ROLE_PRIVILEGE,
    MongoUserRepository,
)

_INACTIVE_STATUSES = frozenset({"inactive", "disabled", "terminated", "suspended"})


def _privilege_ceiling(roles: list[str]) -> int:
    return max((_ROLE_PRIVILEGE.get(r, 0) for r in roles), default=0)


def _directory_roles(doc: dict[str, Any]) -> list[str]:
    roles = doc.get("roles")
    if isinstance(roles, str):
        return [roles]
    if isinstance(roles, list | tuple):
        return [str(r) for r in roles if r]
    legacy = doc.get("role")
    return [str(legacy)] if legacy else []


def _directory_inactive(doc: dict[str, Any]) -> bool:
    status = str(doc.get("status") or "").lower()
    if status in _INACTIVE_STATUSES:
        return True
    return not bool(doc.get("is_active", True))


@dataclass
class StaleMembership:
    """A membership row granting more privilege than the directory shows."""

    academy_id: str
    user_id: str
    membership_id: str
    membership_user_id: str
    membership_roles: list[str]
    membership_status: str
    directory_roles: list[str]
    directory_status: str
    directory_inactive: bool
    corrected: bool = False
    skipped_reason: str | None = None


@dataclass
class AliasCollision:
    """An account whose alias set matched rows owned by another account.

    Corrections for this account are withheld (fail closed): the foreign row
    is still resolvable by ``LoadAuthClaims`` through the same alias set, so a
    partial correction would report the stale grant fixed while auth can keep
    serving it.
    """

    academy_id: str
    user_id: str
    foreign_membership_ids: list[str]
    stale_membership_ids: list[str]


@dataclass
class OrphanMembership:
    """A membership row no ``users`` doc in its academy resolves to.

    There is no directory truth to reconcile it against, so it is reported
    for a human — a privileged orphan row is exactly the shape of grant this
    audit exists to surface.
    """

    academy_id: str
    membership_id: str
    membership_user_id: str
    roles: list[str]
    status: str


@dataclass
class ReconcileReport:
    stale: list[StaleMembership] = field(default_factory=list)
    collisions: list[AliasCollision] = field(default_factory=list)
    orphans: list[OrphanMembership] = field(default_factory=list)
    users_scanned: int = 0
    memberships_scanned: int = 0
    fixed: int = 0

    def sort(self) -> None:
        # Terminated/inactive accounts first — nobody is watching those, so a
        # stale admin grant there is the longest-lived exposure — then by how
        # much privilege the row over-grants.
        self.stale.sort(
            key=lambda s: (
                0 if s.directory_inactive else 1,
                -(_privilege_ceiling(s.membership_roles) - _privilege_ceiling(s.directory_roles)),
                s.academy_id,
                s.membership_id,
            )
        )


async def reconcile(
    db: Any,
    *,
    academy_id: str | None = None,
    fix: bool = False,
    now: datetime | None = None,
) -> ReconcileReport:
    now = now or datetime.now(UTC)
    repo = MongoUserRepository(db)
    memberships = db["academy_memberships"]
    report = ReconcileReport()

    scope: dict[str, Any] = {"academy_id": academy_id} if academy_id else {}
    claimed_ids: set[Any] = set()

    async for doc in db["users"].find(scope):
        report.users_scanned += 1
        doc_academy = str(doc.get("academy_id") or "")
        if not doc_academy:
            continue
        aliases = list(repo._membership_aliases(doc))
        if not aliases:
            continue
        rows = [
            row
            async for row in memberships.find(
                {"academy_id": doc_academy, "user_id": {"$in": aliases}}
            )
        ]

        resolved_user_id = repo._to_domain(doc).user_id
        dir_roles = _directory_roles(doc)
        dir_ceiling = _privilege_ceiling(dir_roles)

        owned: list[dict[str, Any]] = []
        foreign: list[dict[str, Any]] = []
        for row in rows:
            if await repo._membership_is_foreign(row, doc):
                foreign.append(row)
            else:
                owned.append(row)
                claimed_ids.add(row["_id"])

        stale_rows = [
            row
            for row in owned
            if _privilege_ceiling([str(r) for r in row.get("roles") or []]) > dir_ceiling
        ]
        if not stale_rows:
            continue

        collision = bool(foreign)
        empty_directory = not dir_roles
        for row in stale_rows:
            entry = StaleMembership(
                academy_id=doc_academy,
                user_id=resolved_user_id,
                membership_id=str(row.get("membership_id") or row["_id"]),
                membership_user_id=str(row.get("user_id") or ""),
                membership_roles=[str(r) for r in row.get("roles") or []],
                membership_status=str(row.get("status") or ""),
                directory_roles=dir_roles,
                directory_status=str(doc.get("status") or ""),
                directory_inactive=_directory_inactive(doc),
            )
            if collision:
                entry.skipped_reason = "alias-collision"
            elif empty_directory:
                # Correcting to an empty role list is a distinct, destructive
                # decision (it revokes everything); surface it, don't automate it.
                entry.skipped_reason = "empty-directory-roles"
            report.stale.append(entry)

        if collision:
            report.collisions.append(
                AliasCollision(
                    academy_id=doc_academy,
                    user_id=resolved_user_id,
                    foreign_membership_ids=[
                        str(r.get("membership_id") or r["_id"]) for r in foreign
                    ],
                    stale_membership_ids=[
                        str(r.get("membership_id") or r["_id"]) for r in stale_rows
                    ],
                )
            )
            continue
        if empty_directory or not fix:
            continue

        result = await memberships.update_many(
            {"_id": {"$in": [row["_id"] for row in stale_rows]}},
            {"$set": {"roles": dir_roles, "updated_at": now}},
        )
        if getattr(result, "matched_count", 0) != len(stale_rows):
            raise RoleRevocationFailed(
                f"membership reconciliation for {resolved_user_id} in {doc_academy} "
                f"matched {getattr(result, 'matched_count', 0)} of {len(stale_rows)} rows"
            )
        for entry in report.stale:
            if entry.user_id == resolved_user_id and entry.academy_id == doc_academy:
                entry.corrected = True
        report.fixed += len(stale_rows)

    async for row in memberships.find(scope):
        report.memberships_scanned += 1
        if row["_id"] in claimed_ids:
            continue
        row_academy = str(row.get("academy_id") or "")
        key = str(row.get("user_id") or "")
        owner = await db["users"].find_one({"academy_id": row_academy, "user_id": key})
        if owner is not None:
            # Alias-owned by an account processed above (foreign to some other
            # doc's alias set, but keyed by its own primary user_id) — the
            # owner pass already compared it.
            continue
        report.orphans.append(
            OrphanMembership(
                academy_id=row_academy,
                membership_id=str(row.get("membership_id") or row["_id"]),
                membership_user_id=key,
                roles=[str(r) for r in row.get("roles") or []],
                status=str(row.get("status") or ""),
            )
        )

    report.sort()
    return report


def _print_report(report: ReconcileReport, *, fix: bool, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {
                    "users_scanned": report.users_scanned,
                    "memberships_scanned": report.memberships_scanned,
                    "fixed": report.fixed,
                    "stale": [asdict(s) for s in report.stale],
                    "collisions": [asdict(c) for c in report.collisions],
                    "orphans": [asdict(o) for o in report.orphans],
                },
                indent=2,
                default=str,
            )
        )
        return
    mode = "FIX" if fix else "DRY RUN"
    print(
        f"[{mode}] scanned {report.users_scanned} users / "
        f"{report.memberships_scanned} membership rows; "
        f"{len(report.stale)} stale, {report.fixed} corrected, "
        f"{len(report.collisions)} alias collisions, {len(report.orphans)} orphans"
    )
    for s in report.stale:
        flag = "INACTIVE " if s.directory_inactive else ""
        outcome = (
            "corrected"
            if s.corrected
            else (f"SKIPPED ({s.skipped_reason})" if s.skipped_reason else "would correct")
        )
        print(
            f"  {flag}{s.academy_id} {s.user_id} membership={s.membership_id} "
            f"roles {s.membership_roles} -> directory {s.directory_roles} [{outcome}]"
        )
    for c in report.collisions:
        print(
            f"  COLLISION {c.academy_id} {c.user_id}: foreign rows "
            f"{c.foreign_membership_ids} block correcting {c.stale_membership_ids} "
            "(fail closed — needs a human)"
        )
    for o in report.orphans:
        print(
            f"  ORPHAN {o.academy_id} membership={o.membership_id} "
            f"user_id={o.membership_user_id} roles={o.roles} status={o.status}"
        )


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="apply corrections")
    parser.add_argument("--academy-id", default=None, help="limit to one academy")
    parser.add_argument("--json", action="store_true", help="emit a JSON report")
    args = parser.parse_args()

    from motor.motor_asyncio import AsyncIOMotorClient

    from backend.v2.shared.config import get_settings

    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongo_url)
    try:
        report = await reconcile(
            client[settings.mongo_db], academy_id=args.academy_id, fix=args.fix
        )
        _print_report(report, fix=args.fix, as_json=args.json)
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(_main())
