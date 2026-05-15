"""Phase 5 Slice 7 — GET /api/coach/today regression tests.

Coach daily operations endpoint. Coach identity is server-derived from the
authenticated user. Returns sessions assigned to this coach on the requested
academy-local date. Payment info is intentionally hidden.
"""
from __future__ import annotations

import os
import sys
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "academy_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ["FIREBASE_AUTH_ENABLED"] = "true"
os.environ["FIREBASE_PROJECT_ID"] = "academy-courtmastr-test"
os.environ["ACADEMY_TIMEZONE"] = "America/Chicago"

from mongomock_motor import AsyncMongoMockClient  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from bson import ObjectId  # noqa: E402

import db as db_module  # noqa: E402
import auth as auth_module  # noqa: E402
from routers.coach_routes import router as coach_router  # noqa: E402


@pytest.fixture
def mongo():
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
    application.include_router(coach_router, prefix="/api")
    return application


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


def _stub_token(uid: str, email: str, email_verified: bool = True, provider: str = "google.com"):
    return {
        "sub": uid,
        "user_id": uid,
        "email": email,
        "email_verified": email_verified,
        "name": "User",
        "firebase": {"sign_in_provider": provider},
    }


@pytest.fixture
def stub_verify():
    holder = {"claim": _stub_token("uid-default", "default@example.com")}

    def fake_verify(token, check_revoked=False):
        if token == "INVALID":
            raise ValueError("bad")
        return holder["claim"]

    with patch.object(auth_module, "_ensure_firebase_app", lambda: None), \
         patch.object(auth_module.firebase_admin_auth, "verify_id_token", side_effect=fake_verify):
        yield holder


def _seed_user(mongo, uid: str, email: str, role: str) -> str:
    res = asyncio.run(mongo.users.insert_one({
        "email": email,
        "name": email.split("@")[0],
        "role": role,
        "status": "active",
        "auth_provider": "firebase",
        "auth_uid": uid,
        "email_verified": True,
    }))
    return str(res.inserted_id)


def _seed_session(mongo, coach_id: str, name: str = "Beginner Badminton",
                   start_date: str = "2026-01-01", end_date: str = "2026-12-31",
                   days_of_week=None, start_time: str = "16:00", end_time: str = "17:30") -> str:
    if days_of_week is None:
        days_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    res = asyncio.run(mongo.sessions.insert_one({
        "name": name,
        "coach_id": coach_id,
        "start_date": start_date,
        "end_date": end_date,
        "days_of_week": days_of_week,
        "start_time": start_time,
        "end_time": end_time,
        "status": "active",
        "is_deleted": False,
    }))
    return str(res.inserted_id)


def _seed_student(mongo, first: str = "Kid", last: str = "One", medical_notes: str = "") -> str:
    res = asyncio.run(mongo.students.insert_one({
        "first_name": first,
        "last_name": last,
        "medical_notes": medical_notes,
        "is_deleted": False,
    }))
    return str(res.inserted_id)


def _seed_enrollment(mongo, session_id: str, student_id: str) -> str:
    res = asyncio.run(mongo.enrollments.insert_one({
        "session_id": session_id,
        "student_id": student_id,
        "status": "active",
        "is_deleted": False,
    }))
    return str(res.inserted_id)


# 2026-05-15 is a Friday in academy CT.

def test_today_returns_only_assigned_sessions(client, mongo, stub_verify):
    coach_a = _seed_user(mongo, "uid-a", "a@example.com", "coach")
    coach_b = _seed_user(mongo, "uid-b", "b@example.com", "coach")
    sess_x = _seed_session(mongo, coach_id=coach_a, name="A Session", days_of_week=["Fri"])
    sess_y = _seed_session(mongo, coach_id=coach_b, name="B Session", days_of_week=["Fri"])

    stub_verify["claim"] = _stub_token("uid-a", "a@example.com")
    r = client.get("/api/coach/today?date=2026-05-15", headers={"Authorization": "Bearer FAKE"})
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [s["id"] for s in body["sessions"]]
    assert sess_x in ids
    assert sess_y not in ids


def test_today_ignores_client_supplied_coach_id(client, mongo, stub_verify):
    coach_a = _seed_user(mongo, "uid-a", "a@example.com", "coach")
    coach_b = _seed_user(mongo, "uid-b", "b@example.com", "coach")
    sess_a = _seed_session(mongo, coach_id=coach_a, name="A", days_of_week=["Fri"])
    _seed_session(mongo, coach_id=coach_b, name="B", days_of_week=["Fri"])

    stub_verify["claim"] = _stub_token("uid-a", "a@example.com")
    r = client.get(
        f"/api/coach/today?date=2026-05-15&coach_id={coach_b}",
        headers={"Authorization": "Bearer FAKE"},
    )
    assert r.status_code == 200, r.text
    ids = [s["id"] for s in r.json()["sessions"]]
    assert ids == [sess_a]


def test_today_rejects_non_coach(client, mongo, stub_verify):
    _seed_user(mongo, "uid-admin", "admin@example.com", "admin")
    stub_verify["claim"] = _stub_token("uid-admin", "admin@example.com")
    r = client.get("/api/coach/today", headers={"Authorization": "Bearer FAKE"})
    assert r.status_code == 403


def test_today_rejects_unauthenticated(client):
    r = client.get("/api/coach/today")
    assert r.status_code == 401


