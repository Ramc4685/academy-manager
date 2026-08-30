"""Contract tests for the membership-role reconciliation script (issue #508).

PR #502 stopped NEW demotions from leaving stale ``academy_memberships``
rows, but corrected nothing retroactively. The script under test finds and
fixes rows where the membership grants more privilege than the ``users``
directory — the exact residue earlier demotions left behind.
"""

from __future__ import annotations

import pytest

from backend.v2.contexts.identity.domain.errors import RoleRevocationFailed
from backend.v2.scripts.reconcile_membership_roles import reconcile


async def _seed(
    db,
    *,
    user_id: str = "u-staff",
    membership_user_id: str = "u-staff",
    directory_roles: list[str] | None = None,
    membership_roles: list[str] | None = None,
    academy_id: str = "academy-a",
    status: str = "active",
    is_active: bool = True,
    membership_id: str = "m-staff",
) -> None:
    roles = directory_roles if directory_roles is not None else ["parent"]
    await db["users"].insert_one(
        {
            "user_id": user_id,
            "auth_uid": user_id,
            "email": f"{user_id}@example.com",
            "display_name": user_id,
            "role": roles[0] if roles else None,
            "roles": roles,
            "status": status,
            "is_active": is_active,
            "academy_id": academy_id,
        }
    )
    await db["academy_memberships"].insert_one(
        {
            "membership_id": membership_id,
            "academy_id": academy_id,
            "user_id": membership_user_id,
            "roles": membership_roles if membership_roles is not None else ["admin"],
            "status": "active",
        }
    )


@pytest.mark.asyncio
async def test_dry_run_reports_stale_row_without_writing(db) -> None:
    """A pre-#502 demotion residue — directory parent, membership admin —
    is reported, and a dry run must leave the row untouched."""
    await _seed(db)

    report = await reconcile(db, fix=False)

    assert len(report.stale) == 1
    entry = report.stale[0]
    assert entry.membership_id == "m-staff"
    assert entry.membership_roles == ["admin"]
    assert entry.directory_roles == ["parent"]
    assert not entry.corrected
    row = await db["academy_memberships"].find_one({"membership_id": "m-staff"})
    assert row["roles"] == ["admin"]


@pytest.mark.asyncio
async def test_fix_rewrites_membership_to_directory_roles(db) -> None:
    await _seed(db)

    report = await reconcile(db, fix=True)

    assert report.fixed == 1
    assert report.stale[0].corrected
    row = await db["academy_memberships"].find_one({"membership_id": "m-staff"})
    assert row["roles"] == ["parent"]


@pytest.mark.asyncio
async def test_alias_keyed_membership_is_found(db) -> None:
    """The membership row may be keyed by ``firebase_uid`` rather than the
    primary ``user_id``; resolution must match the claims path's alias set."""
    await db["users"].insert_one(
        {
            "user_id": "roster-staff",
            "firebase_uid": "fb-staff",
            "email": "roster@example.com",
            "display_name": "Roster",
            "role": "parent",
            "roles": ["parent"],
            "status": "active",
            "is_active": True,
            "academy_id": "academy-a",
        }
    )
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "m-alias",
            "academy_id": "academy-a",
            "user_id": "fb-staff",
            "roles": ["admin"],
            "status": "active",
        }
    )

    report = await reconcile(db, fix=True)

    assert report.fixed == 1
    row = await db["academy_memberships"].find_one({"membership_id": "m-alias"})
    assert row["roles"] == ["parent"]


@pytest.mark.asyncio
async def test_matching_rows_are_left_alone(db) -> None:
    await _seed(db, directory_roles=["admin"], membership_roles=["admin"])

    report = await reconcile(db, fix=True)

    assert report.stale == []
    assert report.fixed == 0


