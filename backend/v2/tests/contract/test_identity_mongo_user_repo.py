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
