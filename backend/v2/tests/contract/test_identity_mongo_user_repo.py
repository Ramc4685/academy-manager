"""Identity repository auth-bootstrap behavior."""

from __future__ import annotations

import pytest

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
    )

    assert user.roles == ("coach", "parent")
    stored = await db["users"].find_one({"email": "coach-parent@example.com"})
    assert stored["role"] == "coach"