def test_today_filters_by_academy_local_date(client, mongo, stub_verify):
    """A session at 23:30 CT on 2026-05-15 (Friday) must appear when ?date=2026-05-15,
    not when ?date=2026-05-14, even though 23:30 CT crosses UTC midnight."""
    coach = _seed_user(mongo, "uid-a", "a@example.com", "coach")
    _seed_session(mongo, coach_id=coach, name="Late", days_of_week=["Fri"],
                  start_time="23:30", end_time="23:59")

    stub_verify["claim"] = _stub_token("uid-a", "a@example.com")
    r1 = client.get("/api/coach/today?date=2026-05-15", headers={"Authorization": "Bearer FAKE"})
    assert r1.status_code == 200
    assert len(r1.json()["sessions"]) == 1

    r2 = client.get("/api/coach/today?date=2026-05-14", headers={"Authorization": "Bearer FAKE"})
    assert r2.status_code == 200
    # 2026-05-14 is Thursday; session only runs Fri.
    assert r2.json()["sessions"] == []


def test_today_default_date_is_academy_today(client, mongo, stub_verify):
    """No ?date param uses current academy-local date. Pin UTC to 2026-05-15 04:00Z
    which maps to 2026-05-14 23:00 CT — academy "today" is 2026-05-14 (Thursday)."""
    coach = _seed_user(mongo, "uid-a", "a@example.com", "coach")
    _seed_session(mongo, coach_id=coach, name="ThuOnly", days_of_week=["Thu"])
    _seed_session(mongo, coach_id=coach, name="FriOnly", days_of_week=["Fri"])

    fixed_utc = datetime(2026, 5, 15, 4, 0, 0, tzinfo=timezone.utc)

    import routers.coach_routes as coach_routes_module

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_utc.replace(tzinfo=None)
            return fixed_utc.astimezone(tz)

    stub_verify["claim"] = _stub_token("uid-a", "a@example.com")
    with patch.object(coach_routes_module, "datetime", FrozenDateTime):
        r = client.get("/api/coach/today", headers={"Authorization": "Bearer FAKE"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date"] == "2026-05-14"
    names = [s["name"] for s in body["sessions"]]
    assert "ThuOnly" in names
    assert "FriOnly" not in names


def test_today_roster_includes_medical_and_pause_flags(client, mongo, stub_verify):
    coach = _seed_user(mongo, "uid-a", "a@example.com", "coach")
    sess = _seed_session(mongo, coach_id=coach, days_of_week=["Fri"])
    s_med = _seed_student(mongo, "Med", "Kid", medical_notes="asthma")
    s_pause = _seed_student(mongo, "Pause", "Kid", medical_notes="")
    s_plain = _seed_student(mongo, "Plain", "Kid", medical_notes="")
    e_med = _seed_enrollment(mongo, sess, s_med)
    e_pause = _seed_enrollment(mongo, sess, s_pause)
    _seed_enrollment(mongo, sess, s_plain)

    asyncio.run(mongo.pause_requests.insert_one({
        "enrollment_id": e_pause,
        "student_id": s_pause,
        "status": "active",
    }))

    stub_verify["claim"] = _stub_token("uid-a", "a@example.com")
    r = client.get("/api/coach/today?date=2026-05-15", headers={"Authorization": "Bearer FAKE"})
    assert r.status_code == 200, r.text
    roster = r.json()["sessions"][0]["roster"]
    by_id = {row["student_id"]: row for row in roster}
    assert by_id[s_med]["has_medical_notes"] is True
    assert by_id[s_pause]["has_medical_notes"] is False
    assert by_id[s_pause]["is_paused"] is True
    assert by_id[s_med]["is_paused"] is False


def test_today_roster_excludes_payment_badges(client, mongo, stub_verify):
    coach = _seed_user(mongo, "uid-a", "a@example.com", "coach")
    sess = _seed_session(mongo, coach_id=coach, days_of_week=["Fri"])
    s = _seed_student(mongo)
    _seed_enrollment(mongo, sess, s)

    stub_verify["claim"] = _stub_token("uid-a", "a@example.com")
    r = client.get("/api/coach/today?date=2026-05-15", headers={"Authorization": "Bearer FAKE"})
    assert r.status_code == 200
    row = r.json()["sessions"][0]["roster"][0]
    for forbidden in ("payment_status", "unpaid", "overdue", "balance", "amount_due"):
        assert forbidden not in row


def test_today_attendance_status_reflects_attendance_collection(client, mongo, stub_verify):
    coach = _seed_user(mongo, "uid-a", "a@example.com", "coach")
    sess = _seed_session(mongo, coach_id=coach, days_of_week=["Fri"])
    s = _seed_student(mongo)
    _seed_enrollment(mongo, sess, s)
    asyncio.run(mongo.attendance.insert_one({
        "session_id": sess,
        "student_id": s,
        "date": "2026-05-15",
        "status": "present",
    }))

    stub_verify["claim"] = _stub_token("uid-a", "a@example.com")
    r = client.get("/api/coach/today?date=2026-05-15", headers={"Authorization": "Bearer FAKE"})
    assert r.status_code == 200
    row = r.json()["sessions"][0]["roster"][0]
    assert row["attendance_status"] == "present"


def test_today_empty_when_no_sessions(client, mongo, stub_verify):
    _seed_user(mongo, "uid-a", "a@example.com", "coach")
    stub_verify["claim"] = _stub_token("uid-a", "a@example.com")
    r = client.get("/api/coach/today?date=2026-05-15", headers={"Authorization": "Bearer FAKE"})
    assert r.status_code == 200
    body = r.json()
    assert body["date"] == "2026-05-15"
    assert body["timezone"] == "America/Chicago"
    assert body["sessions"] == []
