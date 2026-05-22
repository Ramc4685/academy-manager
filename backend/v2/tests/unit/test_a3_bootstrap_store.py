from __future__ import annotations

import mongomock_motor
import pytest

from backend.v2.contexts.identity.infrastructure.mongo_bootstrap_store import (
    MongoTenantBootstrapStore,
)


@pytest.fixture
async def db():
    client = mongomock_motor.AsyncMongoMockClient()
    return client["test"]


async def test_find_academy_by_slug_returns_none_when_missing(db):
    store = MongoTenantBootstrapStore(db)
    result = await store.find_academy_by_slug("nonexistent")
    assert result is None


async def test_create_and_find_academy(db):
    store = MongoTenantBootstrapStore(db)
    doc = {"academy_id": "acad1", "slug": "my-acad", "primary_domain": "my.acad.com"}
    await store.create_academy(doc)
    found = await store.find_academy_by_slug("my-acad")
    assert found is not None
    assert found["academy_id"] == "acad1"


async def test_ensure_owner_user_is_idempotent(db):
    store = MongoTenantBootstrapStore(db)
    user = {"user_id": "u1", "email": "a@b.com", "normalized_email": "a@b.com",
            "display_name": "A", "global_status": "active"}
    r1 = await store.ensure_owner_user(user)
    r2 = await store.ensure_owner_user(user)
    assert r1["user_id"] == r2["user_id"]
    count = await db.users.count_documents({"email": "a@b.com"})
    assert count == 1


async def test_ensure_owner_membership_is_idempotent(db):
    store = MongoTenantBootstrapStore(db)
    m = {"membership_id": "m1", "academy_id": "a1", "user_id": "u1",
         "roles": ["admin"], "status": "active"}
    await store.ensure_owner_membership(m)
    await store.ensure_owner_membership(m)
    count = await db.academy_memberships.count_documents({"academy_id": "a1", "user_id": "u1"})
    assert count == 1
