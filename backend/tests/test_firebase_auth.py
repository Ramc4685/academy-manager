"""Phase 1 regression tests for the Firebase-primary auth model.

Covers the four ship-blockers identified in the code review:
  1. Legacy password routes return 410 when FIREBASE_AUTH_ENABLED=true.
  2. Email verification is enforced at signup + per-request, not only on linking.
  3. Invite acceptance requires a matching, verified Firebase identity.
  4. Backend-side Firebase rollback fires when registration fails.

These tests stub firebase-admin's token verification and the Mongo client
(mongomock-motor) so they run without network or a live database.
"""
from __future__ import annotations

import os
import sys
import types
import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Set required env BEFORE importing backend modules.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "academy_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ["FIREBASE_AUTH_ENABLED"] = "true"
os.environ["FIREBASE_PROJECT_ID"] = "academy-courtmastr-test"

from mongomock_motor import AsyncMongoMockClient  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import db as db_module  # noqa: E402
import auth as auth_module  # noqa: E402
from routers import auth_routes as auth_routes_module  # noqa: E402
from routers.auth_routes import router as auth_router  # noqa: E402


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
    application.include_router(auth_router, prefix="/api")
    return application


@pytest.fixture
def client(app):
    # raise_server_exceptions=False lets us assert on the 500 response body
    # produced by Starlette when our route raises, instead of re-raising.
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def firebase_disabled():
    """Temporarily disable Firebase to exercise legacy paths."""
    prev = os.environ.get("FIREBASE_AUTH_ENABLED")
    os.environ["FIREBASE_AUTH_ENABLED"] = "false"
    yield
    if prev is None:
        os.environ.pop("FIREBASE_AUTH_ENABLED", None)
    else:
        os.environ["FIREBASE_AUTH_ENABLED"] = prev


def _stub_token(
    uid: str = "uid-123",
    email: str = "newparent@example.com",
    email_verified: bool = True,
    provider: str = "password",
):
    """Build a fake decoded Firebase claim dict."""
    return {
        "sub": uid,
        "user_id": uid,
        "email": email,
        "email_verified": email_verified,
        "name": "New Parent",
        "firebase": {"sign_in_provider": provider},
    }


@pytest.fixture
def stub_verify():
    """Patch firebase_admin verify_id_token to return a controllable claim."""
    holder = {"claim": _stub_token()}

    def fake_verify(token, check_revoked=False):  # noqa: D401
        if token == "INVALID":
            raise ValueError("bad token")
        return holder["claim"]

    with patch.object(auth_module, "_ensure_firebase_app", lambda: None), \
         patch.object(auth_module.firebase_admin_auth, "verify_id_token", side_effect=fake_verify):
        yield holder


@pytest.fixture
def stub_delete_firebase_user():
    """Record backend-initiated Firebase deletions."""
    deletions = []

    async def fake_delete(uid):
        deletions.append(uid)

    with patch.object(auth_module, "delete_firebase_user", side_effect=fake_delete), \
         patch.object(auth_routes_module, "delete_firebase_user", side_effect=fake_delete):
        yield deletions


# ---------------------------------------------------------------------------
# 1. Legacy password routes are gated when Firebase is enabled
# ---------------------------------------------------------------------------

class TestLegacyRoutesGated:
    def test_login_returns_410(self, client):
        r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "x"})
        assert r.status_code == 410

    def test_refresh_returns_410(self, client):
        r = client.post("/api/auth/refresh")
        assert r.status_code == 410

    def test_forgot_password_returns_410(self, client):
        r = client.post("/api/auth/forgot-password", json={"email": "a@b.com"})
        assert r.status_code == 410

    def test_reset_password_returns_410(self, client):
        r = client.post("/api/auth/reset-password", json={"token": "x", "password": "abcdef"})
        assert r.status_code == 410

    def test_login_still_works_when_firebase_disabled(self, client, mongo, firebase_disabled):
        # Seed a legacy password user.
        import bcrypt
        hashed = bcrypt.hashpw(b"Passw0rd!", bcrypt.gensalt()).decode()
        asyncio.run(
            mongo.users.insert_one({
                "email": "legacy@example.com",
                "password_hash": hashed,
                "role": "parent",
                "status": "active",
            })
        )
        r = client.post(
            "/api/auth/login",
            json={"email": "legacy@example.com", "password": "Passw0rd!"},
        )
        assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# 2. Email verification enforcement
