"""Contract tests for MongoMembershipRepository.

Verifies:
- Membership lookup succeeds for matching (academy_id, user_id).
- Membership lookup does NOT return another academy's membership.
- Inactive/suspended memberships are distinguishable from active ones.
- list_memberships_for_user returns only that user's memberships.
- list_active_platform_roles returns only active roles.
- upsert_membership is idempotent and updates in place.
- upsert_platform_role is idempotent and updates in place.
- Migration creates the expected index definitions.
"""

from __future__ import annotations

import importlib

import pytest

from backend.v2.contexts.identity.domain.models import AcademyMembership, PlatformRole
from backend.v2.contexts.identity.infrastructure.mongo_membership_repo import (
    MongoMembershipRepository,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_repo(db) -> MongoMembershipRepository:
    return MongoMembershipRepository(db)


async def _insert_membership(db, **kwargs) -> dict:
    defaults = {
        "membership_id": "m-default",
        "academy_id": "acad-a",
        "user_id": "u-1",
        "roles": ["coach"],
        "status": "active",
    }
    defaults.update(kwargs)
    await db["academy_memberships"].insert_one(defaults)
    return defaults


async def _insert_platform_role(db, **kwargs) -> dict:
    defaults = {
        "platform_role_id": "pr-default",
        "user_id": "u-1",
        "role": "platform_admin",
        "status": "active",
    }
    defaults.update(kwargs)
    await db["platform_roles"].insert_one(defaults)
    return defaults


# ---------------------------------------------------------------------------
# Membership lookup — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_membership_returns_active_membership(db) -> None:
    await _insert_membership(db, membership_id="m-1", academy_id="acad-a", user_id="u-1")
    repo = _make_repo(db)

    result = await repo.get_membership("acad-a", "u-1")

    assert result is not None
    assert result.membership_id == "m-1"
    assert result.academy_id == "acad-a"
    assert result.user_id == "u-1"
    assert result.roles == ("coach",)
    assert result.is_active()


@pytest.mark.asyncio
async def test_repo_satisfies_auth_membership_lookup_port(db) -> None:
    await _insert_membership(db, membership_id="m-auth", academy_id="acad-a", user_id="u-auth")
    repo = _make_repo(db)

    result = await repo.get_for_user_in_academy(user_id="u-auth", academy_id="acad-a")

    assert result is not None
    assert result.membership_id == "m-auth"


@pytest.mark.asyncio
async def test_lookup_matches_membership_keyed_by_identity_alias(db) -> None:
    """Regression (#424): a membership row keyed by the account's
    `firebase_uid`/`auth_uid` rather than its roster `user_id` must still
    resolve, matching the alias semantics PR #400 gave the invite path."""
    await _insert_membership(db, membership_id="m-alias", academy_id="acad-a", user_id="fb-uid-7")
    repo = _make_repo(db)

    assert await repo.get_for_user_in_academy(user_id="roster-7", academy_id="acad-a") is None

    result = await repo.get_for_user_in_academy(
        user_id="roster-7", academy_id="acad-a", aliases=["fb-uid-7"]
    )

    assert result is not None
    assert result.membership_id == "m-alias"


@pytest.mark.asyncio
async def test_alias_lookup_still_refuses_another_academys_membership(db) -> None:
    """Aliases widen identity only — `academy_id` stays a mandatory term."""
    await _insert_membership(db, membership_id="m-alias-b", academy_id="acad-b", user_id="fb-uid-7")
    repo = _make_repo(db)

    result = await repo.get_for_user_in_academy(
        user_id="roster-7", academy_id="acad-a", aliases=["fb-uid-7"]
    )

    assert result is None


# ---------------------------------------------------------------------------
# Membership lookup — cross-tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_membership_does_not_return_another_academys_membership(db) -> None:
    await _insert_membership(db, membership_id="m-a", academy_id="acad-a", user_id="u-1")
    await _insert_membership(db, membership_id="m-b", academy_id="acad-b", user_id="u-1")

    repo = _make_repo(db)

    result_a = await repo.get_membership("acad-a", "u-1")
    result_b = await repo.get_membership("acad-b", "u-1")

    assert result_a is not None
    assert result_a.membership_id == "m-a"
    assert result_a.academy_id == "acad-a"

    assert result_b is not None
    assert result_b.membership_id == "m-b"
    assert result_b.academy_id == "acad-b"

    # querying for acad-a with a user that only has acad-b membership returns None
    result_miss = await repo.get_membership("acad-a", "u-only-b")
    assert result_miss is None


@pytest.mark.asyncio
async def test_get_membership_returns_none_when_user_not_in_academy(db) -> None:
    await _insert_membership(db, membership_id="m-1", academy_id="acad-a", user_id="u-1")
    repo = _make_repo(db)

    result = await repo.get_membership("acad-b", "u-1")

    assert result is None


# ---------------------------------------------------------------------------
# Inactive/suspended membership distinguishability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["invited", "suspended", "removed"])
@pytest.mark.asyncio
async def test_inactive_membership_is_returned_but_reports_not_active(db, status: str) -> None:
    await _insert_membership(
        db,
        membership_id="m-inactive",
        academy_id="acad-a",
        user_id="u-1",
        roles=["coach"],
        status=status,
    )
    repo = _make_repo(db)

    result = await repo.get_membership("acad-a", "u-1")

    assert result is not None
    assert result.status == status
    assert not result.is_active()
    assert not result.has_role("coach")


@pytest.mark.asyncio
async def test_active_and_inactive_membership_are_both_returned_by_status(db) -> None:
    await db["academy_memberships"].insert_many(
        [
            {
                "membership_id": "m-a",
                "academy_id": "acad-1",
                "user_id": "u-1",
                "roles": ["admin"],
                "status": "active",
            },
            {
                "membership_id": "m-b",
                "academy_id": "acad-2",
                "user_id": "u-1",
                "roles": ["coach"],
                "status": "suspended",
            },
        ]
    )
    repo = _make_repo(db)

    memberships = await repo.list_memberships_for_user("u-1")
    statuses = {m.academy_id: m.status for m in memberships}

    assert statuses["acad-1"] == "active"
    assert statuses["acad-2"] == "suspended"


# ---------------------------------------------------------------------------
# list_memberships_for_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_memberships_for_user_returns_only_that_users_memberships(db) -> None:
    await db["academy_memberships"].insert_many(
        [
            {
                "membership_id": "m-u1-a",
                "academy_id": "acad-a",
                "user_id": "u-1",
                "roles": ["coach"],
                "status": "active",
            },
            {
                "membership_id": "m-u1-b",
                "academy_id": "acad-b",
                "user_id": "u-1",
                "roles": ["parent"],
                "status": "active",
            },
            {
                "membership_id": "m-u2-a",
                "academy_id": "acad-a",
                "user_id": "u-2",
                "roles": ["admin"],
                "status": "active",
            },
        ]
    )
    repo = _make_repo(db)

    u1_memberships = await repo.list_memberships_for_user("u-1")
    u2_memberships = await repo.list_memberships_for_user("u-2")

    assert len(u1_memberships) == 2
    assert all(m.user_id == "u-1" for m in u1_memberships)
    academy_ids = {m.academy_id for m in u1_memberships}
    assert academy_ids == {"acad-a", "acad-b"}

    assert len(u2_memberships) == 1
    assert u2_memberships[0].academy_id == "acad-a"


@pytest.mark.asyncio
async def test_list_memberships_for_user_returns_empty_for_unknown_user(db) -> None:
    repo = _make_repo(db)
    result = await repo.list_memberships_for_user("no-such-user")
    assert result == []


# ---------------------------------------------------------------------------
# Platform roles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_active_platform_roles_returns_only_active_roles(db) -> None:
    await db["platform_roles"].insert_many(
        [
            {
                "platform_role_id": "pr-1",
                "user_id": "u-1",
                "role": "platform_admin",
                "status": "active",
            },
            {
                "platform_role_id": "pr-2",
                "user_id": "u-1",
                "role": "platform_support",
                "status": "revoked",
            },
        ]
    )
    repo = _make_repo(db)

    roles = await repo.list_active_platform_roles("u-1")

    assert len(roles) == 1
    assert roles[0].role == "platform_admin"
    assert roles[0].is_active()


@pytest.mark.asyncio
async def test_repo_satisfies_auth_platform_role_port(db) -> None:
    await _insert_platform_role(
        db, platform_role_id="pr-auth", user_id="u-auth", role="platform_support"
    )
    repo = _make_repo(db)

    roles = await repo.list_active_for_user("u-auth")

    assert [role.role for role in roles] == ["platform_support"]


@pytest.mark.asyncio
async def test_list_active_platform_roles_does_not_return_other_users_roles(db) -> None:
    await db["platform_roles"].insert_many(
        [
            {
                "platform_role_id": "pr-u1",
                "user_id": "u-1",
                "role": "platform_admin",
                "status": "active",
            },
            {
                "platform_role_id": "pr-u2",
                "user_id": "u-2",
                "role": "platform_admin",
                "status": "active",
            },
        ]
    )
    repo = _make_repo(db)

    u1_roles = await repo.list_active_platform_roles("u-1")
    assert all(r.user_id == "u-1" for r in u1_roles)
    assert len(u1_roles) == 1


@pytest.mark.asyncio
async def test_list_active_platform_roles_empty_for_unknown_user(db) -> None:
    repo = _make_repo(db)
    result = await repo.list_active_platform_roles("no-such-user")
    assert result == []


# ---------------------------------------------------------------------------
# upsert_membership idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_membership_creates_new_membership(db) -> None:
    repo = _make_repo(db)
    membership = AcademyMembership(
        membership_id="m-new",
        academy_id="acad-a",
        user_id="u-new",
        roles=("admin",),
        status="active",
    )

    result = await repo.upsert_membership(membership)

    assert result.membership_id == "m-new"
    assert result.academy_id == "acad-a"
    assert result.user_id == "u-new"
    assert result.roles == ("admin",)

    stored = await db["academy_memberships"].find_one({"academy_id": "acad-a", "user_id": "u-new"})
    assert stored is not None


@pytest.mark.asyncio
async def test_upsert_membership_updates_existing_roles(db) -> None:
    await _insert_membership(
        db,
        membership_id="m-1",
        academy_id="acad-a",
        user_id="u-1",
        roles=["parent"],
        status="active",
    )
    repo = _make_repo(db)
    updated = AcademyMembership(
        membership_id="m-1",
        academy_id="acad-a",
        user_id="u-1",
        roles=("parent", "admin"),
        status="active",
    )

    result = await repo.upsert_membership(updated)

    assert set(result.roles) == {"parent", "admin"}
    count = await db["academy_memberships"].count_documents(
        {"academy_id": "acad-a", "user_id": "u-1"}
    )
    assert count == 1  # no duplicate inserted


# ---------------------------------------------------------------------------
# upsert_platform_role idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_platform_role_creates_new_grant(db) -> None:
    repo = _make_repo(db)
    grant = PlatformRole(
        platform_role_id="pr-new",
        user_id="u-platform",
        role="platform_admin",
        status="active",
    )

    result = await repo.upsert_platform_role(grant)

    assert result.user_id == "u-platform"
    assert result.role == "platform_admin"
    assert result.is_active()


@pytest.mark.asyncio
async def test_upsert_platform_role_revokes_existing_grant(db) -> None:
    await _insert_platform_role(
        db, platform_role_id="pr-1", user_id="u-1", role="platform_admin", status="active"
    )
    repo = _make_repo(db)
    revoked = PlatformRole(
        platform_role_id="pr-1",
        user_id="u-1",
        role="platform_admin",
        status="revoked",
    )

    result = await repo.upsert_platform_role(revoked)

    assert not result.is_active()
    count = await db["platform_roles"].count_documents({"user_id": "u-1", "role": "platform_admin"})
    assert count == 1  # no duplicate inserted


# ---------------------------------------------------------------------------
# Migration smoke — index definitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_creates_membership_and_platform_role_indexes(db) -> None:
    migration = importlib.import_module("backend.v2.migrations.0080_identity_membership_indexes")
    await migration.up(db)

    membership_indexes = {idx["name"] async for idx in db["academy_memberships"].list_indexes()}
    platform_indexes = {idx["name"] async for idx in db["platform_roles"].list_indexes()}
    user_indexes = {idx["name"] async for idx in db["users"].list_indexes()}

    assert "membership_academy_user_unique" in membership_indexes
    assert "membership_user_status" in membership_indexes
    assert "membership_academy_roles_status" in membership_indexes
    assert "platform_role_user_role_unique" in platform_indexes
    assert "users_firebase_uid_unique" in user_indexes
    assert "users_normalized_email_unique" in user_indexes