@pytest.mark.asyncio
async def test_alias_collision_fails_closed(db) -> None:
    """When the account's alias set matches a row owned by another account
    (its primary ``user_id``), no correction is applied for that account —
    the same fail-closed rule ``_replace_membership_roles`` enforces."""
    await db["users"].insert_one(
        {
            "user_id": "u-demoted",
            "auth_uid": "shared-id",
            "email": "demoted@example.com",
            "display_name": "Demoted",
            "role": "parent",
            "roles": ["parent"],
            "status": "active",
            "is_active": True,
            "academy_id": "academy-a",
        }
    )
    # The colliding account: its PRIMARY user_id is our auth_uid alias.
    await db["users"].insert_one(
        {
            "user_id": "shared-id",
            "email": "other@example.com",
            "display_name": "Other",
            "role": "admin",
            "roles": ["admin"],
            "status": "active",
            "is_active": True,
            "academy_id": "academy-a",
        }
    )
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "m-stale",
            "academy_id": "academy-a",
            "user_id": "u-demoted",
            "roles": ["admin"],
            "status": "active",
        }
    )
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "m-foreign",
            "academy_id": "academy-a",
            "user_id": "shared-id",
            "roles": ["admin"],
            "status": "active",
        }
    )

    report = await reconcile(db, fix=True)

    assert len(report.collisions) == 1
    collision = report.collisions[0]
    assert collision.user_id == "u-demoted"
    assert collision.foreign_membership_ids == ["m-foreign"]
    assert collision.stale_membership_ids == ["m-stale"]
    stale = await db["academy_memberships"].find_one({"membership_id": "m-stale"})
    assert stale["roles"] == ["admin"], "collision must withhold the correction"
    entry = next(s for s in report.stale if s.membership_id == "m-stale")
    assert entry.skipped_reason == "alias-collision"
    assert not entry.corrected


@pytest.mark.asyncio
async def test_empty_directory_roles_are_reported_not_auto_revoked(db) -> None:
    await _seed(db, directory_roles=[])

    report = await reconcile(db, fix=True)

    assert report.fixed == 0
    assert report.stale[0].skipped_reason == "empty-directory-roles"
    row = await db["academy_memberships"].find_one({"membership_id": "m-staff"})
    assert row["roles"] == ["admin"]


@pytest.mark.asyncio
async def test_inactive_accounts_sort_first(db) -> None:
    """Terminated/inactive accounts are the priority: nobody is watching
    them, so their stale grants live longest."""
    await _seed(
        db,
        user_id="u-active",
        membership_user_id="u-active",
        membership_id="m-active",
    )
    await _seed(
        db,
        user_id="u-terminated",
        membership_user_id="u-terminated",
        membership_id="m-terminated",
        status="terminated",
        is_active=False,
    )

    report = await reconcile(db, fix=False)

    assert [s.user_id for s in report.stale] == ["u-terminated", "u-active"]
    assert report.stale[0].directory_inactive


@pytest.mark.asyncio
async def test_scoped_to_one_academy(db) -> None:
    await _seed(db, academy_id="academy-a", membership_id="m-a")
    await _seed(
        db,
        user_id="u-b",
        membership_user_id="u-b",
        academy_id="academy-b",
        membership_id="m-b",
    )

    report = await reconcile(db, academy_id="academy-a", fix=True)

    assert report.fixed == 1
    row_a = await db["academy_memberships"].find_one({"membership_id": "m-a"})
    row_b = await db["academy_memberships"].find_one({"membership_id": "m-b"})
    assert row_a["roles"] == ["parent"]
    assert row_b["roles"] == ["admin"]


@pytest.mark.asyncio
async def test_orphan_membership_rows_are_reported(db) -> None:
    """A privileged membership row no users doc resolves to has no directory
    truth to reconcile against — it is surfaced for a human, not rewritten."""
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "m-orphan",
            "academy_id": "academy-a",
            "user_id": "gone-user",
            "roles": ["admin"],
            "status": "active",
        }
    )

    report = await reconcile(db, fix=True)

    assert len(report.orphans) == 1
    assert report.orphans[0].membership_id == "m-orphan"
    assert report.orphans[0].roles == ["admin"]
    row = await db["academy_memberships"].find_one({"membership_id": "m-orphan"})
    assert row["roles"] == ["admin"]


@pytest.mark.asyncio
async def test_lost_write_raises(db) -> None:
    """A correction whose write does not land must abort loudly — reporting
    a stale grant fixed when it was not is the failure class #508 is about."""

    class _LostWriteCollection:
        def __init__(self, real):
            self._real = real

        def find(self, *args, **kwargs):
            return self._real.find(*args, **kwargs)

        async def find_one(self, *args, **kwargs):
            return await self._real.find_one(*args, **kwargs)

        async def update_many(self, *args, **kwargs):
            class _R:
                matched_count = 0

            return _R()

    class _WrappedDb:
        def __init__(self, real):
            self._real = real

        def __getitem__(self, name):
            if name == "academy_memberships":
                return _LostWriteCollection(self._real[name])
            return self._real[name]

    await _seed(db)

    with pytest.raises(RoleRevocationFailed):
        await reconcile(_WrappedDb(db), fix=True)
