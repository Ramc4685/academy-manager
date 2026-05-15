"""Phase 5 Slice 2 tests for parent onboarding backend.

Tests cover:
  - POST /api/onboarding/start (idempotent draft creation)
  - PATCH /api/onboarding/{id} (owner-only, draft-only, waiver validation)
  - GET /api/onboarding/{id}/status (minimal polling payload)
  - Waiver version seed idempotency
  - TTL index on expires_at

Stubs firebase-admin and uses mongomock-motor, matching test_firebase_auth.py pattern.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "academy_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ["FIREBASE_AUTH_ENABLED"] = "true"
os.environ["FIREBASE_PROJECT_ID"] = "academy-courtmastr-test"

from mongomock_motor import AsyncMongoMockClient  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from bson import ObjectId  # noqa: E402

import db as db_module  # noqa: E402
import auth as auth_module  # noqa: E402
from routers.onboarding_routes import router as onboarding_router  # noqa: E402
from routers.onboarding_routes import seed_waiver_version  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mongo():
    """Fresh in-memory Mongo for each test, wired into the backend's get_db()."""
    client = AsyncMongoMockClient()
    fake_db = client["academy_test"]
    db_module._client = client
    db_module._db = fake_db
    yield fake_db
    db_module._client = None
    db_module._db = None


@pytest.fixture
def app(mongo):
    application = FastAPI()
    application.include_router(onboarding_router, prefix="/api")
    return application


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


def _stub_token(
    uid: str = "uid-parent-1",
    email: str = "parent@example.com",
    email_verified: bool = True,
    provider: str = "password",
) -> dict:
    return {
        "sub": uid,
        "user_id": uid,
        "email": email,
        "email_verified": email_verified,
        "name": "Test Parent",
        "firebase": {"sign_in_provider": provider},
    }


@pytest.fixture
def stub_verify():
    """Patch firebase_admin verify_id_token to return a controllable claim."""
    holder = {"claim": _stub_token()}

    def fake_verify(token, check_revoked=False):
        if token == "INVALID":
            raise ValueError("bad token")
        return holder["claim"]

    with patch.object(auth_module, "_ensure_firebase_app", lambda: None), \
         patch.object(auth_module.firebase_admin_auth, "verify_id_token", side_effect=fake_verify):
        yield holder


def _seed_parent(mongo_db, uid: str = "uid-parent-1", email: str = "parent@example.com") -> dict:
    """Insert a verified Firebase parent user and return the doc."""
    doc = {
        "email": email,
        "auth_provider": "firebase",
        "auth_uid": uid,
        "email_verified": True,
        "role": "parent",
        "status": "active",
        "name": "Test Parent",
    }
    result = asyncio.run(mongo_db.users.insert_one(doc))
    doc["_id"] = result.inserted_id
    return doc


def _seed_waiver(mongo_db) -> None:
    """Seed the 2026.1 waiver version synchronously for test setup."""
    asyncio.run(seed_waiver_version(mongo_db))


# ---------------------------------------------------------------------------
# 1. POST /api/onboarding/start — creates draft for verified parent
# ---------------------------------------------------------------------------


