"""Phase 5 Slice 6 tests: admin-controlled waitlist endpoints.

Covers:
  1. GET /api/admin/waitlist?session_id=... returns FIFO with next_candidate flag
  2. next_candidate is False when session is full
  3. 403 for non-admin roles (coach, parent)
  4. POST /api/admin/waitlist/{id}/enroll happy path
  5. POST /api/admin/waitlist/{id}/enroll 409 race condition
  6. POST /api/admin/waitlist/{id}/enroll 400 for non-waiting status
  7. POST /api/admin/waitlist/{id}/enroll 403 for parent
  8. POST /api/admin/waitlist/{id}/skip marks status with reason, no enrollment
  9. DELETE /api/admin/waitlist/{id} soft-deletes with audit log
  10. Each mutation writes audit_logs row with actor_id, actor_email, action, entity_id
  11. GET response includes student_name (joined from students collection)

Uses mongomock-motor + patched firebase-admin + FastAPI TestClient, mirroring
the patterns in test_firebase_auth.py and test_onboarding.py.
"""
from __future__ import annotations

import asyncio
import json as _json_lib
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from bson import ObjectId

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "academy_test")
os.environ.setdefault("JWT_SECRET", "test-secret-slice6")
os.environ["FIREBASE_AUTH_ENABLED"] = "true"
os.environ["FIREBASE_PROJECT_ID"] = "academy-courtmastr-test"