# ---------------------------------------------------------------------------

class TestVerificationEnforcement:
    def test_register_rejects_unverified_password_user(self, client, stub_verify):
        stub_verify["claim"] = _stub_token(email_verified=False, provider="password")
        r = client.post(
            "/api/auth/register",
            json={
                "email": "newparent@example.com",
                "password": "ignored-by-server",
                "name": "New Parent",
            },
            headers={"Authorization": "Bearer FAKE"},
        )
        assert r.status_code == 403
        assert "Verify" in r.json()["detail"] or "verification" in r.json()["detail"].lower()

    def test_register_allows_verified_password_user(self, client, mongo, stub_verify):
        stub_verify["claim"] = _stub_token(email_verified=True, provider="password")
        r = client.post(
            "/api/auth/register",
            json={
                "email": "newparent@example.com",
                "password": "ignored",
                "name": "New Parent",
            },
            headers={"Authorization": "Bearer FAKE"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["email"] == "newparent@example.com"
        user = asyncio.run(
            mongo.users.find_one({"email": "newparent@example.com"})
        )
        assert user["auth_provider"] == "firebase"
        assert user["email_verified"] is True
        assert "password_hash" not in user

    def test_register_allows_google_signin_without_email_verified_claim(
        self, client, mongo, stub_verify
    ):
        # Google tokens always carry email_verified=true, but verify the gate
        # short-circuits on provider != "password" regardless.
        stub_verify["claim"] = _stub_token(
            email_verified=False, provider="google.com", email="g@example.com"
        )
        r = client.post(
            "/api/auth/register",
            json={"email": "g@example.com", "password": "ignored", "name": "G"},
            headers={"Authorization": "Bearer FAKE"},
        )
        assert r.status_code == 200, r.text

    def test_me_rejects_unverified_password_user_even_when_linked(
        self, client, mongo, stub_verify
    ):
        """Per-request enforcement: even if a user is already linked, an
        unverified password token must be refused."""
        asyncio.run(
            mongo.users.insert_one({
                "email": "already@example.com",
                "auth_provider": "firebase",
                "auth_uid": "uid-already",
                "email_verified": True,  # historical state
                "role": "parent",
                "status": "active",
            })
        )
        stub_verify["claim"] = _stub_token(
            uid="uid-already",
            email="already@example.com",
            email_verified=False,
            provider="password",
        )
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 403

    def test_me_succeeds_for_verified_linked_user(self, client, mongo, stub_verify):
        asyncio.run(
            mongo.users.insert_one({
                "email": "ok@example.com",
                "auth_provider": "firebase",
                "auth_uid": "uid-ok",
                "role": "parent",
                "status": "active",
            })
        )
        stub_verify["claim"] = _stub_token(
            uid="uid-ok", email="ok@example.com", email_verified=True
        )
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 200
        assert r.json()["email"] == "ok@example.com"

    def test_me_links_seeded_admin_without_service_account_credentials(
        self, client, mongo, monkeypatch
    ):
        """Fly deploys do not have Application Default Credentials. In that
        case the backend must still verify Firebase ID tokens with Google's
        public Firebase certs and link the seeded admin by verified email."""
        for key in (
            "FIREBASE_CREDENTIALS_JSON",
            "FIREBASE_CREDENTIALS_FILE",
            "GOOGLE_APPLICATION_CREDENTIALS",
        ):
            monkeypatch.delenv(key, raising=False)

        email = "ramchand4685@gmail.com"
        asyncio.run(
            mongo.users.insert_one({
                "email": email,
                "role": "admin",
                "status": "active",
                "name": "Academy Admin",
            })
        )
        claim = _stub_token(
            uid="firebase-admin-uid",
            email=email,
            email_verified=True,
            provider="google.com",
        )
        claim["iss"] = "https://securetoken.google.com/academy-courtmastr-test"

        with patch.object(auth_module, "_ensure_firebase_app", lambda: None), patch.object(
            auth_module.google_id_token,
            "verify_firebase_token",
            return_value=claim,
        ) as verify_public, patch.object(
            auth_module.firebase_admin_auth,
            "verify_id_token",
            side_effect=auth_module.google_auth_exceptions.DefaultCredentialsError("no adc"),
        ):
            r = client.get("/api/auth/me", headers={"Authorization": "Bearer FAKE"})

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["email"] == email
        assert body["role"] == "admin"
        verify_public.assert_called_once()
        user = asyncio.run(mongo.users.find_one({"email": email}))
        assert user["auth_provider"] == "firebase"
        assert user["auth_uid"] == "firebase-admin-uid"

    def test_public_cert_transport_failure_returns_503(self, client, mongo):
        asyncio.run(
            mongo.users.insert_one({
                "email": "ok@example.com",
                "auth_provider": "firebase",
                "auth_uid": "uid-ok",
                "role": "parent",
                "status": "active",
            })
        )

        with patch.object(auth_module, "_ensure_firebase_app", lambda: None), patch.object(
            auth_module.firebase_admin_auth,
            "verify_id_token",
            side_effect=auth_module.google_auth_exceptions.DefaultCredentialsError("no adc"),
        ), patch.object(
            auth_module.google_id_token,
            "verify_firebase_token",
            side_effect=auth_module.google_auth_exceptions.TransportError("cert fetch failed"),
        ):
            r = client.get("/api/auth/me", headers={"Authorization": "Bearer FAKE"})

        assert r.status_code == 503
        assert r.json()["detail"] == "Firebase token verification unavailable"


# ---------------------------------------------------------------------------
# 3. Invite acceptance is Firebase-first
# ---------------------------------------------------------------------------

class TestInviteFirebaseFirst:
    def _seed_invite(self, mongo, email="coach@example.com", role="coach"):
        asyncio.run(
            mongo.invites.insert_one({
                "token": "inv-token",
                "email": email,
                "role": role,
                "name": "Invited Coach",
                "status": "pending",
                "created_at": "2026-01-01T00:00:00Z",
                "expires_at": "2099-01-01T00:00:00Z",
            })
        )

    def test_invite_accept_requires_matching_firebase_identity(
        self, client, mongo, stub_verify
    ):
        self._seed_invite(mongo)
        stub_verify["claim"] = _stub_token(
            email="someoneelse@example.com", email_verified=True
        )
        r = client.post(
            "/api/invites/accept/inv-token",
            json={"name": "Coach"},
            headers={"Authorization": "Bearer FAKE"},
        )
        assert r.status_code == 403

    def test_invite_accept_rejects_unverified_password_identity(
        self, client, mongo, stub_verify
    ):
        self._seed_invite(mongo)
        stub_verify["claim"] = _stub_token(
            email="coach@example.com", email_verified=False, provider="password"
        )
        r = client.post(
            "/api/invites/accept/inv-token",
            json={"name": "Coach"},
            headers={"Authorization": "Bearer FAKE"},
        )
        assert r.status_code == 403

    def test_invite_accept_creates_firebase_user_no_password_hash(
        self, client, mongo, stub_verify
    ):
        self._seed_invite(mongo)
        stub_verify["claim"] = _stub_token(
            uid="uid-coach", email="coach@example.com", email_verified=True
        )
        r = client.post(
            "/api/invites/accept/inv-token",
            json={"name": "Coach Jane"},
            headers={"Authorization": "Bearer FAKE"},
        )
        assert r.status_code == 200, r.text
        user = asyncio.run(
            mongo.users.find_one({"email": "coach@example.com"})
        )
        assert user["auth_provider"] == "firebase"
        assert user["auth_uid"] == "uid-coach"
        assert "password_hash" not in user
        # Invite consumed.
        inv = asyncio.run(
            mongo.invites.find_one({"token": "inv-token"})
        )
        assert inv["status"] == "accepted"


# ---------------------------------------------------------------------------
# 4. Backend-side Firebase rollback on registration failure
# ---------------------------------------------------------------------------

class TestBackendRollback:
    def test_register_calls_firebase_delete_when_email_already_taken(
        self, client, mongo, stub_verify, stub_delete_firebase_user
    ):
        asyncio.run(
            mongo.users.insert_one({
                "email": "taken@example.com",
                "role": "parent",
                "status": "active",
            })
        )
        stub_verify["claim"] = _stub_token(
            uid="uid-leak", email="taken@example.com", email_verified=True
        )
        r = client.post(
            "/api/auth/register",
            json={"email": "taken@example.com", "password": "ignored", "name": "X"},
            headers={"Authorization": "Bearer FAKE"},
        )
        assert r.status_code == 400
        assert stub_delete_firebase_user == ["uid-leak"]

    def test_register_calls_firebase_delete_when_email_mismatch(
        self, client, stub_verify, stub_delete_firebase_user
    ):
        stub_verify["claim"] = _stub_token(
            uid="uid-mismatch", email="firebase@example.com", email_verified=True
        )
        r = client.post(
            "/api/auth/register",
            json={"email": "wanted@example.com", "password": "ignored", "name": "X"},
            headers={"Authorization": "Bearer FAKE"},
        )
        assert r.status_code == 400
        assert stub_delete_firebase_user == ["uid-mismatch"]

    def test_register_does_not_delete_on_success(
        self, client, mongo, stub_verify, stub_delete_firebase_user
    ):
        stub_verify["claim"] = _stub_token(
            uid="uid-ok2", email="brand@example.com", email_verified=True
        )
        r = client.post(
            "/api/auth/register",
            json={"email": "brand@example.com", "password": "ignored", "name": "X"},
            headers={"Authorization": "Bearer FAKE"},
        )
        assert r.status_code == 200, r.text
        assert stub_delete_firebase_user == []

    def test_register_full_rolls_back_firebase_and_mongo_on_student_insert_failure(
        self, client, mongo, stub_verify, stub_delete_firebase_user
    ):
        """If parent inserts but downstream (student) blows up, both the
        Firebase user and the Mongo parent row must be removed so the user
        can retry from scratch."""
        stub_verify["claim"] = _stub_token(
            uid="uid-rollback",
            email="rollback@example.com",
            email_verified=True,
        )

        async def explode(*_args, **_kwargs):
            raise RuntimeError("simulated downstream failure after parent insert")

        with patch.object(
            auth_routes_module, "record_waiver_acceptance", side_effect=explode
        ):
            r = client.post(
                "/api/auth/register-full",
                json={
                    "parent_name": "Rollback Parent",
                    "parent_email": "rollback@example.com",
                    "parent_phone": "",
                    "password": "ignored",
                    "child_first_name": "Kid",
                    "child_last_name": "X",
                    "child_dob": "2015-01-01",
                    "child_skill_level": "beginner",
                    "emergency_contact_name": "E",
                    "emergency_contact_phone": "555",
                    "medical_notes": "",
                    "t_shirt_size": "",
                    "previous_experience": "",
                    "waiver_accepted": True,
                    "session_id": None,
                },
                headers={"Authorization": "Bearer FAKE"},
            )

        assert r.status_code == 500
        assert stub_delete_firebase_user == ["uid-rollback"]
        leftover = asyncio.run(
            mongo.users.find_one({"email": "rollback@example.com"})
        )
        assert leftover is None, "Mongo parent row must be cleaned up too"
        leftover_student = asyncio.run(
            mongo.students.find_one({"first_name": "Kid"})
        )
        assert leftover_student is None, "Student row must be cleaned up too"