class TestStartEndpoint:
    def test_start_creates_draft_for_verified_parent(self, client, mongo, stub_verify):
        parent = _seed_parent(mongo)
        stub_verify["claim"] = _stub_token(
            uid=str(parent["auth_uid"]), email=parent["email"]
        )
        r = client.post(
            "/api/onboarding/start",
            headers={"Authorization": "Bearer FAKE"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "draft"
        assert body["parent_user_id"] == str(parent["_id"])
        assert "id" in body

    def test_start_idempotent_returns_existing_draft(self, client, mongo, stub_verify):
        parent = _seed_parent(mongo)
        stub_verify["claim"] = _stub_token(
            uid=parent["auth_uid"], email=parent["email"]
        )
        r1 = client.post(
            "/api/onboarding/start",
            headers={"Authorization": "Bearer FAKE"},
        )
        r2 = client.post(
            "/api/onboarding/start",
            headers={"Authorization": "Bearer FAKE"},
        )
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"]
        count = asyncio.run(
            mongo.onboarding_applications.count_documents({})
        )
        assert count == 1

    def test_start_rejected_for_unverified_password_user(self, client, mongo, stub_verify):
        parent = _seed_parent(mongo)
        stub_verify["claim"] = _stub_token(
            uid=parent["auth_uid"], email=parent["email"],
            email_verified=False, provider="password"
        )
        r = client.post(
            "/api/onboarding/start",
            headers={"Authorization": "Bearer FAKE"},
        )
        assert r.status_code == 403
        count = asyncio.run(
            mongo.onboarding_applications.count_documents({})
        )
        assert count == 0

    def test_start_rejected_for_unauthenticated(self, client):
        r = client.post("/api/onboarding/start")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 2. PATCH /api/onboarding/{id}
# ---------------------------------------------------------------------------


class TestPatchEndpoint:
    def test_patch_updates_owned_application(self, client, mongo, stub_verify):
        parent = _seed_parent(mongo)
        stub_verify["claim"] = _stub_token(
            uid=parent["auth_uid"], email=parent["email"]
        )
        # Create the draft first
        start_r = client.post(
            "/api/onboarding/start",
            headers={"Authorization": "Bearer FAKE"},
        )
        app_id = start_r.json()["id"]

        patch_r = client.patch(
            f"/api/onboarding/{app_id}",
            json={"child_profile": {"name": "Alice", "dob": "2015-06-01"}},
            headers={"Authorization": "Bearer FAKE"},
        )
        assert patch_r.status_code == 200, patch_r.text
        body = patch_r.json()
        assert body["child_profile"]["name"] == "Alice"

    def test_patch_blocks_other_parent(self, client, mongo, stub_verify):
        owner = _seed_parent(mongo, uid="uid-owner", email="owner@example.com")
        other = _seed_parent(mongo, uid="uid-other", email="other@example.com")

        # Create draft as owner
        stub_verify["claim"] = _stub_token(uid="uid-owner", email="owner@example.com")
        start_r = client.post(
            "/api/onboarding/start",
            headers={"Authorization": "Bearer FAKE"},
        )
        app_id = start_r.json()["id"]

        # Attempt patch as other parent
        stub_verify["claim"] = _stub_token(uid="uid-other", email="other@example.com")
        patch_r = client.patch(
            f"/api/onboarding/{app_id}",
            json={"child_profile": {"name": "Hijacked"}},
            headers={"Authorization": "Bearer FAKE"},
        )
        assert patch_r.status_code == 403

        # Verify no mutation occurred
        doc = asyncio.run(
            mongo.onboarding_applications.find_one({"_id": ObjectId(app_id)})
        )
        assert doc["child_profile"] == {}

    def test_patch_blocks_non_draft_status(self, client, mongo, stub_verify):
        parent = _seed_parent(mongo)
        stub_verify["claim"] = _stub_token(
            uid=parent["auth_uid"], email=parent["email"]
        )
        start_r = client.post(
            "/api/onboarding/start",
            headers={"Authorization": "Bearer FAKE"},
        )
        app_id = start_r.json()["id"]

        # Manually flip status to pending_approval
        asyncio.run(
            mongo.onboarding_applications.update_one(
                {"_id": ObjectId(app_id)},
                {"$set": {"status": "pending_approval"}},
            )
        )

        patch_r = client.patch(
            f"/api/onboarding/{app_id}",
            json={"child_profile": {"name": "Alice"}},
            headers={"Authorization": "Bearer FAKE"},
        )
        assert patch_r.status_code == 400

    def test_patch_waiver_acceptance_creates_acceptance_row(self, client, mongo, stub_verify):
        _seed_waiver(mongo)
        parent = _seed_parent(mongo)
        stub_verify["claim"] = _stub_token(
            uid=parent["auth_uid"], email=parent["email"]
        )
        start_r = client.post(
            "/api/onboarding/start",
            headers={"Authorization": "Bearer FAKE"},
        )
        app_id = start_r.json()["id"]

        # Set child profile first (needed for composite key)
        client.patch(
            f"/api/onboarding/{app_id}",
            json={"child_profile": {"name": "Bob", "dob": "2016-03-15"}},
            headers={"Authorization": "Bearer FAKE"},
        )

        patch_r = client.patch(
            f"/api/onboarding/{app_id}",
            json={"waiver_acceptance": {"version": "2026.1", "accepted": True}},
            headers={"Authorization": "Bearer FAKE"},
        )
        assert patch_r.status_code == 200, patch_r.text

        acceptance = asyncio.run(
            mongo.waiver_acceptances.find_one(
                {"parent_user_id": str(parent["_id"]), "waiver_version": "2026.1"}
            )
        )
        assert acceptance is not None
        assert acceptance["content_hash"] is not None
        assert acceptance["text_snapshot"] is not None
        assert len(acceptance["content_hash"]) == 64  # SHA-256 hex

    def test_patch_unknown_waiver_version_400(self, client, mongo, stub_verify):
        _seed_waiver(mongo)
        parent = _seed_parent(mongo)
        stub_verify["claim"] = _stub_token(
            uid=parent["auth_uid"], email=parent["email"]
        )
        start_r = client.post(
            "/api/onboarding/start",
            headers={"Authorization": "Bearer FAKE"},
        )
        app_id = start_r.json()["id"]

        patch_r = client.patch(
            f"/api/onboarding/{app_id}",
            json={"waiver_acceptance": {"version": "9999.bogus", "accepted": True}},
            headers={"Authorization": "Bearer FAKE"},
        )
        assert patch_r.status_code == 400


# ---------------------------------------------------------------------------
# 3. GET /api/onboarding/{id}/status
# ---------------------------------------------------------------------------


class TestStatusEndpoint:
    def test_status_returns_minimal_payload(self, client, mongo, stub_verify):
        parent = _seed_parent(mongo)
        stub_verify["claim"] = _stub_token(
            uid=parent["auth_uid"], email=parent["email"]
        )
        start_r = client.post(
            "/api/onboarding/start",
            headers={"Authorization": "Bearer FAKE"},
        )
        app_id = start_r.json()["id"]

        status_r = client.get(
            f"/api/onboarding/{app_id}/status",
            headers={"Authorization": "Bearer FAKE"},
        )
        assert status_r.status_code == 200, status_r.text
        body = status_r.json()
        assert body["id"] == app_id
        assert body["status"] == "draft"
        assert "selected_session_id" in body
        assert "child_name" in body
        assert "updated_at" in body
        # Ensure no extra sensitive fields
        assert "parent_profile" not in body
        assert "parent_email" not in body

    def test_status_blocks_other_parent(self, client, mongo, stub_verify):
        owner = _seed_parent(mongo, uid="uid-owner2", email="owner2@example.com")
        other = _seed_parent(mongo, uid="uid-other2", email="other2@example.com")

        stub_verify["claim"] = _stub_token(uid="uid-owner2", email="owner2@example.com")
        start_r = client.post(
            "/api/onboarding/start",
            headers={"Authorization": "Bearer FAKE"},
        )
        app_id = start_r.json()["id"]

        stub_verify["claim"] = _stub_token(uid="uid-other2", email="other2@example.com")
        status_r = client.get(
            f"/api/onboarding/{app_id}/status",
            headers={"Authorization": "Bearer FAKE"},
        )
        assert status_r.status_code == 403


# ---------------------------------------------------------------------------
# 4. Waiver seed idempotency
# ---------------------------------------------------------------------------


class TestWaiverSeed:
    def test_waiver_seed_idempotent(self, mongo):
        asyncio.run(seed_waiver_version(mongo))
        asyncio.run(seed_waiver_version(mongo))
        count = asyncio.run(
            mongo.waiver_versions.count_documents({"version": "2026.1"})
        )
        assert count == 1

    def test_waiver_seed_has_required_fields(self, mongo):
        asyncio.run(seed_waiver_version(mongo))
        doc = asyncio.run(mongo.waiver_versions.find_one({"version": "2026.1"}))
        assert doc is not None
        assert len(doc["content_hash"]) == 64
        assert len(doc["text"]) >= 300
        assert "effective_from" in doc


# ---------------------------------------------------------------------------
# 5. Index assertions
# ---------------------------------------------------------------------------


class TestIndexes:
    def test_ttl_index_on_expires_at(self, mongo):
        asyncio.run(db_module.ensure_indexes())
        indexes = asyncio.run(
            mongo.onboarding_applications.list_indexes().to_list(length=20)
        )
        ttl_index = next(
            (
                idx for idx in indexes
                if "expires_at" in idx.get("key", {})
                and idx.get("expireAfterSeconds") == 0
            ),
            None,
        )
        assert ttl_index is not None, (
            "Expected TTL index on onboarding_applications.expires_at"
        )