from mongomock_motor import AsyncMongoMockClient  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import db as db_module  # noqa: E402
import auth as auth_module  # noqa: E402
from routers.waitlist_routes import router as waitlist_router  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso(offset_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()


def _oid_str() -> str:
    return str(ObjectId())


def _stub_token(
    uid: str = "uid-admin",
    email: str = "admin@example.com",
    email_verified: bool = True,
    provider: str = "password",
) -> dict:
    return {
        "sub": uid,
        "user_id": uid,
        "email": email,
        "email_verified": email_verified,
        "name": "Test User",
        "firebase": {"sign_in_provider": provider},
    }


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
    application.include_router(waitlist_router, prefix="/api")
    return application


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def stub_verify():
    """Patch firebase verify_id_token to return a controllable claim."""
    holder = {"claim": _stub_token()}

    def fake_verify(token, check_revoked=False):
        if token == "INVALID":
            raise ValueError("bad token")
        return holder["claim"]

    with patch.object(auth_module, "_ensure_firebase_app", lambda: None), \
         patch.object(auth_module.firebase_admin_auth, "verify_id_token", side_effect=fake_verify):
        yield holder


def _seed_admin(mongo, uid="uid-admin", email="admin@example.com") -> dict:
    doc = {
        "auth_provider": "firebase",
        "auth_uid": uid,
        "email": email,
        "name": "Admin User",
        "role": "admin",
        "status": "active",
    }
    asyncio.run(mongo.users.insert_one(doc))
    return doc


def _seed_coach(mongo, uid="uid-coach", email="coach@example.com") -> dict:
    doc = {
        "auth_provider": "firebase",
        "auth_uid": uid,
        "email": email,
        "name": "Coach User",
        "role": "coach",
        "status": "active",
    }
    asyncio.run(mongo.users.insert_one(doc))
    return doc


def _seed_parent(mongo, uid="uid-parent", email="parent@example.com") -> dict:
    doc = {
        "auth_provider": "firebase",
        "auth_uid": uid,
        "email": email,
        "name": "Parent User",
        "role": "parent",
        "status": "active",
    }
    asyncio.run(mongo.users.insert_one(doc))
    return doc


def _seed_session(mongo, *, capacity: int = 10, enrolled_count: int = 0,
                  include_reserved_seats: bool = True) -> str:
    sid = ObjectId()
    doc = {
        "_id": sid,
        "name": "Test Session",
        "status": "active",
        "max_students": capacity,
        "is_deleted": False,
    }
    if include_reserved_seats:
        doc["reserved_seats"] = enrolled_count
    asyncio.run(mongo.sessions.insert_one(doc))
    return str(sid)


def _seed_student(mongo, *, parent_user_id: str, first_name: str = "Alice", last_name: str = "Smith") -> str:
    sid = ObjectId()
    asyncio.run(mongo.students.insert_one({
        "_id": sid,
        "first_name": first_name,
        "last_name": last_name,
        "parent_user_id": parent_user_id,
        "is_deleted": False,
    }))
    return str(sid)


def _seed_waitlist_entry(
    mongo,
    *,
    session_id: str,
    student_id: str,
    parent_user_id: str,
    parent_email: str = "parent@example.com",
    status: str = "waiting",
    requested_at: str | None = None,
) -> str:
    wid = ObjectId()
    asyncio.run(mongo.waitlist.insert_one({
        "_id": wid,
        "session_id": session_id,
        "student_id": student_id,
        "parent_user_id": parent_user_id,
        "status": status,
        "requested_at": requested_at or _now_iso(),
        "is_deleted": False,
    }))
    return str(wid)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAdminListWaitlist:
    def test_admin_list_returns_fifo_with_next_candidate(self, client, mongo, stub_verify):
        """3 entries in non-FIFO insertion order; response must be FIFO; first gets next_candidate=True."""
        admin = _seed_admin(mongo)
        stub_verify["claim"] = _stub_token(uid=admin["auth_uid"], email=admin["email"])

        parent = _seed_parent(mongo)
        session_id = _seed_session(mongo, capacity=10, enrolled_count=5)  # free seats exist
        parent_id = str(asyncio.run(mongo.users.find_one({"email": parent["email"]}))["_id"])

        # Insert in reverse chronological order
        t0 = "2025-01-01T10:00:00+00:00"
        t1 = "2025-01-01T11:00:00+00:00"
        t2 = "2025-01-01T12:00:00+00:00"
        s0 = _seed_student(mongo, parent_user_id=parent_id, first_name="Third", last_name="One")
        s1 = _seed_student(mongo, parent_user_id=parent_id, first_name="Second", last_name="One")
        s2 = _seed_student(mongo, parent_user_id=parent_id, first_name="First", last_name="One")

        wid2 = _seed_waitlist_entry(mongo, session_id=session_id, student_id=s0, parent_user_id=parent_id, requested_at=t2)
        wid1 = _seed_waitlist_entry(mongo, session_id=session_id, student_id=s1, parent_user_id=parent_id, requested_at=t1)
        wid0 = _seed_waitlist_entry(mongo, session_id=session_id, student_id=s2, parent_user_id=parent_id, requested_at=t0)

        r = client.get(f"/api/admin/waitlist?session_id={session_id}", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 200, r.text
        entries = r.json()
        assert len(entries) == 3
        # Must be FIFO (ascending requested_at)
        assert entries[0]["requested_at"] == t0
        assert entries[1]["requested_at"] == t1
        assert entries[2]["requested_at"] == t2
        # Positions are 1-indexed
        assert entries[0]["position"] == 1
        assert entries[1]["position"] == 2
        assert entries[2]["position"] == 3
        # Only first has next_candidate
        assert entries[0]["next_candidate"] is True
        assert entries[1]["next_candidate"] is False
        assert entries[2]["next_candidate"] is False

    def test_admin_list_no_next_candidate_when_session_full(self, client, mongo, stub_verify):
        """Session at capacity: no entry should get next_candidate=True."""
        admin = _seed_admin(mongo)
        stub_verify["claim"] = _stub_token(uid=admin["auth_uid"], email=admin["email"])

        parent = _seed_parent(mongo)
        session_id = _seed_session(mongo, capacity=5, enrolled_count=5)  # full
        parent_id = str(asyncio.run(mongo.users.find_one({"email": parent["email"]}))["_id"])

        s0 = _seed_student(mongo, parent_user_id=parent_id)
        _seed_waitlist_entry(mongo, session_id=session_id, student_id=s0, parent_user_id=parent_id)

        r = client.get(f"/api/admin/waitlist?session_id={session_id}", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 200, r.text
        entries = r.json()
        assert all(e["next_candidate"] is False for e in entries)

    def test_admin_list_403_for_non_admin(self, client, mongo, stub_verify):
        """Coach and parent both get 403."""
        session_id = _seed_session(mongo)

        coach = _seed_coach(mongo)
        stub_verify["claim"] = _stub_token(uid=coach["auth_uid"], email=coach["email"])
        r = client.get(f"/api/admin/waitlist?session_id={session_id}", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 403

        parent = _seed_parent(mongo)
        stub_verify["claim"] = _stub_token(uid=parent["auth_uid"], email=parent["email"])
        r = client.get(f"/api/admin/waitlist?session_id={session_id}", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 403

    def test_admin_list_404_for_unknown_session(self, client, mongo, stub_verify):
        """404 when session_id doesn't match anything."""
        admin = _seed_admin(mongo)
        stub_verify["claim"] = _stub_token(uid=admin["auth_uid"], email=admin["email"])
        fake_id = _oid_str()
        r = client.get(f"/api/admin/waitlist?session_id={fake_id}", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 404

    def test_admin_list_includes_student_name(self, client, mongo, stub_verify):
        """Response includes student_name joined from students collection."""
        admin = _seed_admin(mongo)
        stub_verify["claim"] = _stub_token(uid=admin["auth_uid"], email=admin["email"])

        parent = _seed_parent(mongo)
        session_id = _seed_session(mongo, capacity=10, enrolled_count=0)
        parent_id = str(asyncio.run(mongo.users.find_one({"email": parent["email"]}))["_id"])
        student_id = _seed_student(mongo, parent_user_id=parent_id, first_name="Marco", last_name="Polo")

        _seed_waitlist_entry(mongo, session_id=session_id, student_id=student_id, parent_user_id=parent_id)

        r = client.get(f"/api/admin/waitlist?session_id={session_id}", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 200, r.text
        entries = r.json()
        assert len(entries) == 1
        assert entries[0]["student_name"] == "Marco Polo"

    def test_admin_list_student_name_none_when_student_missing(self, client, mongo, stub_verify):
        """Does not 500 when the referenced student doesn't exist."""
        admin = _seed_admin(mongo)
        stub_verify["claim"] = _stub_token(uid=admin["auth_uid"], email=admin["email"])

        parent = _seed_parent(mongo)
        session_id = _seed_session(mongo, capacity=10, enrolled_count=0)
        parent_id = str(asyncio.run(mongo.users.find_one({"email": parent["email"]}))["_id"])
        ghost_student_id = _oid_str()  # never inserted

        _seed_waitlist_entry(mongo, session_id=session_id, student_id=ghost_student_id, parent_user_id=parent_id)

        r = client.get(f"/api/admin/waitlist?session_id={session_id}", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 200, r.text
        entries = r.json()
        # student_name should be None or empty string, not a 500
        assert entries[0].get("student_name") in (None, "")


class TestAdminEnroll:
    def test_admin_enroll_creates_enrollment_and_marks_waitlist(self, client, mongo, stub_verify):
        """Happy path: capacity acquired, enrollment created, waitlist marked enrolled, audit written."""
        admin = _seed_admin(mongo)
        stub_verify["claim"] = _stub_token(uid=admin["auth_uid"], email=admin["email"])

        parent = _seed_parent(mongo)
        parent_id = str(asyncio.run(mongo.users.find_one({"email": parent["email"]}))["_id"])
        session_id = _seed_session(mongo, capacity=10, enrolled_count=5)
        student_id = _seed_student(mongo, parent_user_id=parent_id)
        wid = _seed_waitlist_entry(mongo, session_id=session_id, student_id=student_id, parent_user_id=parent_id)

        r = client.post(f"/api/admin/waitlist/{wid}/enroll", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "enrollment_id" in body
        assert body["waitlist_id"] == wid
        assert body["status"] == "enrolled"

        # Enrollment created as active but still pending admin approval.
        enrollment = asyncio.run(mongo.enrollments.find_one({"_id": ObjectId(body["enrollment_id"])}))
        assert enrollment is not None
        assert enrollment["status"] == "active"
        assert enrollment["approval_status"] == "pending"
        assert enrollment["student_id"] == student_id
        assert enrollment["session_id"] == session_id

        # Waitlist entry marked enrolled
        entry = asyncio.run(mongo.waitlist.find_one({"_id": ObjectId(wid)}))
        assert entry["status"] == "enrolled"
        assert entry.get("enrolled_at") is not None

        # Audit log written
        log = asyncio.run(mongo.audit_logs.find_one({"action": "waitlist.enrolled", "entity_id": wid}))
        assert log is not None

    def test_admin_enroll_409_when_session_full_race(self, client, mongo, stub_verify):
        """Race: enrolled_count == capacity -> 409, no enrollment, waitlist unchanged."""
        admin = _seed_admin(mongo)
        stub_verify["claim"] = _stub_token(uid=admin["auth_uid"], email=admin["email"])

        parent = _seed_parent(mongo)
        parent_id = str(asyncio.run(mongo.users.find_one({"email": parent["email"]}))["_id"])
        session_id = _seed_session(mongo, capacity=5, enrolled_count=5)  # full
        student_id = _seed_student(mongo, parent_user_id=parent_id)
        wid = _seed_waitlist_entry(mongo, session_id=session_id, student_id=student_id, parent_user_id=parent_id)

        r = client.post(f"/api/admin/waitlist/{wid}/enroll", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 409, r.text
        assert r.json().get("error") == "session_full"

        # No enrollment created
        count = asyncio.run(mongo.enrollments.count_documents({}))
        assert count == 0

        # Waitlist entry still waiting
        entry = asyncio.run(mongo.waitlist.find_one({"_id": ObjectId(wid)}))
        assert entry["status"] == "waiting"

    def test_admin_enroll_409_when_legacy_session_full_without_reserved_seats(
        self, client, mongo, stub_verify
    ):
        """Legacy sessions without reserved_seats must seed from active enrollment count."""
        admin = _seed_admin(mongo)
        stub_verify["claim"] = _stub_token(uid=admin["auth_uid"], email=admin["email"])

        parent = _seed_parent(mongo)
        parent_id = str(asyncio.run(mongo.users.find_one({"email": parent["email"]}))["_id"])
        session_id = _seed_session(mongo, capacity=2, enrolled_count=0, include_reserved_seats=False)
        for idx in range(2):
            existing_student_id = _seed_student(
                mongo,
                parent_user_id=parent_id,
                first_name=f"Existing{idx}",
            )
            asyncio.run(mongo.enrollments.insert_one({
                "session_id": session_id,
                "student_id": existing_student_id,
                "parent_user_id": parent_id,
                "status": "active",
                "is_deleted": False,
            }))
        student_id = _seed_student(mongo, parent_user_id=parent_id, first_name="Waitlisted")
        wid = _seed_waitlist_entry(
            mongo,
            session_id=session_id,
            student_id=student_id,
            parent_user_id=parent_id,
        )

        r = client.post(f"/api/admin/waitlist/{wid}/enroll", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 409, r.text
        assert asyncio.run(mongo.enrollments.count_documents({"student_id": student_id})) == 0
        session = asyncio.run(mongo.sessions.find_one({"_id": ObjectId(session_id)}))
        assert session["reserved_seats"] == 2

    def test_admin_enroll_rejects_non_waiting_status(self, client, mongo, stub_verify):
        """Waitlist already skipped -> 400."""
        admin = _seed_admin(mongo)
        stub_verify["claim"] = _stub_token(uid=admin["auth_uid"], email=admin["email"])

        parent = _seed_parent(mongo)
        parent_id = str(asyncio.run(mongo.users.find_one({"email": parent["email"]}))["_id"])
        session_id = _seed_session(mongo, capacity=10, enrolled_count=0)
        student_id = _seed_student(mongo, parent_user_id=parent_id)
        wid = _seed_waitlist_entry(
            mongo,
            session_id=session_id,
            student_id=student_id,
            parent_user_id=parent_id,
            status="skipped",
        )

        r = client.post(f"/api/admin/waitlist/{wid}/enroll", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 400

    def test_admin_enroll_403_for_parent(self, client, mongo, stub_verify):
        """Parent attempt -> 403, no mutation."""
        parent = _seed_parent(mongo)
        stub_verify["claim"] = _stub_token(uid=parent["auth_uid"], email=parent["email"])

        parent_id = str(asyncio.run(mongo.users.find_one({"email": parent["email"]}))["_id"])
        session_id = _seed_session(mongo, capacity=10, enrolled_count=0)
        student_id = _seed_student(mongo, parent_user_id=parent_id)
        wid = _seed_waitlist_entry(
            mongo,
            session_id=session_id,
            student_id=student_id,
            parent_user_id=parent_id,
        )

        r = client.post(f"/api/admin/waitlist/{wid}/enroll", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 403

        # No enrollment, no status change
        count = asyncio.run(mongo.enrollments.count_documents({}))
        assert count == 0
        entry = asyncio.run(mongo.waitlist.find_one({"_id": ObjectId(wid)}))
        assert entry["status"] == "waiting"


class TestAdminSkip:
    def test_admin_skip_marks_status_no_enrollment(self, client, mongo, stub_verify):
        """POST /skip -> status=skipped, skipped_reason persisted, no enrollment created, audit written."""
        admin = _seed_admin(mongo)
        stub_verify["claim"] = _stub_token(uid=admin["auth_uid"], email=admin["email"])

        parent = _seed_parent(mongo)
        parent_id = str(asyncio.run(mongo.users.find_one({"email": parent["email"]}))["_id"])
        session_id = _seed_session(mongo, capacity=10, enrolled_count=0)
        student_id = _seed_student(mongo, parent_user_id=parent_id)
        wid = _seed_waitlist_entry(mongo, session_id=session_id, student_id=student_id, parent_user_id=parent_id)

        r = client.post(
            f"/api/admin/waitlist/{wid}/skip",
            json={"skipped_reason": "parent unavailable"},
            headers={"Authorization": "Bearer FAKE"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "skipped"

        entry = asyncio.run(mongo.waitlist.find_one({"_id": ObjectId(wid)}))
        assert entry["status"] == "skipped"
        assert entry.get("skipped_reason") == "parent unavailable"
        assert entry.get("skipped_at") is not None

        # No enrollment
        count = asyncio.run(mongo.enrollments.count_documents({}))
        assert count == 0

        # Audit log
        log = asyncio.run(mongo.audit_logs.find_one({"action": "waitlist.skipped", "entity_id": wid}))
        assert log is not None

    def test_admin_skip_403_for_non_admin(self, client, mongo, stub_verify):
        coach = _seed_coach(mongo)
        stub_verify["claim"] = _stub_token(uid=coach["auth_uid"], email=coach["email"])

        parent = _seed_parent(mongo)
        parent_id = str(asyncio.run(mongo.users.find_one({"email": parent["email"]}))["_id"])
        session_id = _seed_session(mongo, capacity=10, enrolled_count=0)
        student_id = _seed_student(mongo, parent_user_id=parent_id)
        wid = _seed_waitlist_entry(mongo, session_id=session_id, student_id=student_id, parent_user_id=parent_id)

        r = client.post(f"/api/admin/waitlist/{wid}/skip", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 403


class TestAdminRemove:
    def test_admin_remove_soft_deletes_with_audit(self, client, mongo, stub_verify):
        """DELETE -> status=removed, audit log written, entry still in DB."""
        admin = _seed_admin(mongo)
        stub_verify["claim"] = _stub_token(uid=admin["auth_uid"], email=admin["email"])

        parent = _seed_parent(mongo)
        parent_id = str(asyncio.run(mongo.users.find_one({"email": parent["email"]}))["_id"])
        session_id = _seed_session(mongo, capacity=10, enrolled_count=0)
        student_id = _seed_student(mongo, parent_user_id=parent_id)
        wid = _seed_waitlist_entry(mongo, session_id=session_id, student_id=student_id, parent_user_id=parent_id)

        r = client.delete(
            f"/api/admin/waitlist/{wid}?removed_reason=duplicate+entry",
            headers={"Authorization": "Bearer FAKE"},
        )
        assert r.status_code == 204, r.text

        # Entry still in DB (soft delete)
        entry = asyncio.run(mongo.waitlist.find_one({"_id": ObjectId(wid)}))
        assert entry is not None
        assert entry["status"] == "removed"
        assert entry.get("removed_at") is not None
        assert entry.get("removed_reason") == "duplicate entry"

        # Audit log
        log = asyncio.run(mongo.audit_logs.find_one({"action": "waitlist.removed", "entity_id": wid}))
        assert log is not None

    def test_admin_remove_403_for_non_admin(self, client, mongo, stub_verify):
        coach = _seed_coach(mongo)
        stub_verify["claim"] = _stub_token(uid=coach["auth_uid"], email=coach["email"])

        parent = _seed_parent(mongo)
        parent_id = str(asyncio.run(mongo.users.find_one({"email": parent["email"]}))["_id"])
        session_id = _seed_session(mongo, capacity=10, enrolled_count=0)
        student_id = _seed_student(mongo, parent_user_id=parent_id)
        wid = _seed_waitlist_entry(mongo, session_id=session_id, student_id=student_id, parent_user_id=parent_id)

        r = client.delete(f"/api/admin/waitlist/{wid}", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 403


class TestAuditLogStructure:
    def test_admin_actions_write_audit_logs_with_actor(self, client, mongo, stub_verify):
        """Each of enroll/skip/remove writes an audit_logs row with actor_id, actor_email, action, entity_id."""
        admin = _seed_admin(mongo)
        stub_verify["claim"] = _stub_token(uid=admin["auth_uid"], email=admin["email"])

        parent = _seed_parent(mongo)
        parent_id = str(asyncio.run(mongo.users.find_one({"email": parent["email"]}))["_id"])

        def _make_entry(*, capacity=10, enrolled_count=0, status="waiting"):
            session_id = _seed_session(mongo, capacity=capacity, enrolled_count=enrolled_count)
            student_id = _seed_student(mongo, parent_user_id=parent_id)
            return _seed_waitlist_entry(mongo, session_id=session_id, student_id=student_id, parent_user_id=parent_id, status=status)

        # --- enroll ---
        wid_enroll = _make_entry(capacity=10, enrolled_count=0)
        r = client.post(f"/api/admin/waitlist/{wid_enroll}/enroll", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 200, r.text

        log_enroll = asyncio.run(mongo.audit_logs.find_one({"action": "waitlist.enrolled", "entity_id": wid_enroll}))
        assert log_enroll is not None
        assert "actor_id" in log_enroll or "user_id" in log_enroll  # either key is acceptable
        actor_id_field = "actor_id" if "actor_id" in log_enroll else "user_id"
        actor_email_field = "actor_email" if "actor_email" in log_enroll else "user_email"
        assert log_enroll[actor_id_field]
        assert log_enroll[actor_email_field] == admin["email"]
        assert log_enroll["entity_id"] == wid_enroll
        assert log_enroll["entity_type"] == "waitlist"

        # --- skip ---
        wid_skip = _make_entry()
        r = client.post(f"/api/admin/waitlist/{wid_skip}/skip", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 200, r.text

        log_skip = asyncio.run(mongo.audit_logs.find_one({"action": "waitlist.skipped", "entity_id": wid_skip}))
        assert log_skip is not None
        assert log_skip[actor_email_field] == admin["email"]
        assert log_skip["entity_id"] == wid_skip

        # --- remove ---
        wid_remove = _make_entry()
        r = client.delete(f"/api/admin/waitlist/{wid_remove}?removed_reason=test", headers={"Authorization": "Bearer FAKE"})
        assert r.status_code == 204, r.text

        log_remove = asyncio.run(mongo.audit_logs.find_one({"action": "waitlist.removed", "entity_id": wid_remove}))
        assert log_remove is not None
        assert log_remove[actor_email_field] == admin["email"]
        assert log_remove["entity_id"] == wid_remove
