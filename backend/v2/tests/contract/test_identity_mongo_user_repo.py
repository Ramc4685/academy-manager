"""Identity repository auth-bootstrap behavior."""

from __future__ import annotations

import pytest

from backend.v2.contexts.identity.infrastructure import mongo_user_repo as user_repo_module
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository


@pytest.mark.asyncio
async def test_user_repo_reads_legacy_user_without_tenant_scope(db) -> None:
    await db["users"].insert_one(
        {
            "email": "Coach@Badminton.App",
            "name": "Coach Demo",
            "role": "coach",
            "status": "active",
        }
    )

    repo = MongoUserRepository(db, default_academy_id="local-academy")

    user = await repo.get_by_email("coach@badminton.app")

    assert user is not None
    assert user.email.lower() == "coach@badminton.app"
    assert user.display_name == "Coach Demo"
    assert user.roles == ("coach",)
    assert user.is_active is True
    assert user.academy_id == "local-academy"


@pytest.mark.asyncio
async def test_user_repo_maps_v2_user_shape(db) -> None:
    await db["users"].insert_one(
        {
            "user_id": "u-admin",
            "email": "admin@example.com",
            "display_name": "Admin User",
            "roles": ["admin"],
            "is_active": True,
            "academy_id": "academy-a",
        }
    )

    repo = MongoUserRepository(db, default_academy_id="local-academy")

    user = await repo.get_by_email("admin@example.com")

    assert user is not None
    assert user.user_id == "u-admin"
    assert user.roles == ("admin",)
    assert user.academy_id == "academy-a"


@pytest.mark.asyncio
async def test_admin_user_listing_is_scoped_to_academy(db) -> None:
    await db["users"].insert_many(
        [
            {
                "user_id": "u-a",
                "email": "admin-a@example.com",
                "display_name": "Admin A",
                "roles": ["admin"],
                "status": "active",
                "academy_id": "academy-a",
            },
            {
                "user_id": "u-b",
                "email": "admin-b@example.com",
                "display_name": "Admin B",
                "roles": ["admin"],
                "status": "active",
                "academy_id": "academy-b",
            },
        ]
    )

    repo = MongoUserRepository(db, default_academy_id="academy-a")

    users = await repo.list_users(role="admin", academy_id="academy-a")

    assert [u.user_id for u in users] == ["u-a"]


@pytest.mark.asyncio
async def test_user_repo_bootstraps_new_public_parent(db) -> None:
    repo = MongoUserRepository(db, default_academy_id="academy-a")

    user = await repo.ensure_parent_user(
        email="parent@example.com",
        display_name="Parent One",
        firebase_uid="firebase-parent-1",
        academy_id="academy-a",
    )

    assert user.user_id == "firebase-parent-1"
    assert user.roles == ("parent",)
    assert user.academy_id == "academy-a"

    stored = await db["users"].find_one({"email": "parent@example.com"})
    assert stored["auth_provider"] == "firebase"
    assert stored["firebase_uid"] == "firebase-parent-1"


@pytest.mark.asyncio
async def test_user_repo_adds_parent_role_without_dropping_existing_roles(db) -> None:
    await db["users"].insert_one(
        {
            "user_id": "coach-1",
            "email": "coach-parent@example.com",
            "display_name": "Coach Parent",
            "roles": ["coach"],
            "role": "coach",
            "status": "active",
            "is_active": True,
            "academy_id": "academy-a",
        }
    )
    repo = MongoUserRepository(db, default_academy_id="academy-a")

    user = await repo.ensure_parent_user(
        email="coach-parent@example.com",
        display_name="Coach Parent",
        firebase_uid="firebase-coach-parent",
        academy_id="academy-a",
    )

    assert user.roles == ("coach", "parent")
    stored = await db["users"].find_one({"email": "coach-parent@example.com"})
    assert stored["role"] == "coach"
    # Original tenant preserved on existing users; the new academy_id
    # argument is only honored on first insert (fixes #81).
    assert stored["academy_id"] == "academy-a"


@pytest.mark.asyncio
async def test_billing_setup_login_signal_is_global_membership_aware_and_firebase_linked(
    db,
) -> None:
    await db["users"].insert_many(
        [
            {
                "user_id": "linked",
                "firebase_uid": "firebase-linked",
                "email": "linked@example.com",
                "academy_id": "academy-a",
            },
            {
                "user_id": "mongo-only",
                "email": "mongo@example.com",
                "academy_id": "academy-b",
            },
            {
                "user_id": "pending",
                "firebase_uid": "firebase-pending",
                "email": "pending@example.com",
                "academy_id": "academy-b",
            },
        ]
    )
    await db["academy_memberships"].insert_many(
        [
            {
                "academy_id": "academy-b",
                "user_id": "firebase-linked",
                "roles": ["parent"],
                "status": "active",
            },
            {
                "academy_id": "academy-b",
                "user_id": "firebase-pending",
                "roles": ["parent"],
                "status": "active",
                "login_invite_pending": True,
            },
            {
                "academy_id": "academy-a",
                "user_id": "firebase-pending",
                "roles": ["parent"],
                "status": "active",
            },
        ]
    )
    repo = MongoUserRepository(db, default_academy_id="academy-b")

    found = await repo.list_existing_user_ids(
        ["linked", "mongo-only", "pending"], academy_id="academy-b"
    )

    assert found == {"linked"}
    assert await repo.list_existing_user_ids(["pending"], academy_id="academy-a") == {"pending"}
    assert await repo.get_billing_setup_parent("linked", academy_id="academy-b") is not None
    assert await repo.get_billing_setup_parent("linked", academy_id="academy-a") is None
    assert await repo.get_login_invite_user("linked", academy_id="academy-b") is not None


@pytest.mark.asyncio
async def test_billing_setup_provisioning_remains_invite_pending_for_safe_resend(
    db, monkeypatch
) -> None:
    class _Firebase:
        async def ensure_user(self, **kwargs):
            return kwargs["uid"], False

    monkeypatch.setattr(user_repo_module, "get_firebase_admin_adapter", lambda: _Firebase())
    repo = MongoUserRepository(db, default_academy_id="academy-b")

    uid = await repo.ensure_parent_login(
        parent_id="parent-1",
        email="parent@example.com",
        display_name="Parent One",
        academy_id="academy-b",
        actor_id="admin-1",
    )
    repeated_uid = await repo.ensure_parent_login(
        parent_id="parent-1",
        email="parent@example.com",
        display_name="Parent One",
        academy_id="academy-b",
        actor_id="admin-1",
    )

    assert uid == repeated_uid == "parent-1"
    user = await db["users"].find_one({"user_id": "parent-1"})
    assert user is not None and "login_invite_pending" not in user
    membership = await db["academy_memberships"].find_one(
        {"academy_id": "academy-b", "user_id": "parent-1"}
    )
    assert membership is not None and membership["login_invite_pending"] is True
    assert await repo.list_existing_user_ids(["parent-1"], academy_id="academy-b") == set()

    sent_at = membership["updated_at"]
    await repo.record_login_invite("parent-1", academy_id="academy-b", sent_at=sent_at)
    delivered = await db["academy_memberships"].find_one(
        {"academy_id": "academy-b", "user_id": "parent-1"}
    )
    assert delivered is not None and "login_invite_pending" not in delivered
    assert await repo.list_existing_user_ids(["parent-1"], academy_id="academy-b") == {"parent-1"}
