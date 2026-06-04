"""Admin sessions BFF — happy paths + wrong-persona 404 per route.

Routes covered:
- GET    /api/v2/admin/sessions
- POST   /api/v2/admin/sessions
- DELETE /api/v2/admin/sessions/{id}
- GET    /api/v2/admin/sessions/{id}/enrollments
- POST   /api/v2/admin/enrollments
- DELETE /api/v2/admin/enrollments/{id}
- POST   /api/v2/admin/enrollments/{id}/transfer
- POST   /api/v2/admin/enrollments/{id}/pause
- POST   /api/v2/admin/enrollments/{id}/resume
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import backend.v2.composition.admin as admin_composition
from backend.v2.composition.admin import compose_admin
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import MongoSessionRepository
from backend.v2.contexts.enrollment.infrastructure.mongo_session_writer import MongoSessionWriter
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.tenancy.context import set_academy_id, tenant_scope


class _FakeOutbox:
    async def append(self, event, *, session=None) -> None:
        pass

    async def pull_unprocessed(self, limit: int = 100) -> list[object]:
        return []

    async def mark_processed(self, event_id: str) -> None:
        pass


class _FakeIdempotencyStore:
    async def get(self, key: str):
        return None

    async def put(self, key: str, value) -> None:
        pass


class _FrozenAdminDateTime(datetime):
    _now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls._now.replace(tzinfo=None)
        return cls._now.astimezone(tz)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def test_list_sessions_returns_seeded_session(admin_client):
    r = admin_client.get("/api/v2/admin/sessions?date=2026-05-16")
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(s["session_id"] == "sess-1" for s in body["sessions"])


def _mongo_admin_app(db, *, academy_id: str = "academy-b") -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _tenant_scope(request: Request, call_next):
        token = set_academy_id(academy_id)
        try:
            return await call_next(request)
        finally:
            from backend.v2.shared.tenancy.context import _current as _tenant_var

            _tenant_var.reset(token)

    app.include_router(admin_router, prefix="/api/v2")
    app.state.admin = compose_admin(
        db,
        _FakeOutbox(),
        _FakeIdempotencyStore(),
        FakeStripeGateway(),
    )
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="admin-1",
        email="admin@example.com",
        academy_id=academy_id,
        roles=("admin",),
    )
    return app


@pytest.mark.asyncio
async def test_admin_upcoming_sessions_include_recurring_templates_within_30_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-upcoming-recurring"]
    concrete_start = datetime(2026, 6, 3, 15, 0, tzinfo=UTC)
    await db.sessions.insert_many(
        [
            {
                "academy_id": "academy-b",
                "session_id": "sess-concrete",
                "title": "Concrete Junior",
                "location": "Court 1",
                "coach_id": "coach-1",
                "capacity": 8,
                "status": "scheduled",
                "start_at": concrete_start,
                "end_at": concrete_start + timedelta(hours=1),
            },
            {
                "academy_id": "academy-b",
                "session_id": "tpl-upcoming",
                "name": "Recurring Junior",
                "location": "Court 2",
                "coach_id": "coach-2",
                "max_students": 10,
                "status": "active",
                "days_of_week": ["Mon", "Wed"],
                "start_time": "09:15",
                "end_time": "10:15",
                "timezone": "America/Chicago",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
            },
            {
                "academy_id": "academy-b",
                "session_id": "tpl-open-upcoming",
                "name": "Open Recurring Junior",
                "max_students": 9,
                "status": "open",
                "days_of_week": ["Mon"],
                "start_time": "10:30",
                "end_time": "11:30",
                "timezone": "America/Chicago",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
            },
            {
                "academy_id": "academy-b",
                "session_id": "tpl-prod-shaped",
                "title": "Production Shaped Recurring",
                "capacity": 12,
                "status": "scheduled",
                "days_of_week": ["Mon"],
                "start_time": "11:00",
                "end_time": "12:00",
                "timezone": "America/Chicago",
                "start_at": datetime(2026, 5, 25, 16, 0, tzinfo=UTC),
                "end_at": datetime(2026, 5, 25, 17, 0, tzinfo=UTC),
            },
            {
                "academy_id": "academy-b",
                "session_id": "tpl-late-local",
                "name": "Late Local Session",
                "max_students": 6,
                "status": "open",
                "days_of_week": ["Mon"],
                "start_time": "23:30",
                "end_time": "23:59",
                "timezone": "America/Chicago",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
            },
            {
                "academy_id": "academy-b",
                "session_id": "tpl-expired",
                "name": "Expired Template",
                "max_students": 10,
                "status": "active",
                "days_of_week": ["Mon"],
                "start_time": "09:15",
                "end_time": "10:15",
                "timezone": "America/Chicago",
                "start_date": "2026-05-01",
                "end_date": "2026-05-31",
            },
            {
                "academy_id": "academy-b",
                "session_id": "sess-day-30-late",
                "title": "Day 30 Late",
                "location": "Court 3",
                "coach_id": "coach-3",
                "capacity": 8,
                "status": "scheduled",
                "start_at": datetime(2026, 7, 1, 23, 30, tzinfo=UTC),
                "end_at": datetime(2026, 7, 2, 0, 30, tzinfo=UTC),
            },
            {
                "academy_id": "other-academy",
                "session_id": "tpl-other-tenant",
                "name": "Other Tenant",
                "days_of_week": ["Mon"],
                "start_time": "09:15",
                "end_time": "10:15",
            },
        ]
    )
    await db.enrollments.insert_many(
        [
            {
                "academy_id": "academy-b",
                "session_id": "tpl-upcoming",
                "enrollment_id": "enr-request-tenant",
                "student_id": "st-1",
                "status": "active",
            },
            {
                "academy_id": "default-academy",
                "session_id": "tpl-upcoming",
                "enrollment_id": "enr-default-tenant",
                "student_id": "st-2",
                "status": "active",
            },
        ]
    )
    await db.waitlist.insert_one(
        {
            "academy_id": "academy-b",
            "session_id": "tpl-upcoming",
            "waitlist_id": "wait-request-tenant",
            "student_id": "st-3",
            "status": "waiting",
        }
    )

    app = _mongo_admin_app(db)

    with TestClient(app) as client:
        response = client.get("/api/v2/admin/sessions?window=upcoming")

    assert response.status_code == 200, response.text
    sessions = response.json()["sessions"]
    session_ids = [session["session_id"] for session in sessions]
    assert "sess-concrete" in session_ids
    assert "tpl-upcoming" in session_ids
    assert session_ids.count("tpl-upcoming") == 1
    assert "tpl-open-upcoming" in session_ids
    assert "tpl-prod-shaped" in session_ids
    assert "sess-day-30-late" in session_ids
    assert "tpl-expired" not in session_ids
    assert "tpl-other-tenant" not in session_ids
    recurring = next(session for session in sessions if session["session_id"] == "tpl-upcoming")
    assert recurring["title"] == "Recurring Junior"
    assert recurring["capacity"] == 10
    assert recurring["status"] == "scheduled"
    assert recurring["start_at"] == "2026-06-01T14:15:00Z"
    assert recurring["enrolled_count"] == 1
    assert recurring["waitlist_count"] == 1
    open_recurring = next(
        session for session in sessions if session["session_id"] == "tpl-open-upcoming"
    )
    assert open_recurring["status"] == "scheduled"
    assert open_recurring["capacity"] == 9
    prod_shaped = next(
        session for session in sessions if session["session_id"] == "tpl-prod-shaped"
    )
    assert prod_shaped["start_at"] == "2026-06-01T16:00:00Z"

    with tenant_scope("academy-b"):
        assert await MongoSessionWriter(db).try_reserve_seat("tpl-upcoming") is True
    stored = await db.sessions.find_one({"academy_id": "academy-b", "session_id": "tpl-upcoming"})
    assert stored["reserved_seats"] == 1

    with TestClient(app) as client:
        date_response = client.get("/api/v2/admin/sessions?date=2026-06-01")

    assert date_response.status_code == 200, date_response.text
    date_sessions = date_response.json()["sessions"]
    late_local = next(
        session for session in date_sessions if session["session_id"] == "tpl-late-local"
    )
    assert late_local["status"] == "scheduled"
    assert late_local["start_at"] == "2026-06-02T04:30:00Z"


@pytest.mark.asyncio
async def test_admin_upcoming_sessions_collapses_duplicate_recurring_series(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-upcoming-recurring-dedupe"]
    await db.sessions.insert_many(
        [
            {
                "academy_id": "academy-b",
                "session_id": "series-with-roster",
                "title": "Wednesday 6:00 PM - 6:45 PM Beginner",
                "location": "Court",
                "coach_id": "coach-kishore",
                "capacity": 15,
                "status": "scheduled",
                "days_of_week": ["Wed"],
                "start_time": "18:00",
                "end_time": "18:45",
                "timezone": "America/Chicago",
                "start_at": datetime(2026, 5, 27, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 5, 27, 23, 45, tzinfo=UTC),
            },
            {
                "academy_id": "academy-b",
                "session_id": "series-empty-duplicate",
                "title": "New Beginner Class",
                "location": " Court ",
                "coach_id": "coach-kishore",
                "capacity": 15,
                "status": "scheduled",
                "days_of_week": ["Wed"],
                "start_time": "18:00",
                "end_time": "18:45",
                "timezone": "America/Chicago",
                "start_at": datetime(2026, 6, 3, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 6, 3, 23, 45, tzinfo=UTC),
            },
        ]
    )
    await db.enrollments.insert_one(
        {
            "academy_id": "academy-b",
            "session_id": "series-with-roster",
            "enrollment_id": "enr-existing",
            "student_id": "student-1",
            "status": "active",
        }
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.get("/api/v2/admin/sessions?window=upcoming")

    assert response.status_code == 200, response.text
    sessions = response.json()["sessions"]
    matching = [
        session
        for session in sessions
        if session["days_of_week"] == ["Wed"]
        and session["start_time"] == "18:00"
        and session["end_time"] == "18:45"
        and session["coach_id"] == "coach-kishore"
    ]
    assert len(matching) == 1
    assert matching[0]["session_id"] == "series-with-roster"
    assert matching[0]["enrolled_count"] == 1


@pytest.mark.asyncio
async def test_admin_upcoming_sessions_collapses_duplicate_dated_weekly_series(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-upcoming-dated-dedupe"]
    await db.sessions.insert_many(
        [
            {
                "academy_id": "academy-b",
                "session_id": "dated-series-with-roster",
                "title": "Wednesday 6:00 PM - 6:45 PM Beginner",
                "location": "Court",
                "coach_id": "coach-kishore",
                "capacity": 15,
                "status": "scheduled",
                "start_at": datetime(2026, 6, 3, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 6, 3, 23, 45, tzinfo=UTC),
            },
            {
                "academy_id": "academy-b",
                "session_id": "dated-series-empty-duplicate",
                "title": "Wednesday 6:00 PM - 6:45 PM Beginner",
                "location": "Court",
                "coach_id": "coach-kishore",
                "capacity": 15,
                "status": "scheduled",
                "start_at": datetime(2026, 6, 10, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 6, 10, 23, 45, tzinfo=UTC),
            },
        ]
    )
    await db.enrollments.insert_one(
        {
            "academy_id": "academy-b",
            "session_id": "dated-series-with-roster",
            "enrollment_id": "enr-existing",
            "student_id": "student-1",
            "status": "active",
        }
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.get("/api/v2/admin/sessions?window=upcoming")

    assert response.status_code == 200, response.text
    matching = [
        session
        for session in response.json()["sessions"]
        if session["coach_id"] == "coach-kishore"
        and session["title"] == "Wednesday 6:00 PM - 6:45 PM Beginner"
    ]
    assert len(matching) == 1
    assert matching[0]["session_id"] == "dated-series-with-roster"
    assert matching[0]["enrolled_count"] == 1


@pytest.mark.asyncio
async def test_create_recurring_session_rejects_duplicate_series(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-create-recurring-dedupe"]
    await db.sessions.insert_one(
        {
            "academy_id": "academy-b",
            "session_id": "existing-series",
            "title": "Wednesday Beginner",
            "location": "Court",
            "coach_id": "coach-kishore",
            "capacity": 15,
            "status": "scheduled",
            "days_of_week": ["Wed"],
            "start_time": "18:00",
            "end_time": "18:45",
            "timezone": "America/Chicago",
            "start_at": datetime(2026, 5, 27, 23, 0, tzinfo=UTC),
            "end_at": datetime(2026, 5, 27, 23, 45, tzinfo=UTC),
        }
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.post(
            "/api/v2/admin/sessions",
            json={
                "coach_id": "coach-kishore",
                "title": "Beginner Badminton",
                "location": "court",
                "days_of_week": ["Wed"],
                "start_time": "18:00",
                "end_time": "18:45",
                "timezone": "America/Chicago",
                "capacity": 15,
            },
        )

    assert response.status_code == 409, response.text
    assert "already exists" in response.text


@pytest.mark.asyncio
async def test_edit_recurring_session_rejects_duplicate_series(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-edit-recurring-dedupe"]
    await db.sessions.insert_many(
        [
            {
                "academy_id": "academy-b",
                "session_id": "existing-series",
                "title": "Wednesday Beginner",
                "location": "Court",
                "coach_id": "coach-kishore",
                "capacity": 15,
                "status": "scheduled",
                "days_of_week": ["Wed"],
                "start_time": "18:00",
                "end_time": "18:45",
                "timezone": "America/Chicago",
                "start_at": datetime(2026, 5, 27, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 5, 27, 23, 45, tzinfo=UTC),
            },
            {
                "academy_id": "academy-b",
                "session_id": "series-to-edit",
                "title": "Wednesday Intermediate",
                "location": "Court",
                "coach_id": "coach-kishore",
                "capacity": 15,
                "status": "scheduled",
                "days_of_week": ["Wed"],
                "start_time": "19:00",
                "end_time": "19:45",
                "timezone": "America/Chicago",
                "start_at": datetime(2026, 5, 27, 0, 0, tzinfo=UTC),
                "end_at": datetime(2026, 5, 27, 0, 45, tzinfo=UTC),
            },
        ]
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.patch(
            "/api/v2/admin/sessions/series-to-edit",
            json={
                "title": "Wednesday Beginner",
                "days_of_week": ["Wed"],
                "start_time": "18:00",
                "end_time": "18:45",
                "timezone": "America/Chicago",
                "reason": "avoid duplicate",
            },
        )

    assert response.status_code == 409, response.text
    assert "already exists" in response.text


@pytest.mark.asyncio
async def test_get_session_detail_returns_recurring_session_outside_upcoming_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-session-detail-recurring"]
    await db.sessions.insert_one(
        {
            "academy_id": "academy-b",
            "session_id": "series-detail",
            "title": "Thursday 6 PM",
            "location": "Court 1",
            "coach_id": "coach-1",
            "capacity": 15,
            "status": "scheduled",
            "days_of_week": ["Thu"],
            "start_time": "18:00",
            "end_time": "18:45",
            "timezone": "America/Chicago",
            "start_at": datetime(2026, 5, 1, 23, 0, tzinfo=UTC),
            "end_at": datetime(2026, 5, 1, 23, 45, tzinfo=UTC),
        }
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.get("/api/v2/admin/sessions/series-detail")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == "series-detail"
    assert body["days_of_week"] == ["Thu"]
    assert body["start_time"] == "18:00"
    assert body["end_time"] == "18:45"


@pytest.mark.asyncio
async def test_edit_recurring_session_updates_series_and_future_clean_occurrences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-edit-recurring-series"]
    await db.sessions.insert_one(
        {
            "academy_id": "academy-b",
            "session_id": "series-edit",
            "title": "Wednesday Class",
            "location": "Court 1",
            "coach_id": "coach-old",
            "capacity": 10,
            "status": "scheduled",
            "days_of_week": ["Wed"],
            "start_time": "18:00",
            "end_time": "18:45",
            "timezone": "America/Chicago",
            "start_at": datetime(2026, 5, 27, 23, 0, tzinfo=UTC),
            "end_at": datetime(2026, 5, 27, 23, 45, tzinfo=UTC),
        }
    )
    protected_rows = [
        {
            "academy_id": "academy-b",
            "occurrence_id": "past-occ",
            "session_id": "series-edit",
            "template_session_id": "series-edit",
            "start_at": datetime(2026, 5, 27, 23, 0, tzinfo=UTC),
            "end_at": datetime(2026, 5, 27, 23, 45, tzinfo=UTC),
            "status": "completed",
            "scheduled_coach_id": "coach-old",
            "is_billable": True,
            "is_payable": True,
        },
        {
            "academy_id": "academy-b",
            "occurrence_id": "replacement-occ",
            "session_id": "series-edit",
            "template_session_id": "series-edit",
            "start_at": datetime(2026, 6, 10, 23, 0, tzinfo=UTC),
            "end_at": datetime(2026, 6, 10, 23, 45, tzinfo=UTC),
            "status": "scheduled",
            "scheduled_coach_id": "coach-old",
            "actual_coach_id": "coach-replacement",
            "is_billable": True,
            "is_payable": True,
        },
        {
            "academy_id": "academy-b",
            "occurrence_id": "attendance-occ",
            "session_id": "series-edit",
            "template_session_id": "series-edit",
            "start_at": datetime(2026, 6, 17, 23, 0, tzinfo=UTC),
            "end_at": datetime(2026, 6, 17, 23, 45, tzinfo=UTC),
            "status": "scheduled",
            "scheduled_coach_id": "coach-old",
            "is_billable": True,
            "is_payable": True,
        },
        {
            "academy_id": "academy-b",
            "occurrence_id": "payout-occ",
            "session_id": "series-edit",
            "template_session_id": "series-edit",
            "start_at": datetime(2026, 6, 24, 23, 0, tzinfo=UTC),
            "end_at": datetime(2026, 6, 24, 23, 45, tzinfo=UTC),
            "status": "scheduled",
            "scheduled_coach_id": "coach-old",
            "is_billable": True,
            "is_payable": True,
        },
    ]
    await db.session_occurrences.insert_many(
        [
            *protected_rows,
            {
                "academy_id": "academy-b",
                "occurrence_id": "clean-occ",
                "session_id": "series-edit",
                "template_session_id": "series-edit",
                "start_at": datetime(2026, 6, 3, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 6, 3, 23, 45, tzinfo=UTC),
                "status": "scheduled",
                "scheduled_coach_id": "coach-old",
                "is_billable": True,
                "is_payable": True,
            },
        ]
    )
    await db.attendance.insert_one(
        {
            "academy_id": "academy-b",
            "attendance_id": "att-1",
            "occurrence_id": "attendance-occ",
            "session_id": "series-edit",
            "student_id": "student-1",
            "marked_by": "coach-old",
            "marked_at": datetime(2026, 6, 17, 23, 50, tzinfo=UTC),
            "status": "present",
        }
    )
    await db.payout_period_lines.insert_one(
        {"academy_id": "academy-b", "occurrence_id": "payout-occ", "period_id": "period-1"}
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.patch(
            "/api/v2/admin/sessions/series-edit",
            json={
                "coach_id": "coach-new",
                "title": "Thursday Class",
                "location": "Court 2",
                "capacity": 12,
                "days_of_week": ["Thu"],
                "start_time": "18:15",
                "end_time": "19:00",
                "timezone": "America/Chicago",
                "reason": "recurring schedule correction",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["days_of_week"] == ["Thu"]
    assert body["start_time"] == "18:15"
    assert body["end_time"] == "19:00"

    stored_session = await db.sessions.find_one(
        {"academy_id": "academy-b", "session_id": "series-edit"}
    )
    assert stored_session["coach_id"] == "coach-new"
    assert stored_session["days_of_week"] == ["Thu"]
    assert stored_session["start_time"] == "18:15"
    assert stored_session["end_time"] == "19:00"

    assert await db.session_occurrences.find_one({"occurrence_id": "clean-occ"}) is None
    generated = [
        row
        async for row in db.session_occurrences.find(
            {
                "academy_id": "academy-b",
                "template_session_id": "series-edit",
                "occurrence_id": {"$regex": "^series-edit:"},
            },
            sort=[("start_at", 1)],
        )
    ]
    assert generated
    assert all(row["scheduled_coach_id"] == "coach-new" for row in generated)
    assert _as_utc(generated[0]["start_at"]) == datetime(2026, 6, 4, 23, 15, tzinfo=UTC)
    assert _as_utc(generated[0]["end_at"]) == datetime(2026, 6, 5, 0, 0, tzinfo=UTC)

    for protected in protected_rows:
        stored = await db.session_occurrences.find_one(
            {"occurrence_id": protected["occurrence_id"]}
        )
        assert stored is not None
        assert stored["scheduled_coach_id"] == "coach-old"
        assert _as_utc(stored["start_at"]) == protected["start_at"]


@pytest.mark.asyncio
async def test_replacement_endpoint_sets_actual_coach_without_changing_scheduled() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-replacement-occurrence"]
    await db.session_occurrences.insert_one(
        {
            "academy_id": "academy-b",
            "occurrence_id": "occ-replacement",
            "session_id": "series-replacement",
            "template_session_id": "series-replacement",
            "start_at": datetime(2026, 6, 4, 23, 15, tzinfo=UTC),
            "end_at": datetime(2026, 6, 5, 0, 0, tzinfo=UTC),
            "status": "scheduled",
            "scheduled_coach_id": "coach-scheduled",
            "is_billable": True,
            "is_payable": True,
        }
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.patch(
            "/api/v2/admin/session-occurrences/occ-replacement/replacement",
            json={
                "replacement_coach_id": "coach-replacement",
                "reason": "coach unavailable",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scheduled_coach_id"] == "coach-scheduled"
    assert body["actual_coach_id"] == "coach-replacement"
    assert body["substitute_coach_id"] is None


@pytest.mark.asyncio
async def test_session_replacement_endpoint_creates_occurrence_for_selected_recurring_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _FrozenAdminDateTime,
        "_now",
        datetime(2026, 6, 4, 14, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-replacement-by-date"]
    await db.sessions.insert_one(
        {
            "academy_id": "academy-b",
            "session_id": "series-wed",
            "title": "Wednesday Beginner",
            "location": "Court 1",
            "coach_id": "coach-scheduled",
            "capacity": 8,
            "status": "scheduled",
            "start_at": datetime(2026, 6, 3, 23, 0, tzinfo=UTC),
            "end_at": datetime(2026, 6, 3, 23, 45, tzinfo=UTC),
            "days_of_week": ["Wed"],
            "start_time": "18:00",
            "end_time": "18:45",
            "timezone": "America/Chicago",
        }
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.patch(
            "/api/v2/admin/sessions/series-wed/replacement",
            json={
                "date": "2026-06-10",
                "replacement_coach_id": "coach-replacement",
                "reason": "coach unavailable",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == "series-wed"
    assert body["scheduled_coach_id"] == "coach-scheduled"
    assert body["actual_coach_id"] == "coach-replacement"
    assert body["start_at"].startswith("2026-06-10T23:00:00")
    stored = await db.session_occurrences.find_one(
        {"academy_id": "academy-b", "occurrence_id": body["occurrence_id"]}
    )
    assert stored is not None
    assert stored["scheduled_coach_id"] == "coach-scheduled"
    assert stored["actual_coach_id"] == "coach-replacement"


@pytest.mark.asyncio
async def test_session_replacement_endpoint_updates_existing_dated_session_occurrence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _FrozenAdminDateTime,
        "_now",
        datetime(2026, 6, 4, 14, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-replacement-dated-session"]
    await db.sessions.insert_one(
        {
            "academy_id": "academy-b",
            "session_id": "dated-thu",
            "title": "Thursday Beginner",
            "location": "Court 1",
            "coach_id": "coach-scheduled",
            "capacity": 8,
            "status": "scheduled",
            "start_at": datetime(2026, 6, 4, 23, 0, tzinfo=UTC),
            "end_at": datetime(2026, 6, 4, 23, 45, tzinfo=UTC),
        }
    )
    await db.session_occurrences.insert_one(
        {
            "academy_id": "academy-b",
            "occurrence_id": "dated-thu",
            "session_id": "dated-thu",
            "template_session_id": "dated-thu",
            "start_at": datetime(2026, 6, 4, 23, 0, tzinfo=UTC),
            "end_at": datetime(2026, 6, 4, 23, 45, tzinfo=UTC),
            "status": "scheduled",
            "scheduled_coach_id": "coach-scheduled",
            "is_billable": True,
            "is_payable": True,
        }
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.patch(
            "/api/v2/admin/sessions/dated-thu/replacement",
            json={
                "date": "2026-06-04",
                "replacement_coach_id": "coach-replacement",
                "reason": "coach unavailable",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["occurrence_id"] == "dated-thu"
    assert body["session_id"] == "dated-thu"
    assert body["scheduled_coach_id"] == "coach-scheduled"
    assert body["actual_coach_id"] == "coach-replacement"
    stored = await db.session_occurrences.find_one(
        {"academy_id": "academy-b", "occurrence_id": "dated-thu"}
    )
    assert stored is not None
    assert stored["scheduled_coach_id"] == "coach-scheduled"
    assert stored["actual_coach_id"] == "coach-replacement"


@pytest.mark.asyncio
async def test_session_replacement_endpoint_infers_dated_weekly_series_for_future_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _FrozenAdminDateTime,
        "_now",
        datetime(2026, 6, 4, 14, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-replacement-dated-future-series"]
    await db.sessions.insert_many(
        [
            {
                "academy_id": "academy-b",
                "session_id": "dated-thu-jun4",
                "title": "Thursday Beginner",
                "location": "Court 1",
                "coach_id": "coach-scheduled",
                "capacity": 8,
                "status": "scheduled",
                "start_at": datetime(2026, 6, 4, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 6, 4, 23, 45, tzinfo=UTC),
            },
            {
                "academy_id": "academy-b",
                "session_id": "dated-thu-jun11",
                "title": "Thursday Beginner",
                "location": "Court 1",
                "coach_id": "coach-scheduled",
                "capacity": 8,
                "status": "scheduled",
                "start_at": datetime(2026, 6, 11, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 6, 11, 23, 45, tzinfo=UTC),
            },
        ]
    )
    await db.session_occurrences.insert_many(
        [
            {
                "academy_id": "academy-b",
                "occurrence_id": "dated-thu-jun4",
                "session_id": "dated-thu-jun4",
                "template_session_id": "dated-thu-jun4",
                "start_at": datetime(2026, 6, 4, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 6, 4, 23, 45, tzinfo=UTC),
                "status": "scheduled",
                "scheduled_coach_id": "coach-scheduled",
                "is_billable": True,
                "is_payable": True,
            },
            {
                "academy_id": "academy-b",
                "occurrence_id": "dated-thu-jun11",
                "session_id": "dated-thu-jun11",
                "template_session_id": "dated-thu-jun11",
                "start_at": datetime(2026, 6, 11, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 6, 11, 23, 45, tzinfo=UTC),
                "status": "scheduled",
                "scheduled_coach_id": "coach-scheduled",
                "is_billable": True,
                "is_payable": True,
            },
        ]
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.patch(
            "/api/v2/admin/sessions/dated-thu-jun4/replacement",
            json={
                "date": "2026-06-18",
                "replacement_coach_id": "coach-replacement",
                "reason": "coach unavailable",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == "dated-thu-jun4"
    assert body["scheduled_coach_id"] == "coach-scheduled"
    assert body["actual_coach_id"] == "coach-replacement"
    assert body["start_at"].startswith("2026-06-18T23:00:00")
    stored = await db.session_occurrences.find_one(
        {"academy_id": "academy-b", "occurrence_id": body["occurrence_id"]}
    )
    assert stored is not None
    assert stored["session_id"] == "dated-thu-jun4"
    assert stored["scheduled_coach_id"] == "coach-scheduled"
    assert stored["actual_coach_id"] == "coach-replacement"


@pytest.mark.asyncio
async def test_list_session_occurrences_includes_dated_weekly_series_replacements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _FrozenAdminDateTime,
        "_now",
        datetime(2026, 6, 4, 14, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-replacement-dated-series-list"]
    await db.sessions.insert_many(
        [
            {
                "academy_id": "academy-b",
                "session_id": "dated-thu-jun4",
                "title": "Thursday Beginner",
                "location": "Court 1",
                "coach_id": "coach-scheduled",
                "capacity": 8,
                "status": "scheduled",
                "start_at": datetime(2026, 6, 4, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 6, 4, 23, 45, tzinfo=UTC),
            },
            {
                "academy_id": "academy-b",
                "session_id": "dated-thu-jun11",
                "title": "Thursday Beginner",
                "location": "Court 1",
                "coach_id": "coach-scheduled",
                "capacity": 8,
                "status": "scheduled",
                "start_at": datetime(2026, 6, 11, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 6, 11, 23, 45, tzinfo=UTC),
            },
        ]
    )
    await db.session_occurrences.insert_many(
        [
            {
                "academy_id": "academy-b",
                "occurrence_id": "dated-thu-jun4",
                "session_id": "dated-thu-jun4",
                "template_session_id": "dated-thu-jun4",
                "start_at": datetime(2026, 6, 4, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 6, 4, 23, 45, tzinfo=UTC),
                "status": "scheduled",
                "scheduled_coach_id": "coach-scheduled",
                "actual_coach_id": "coach-replacement-a",
                "is_billable": True,
                "is_payable": True,
            },
            {
                "academy_id": "academy-b",
                "occurrence_id": "dated-thu-jun11",
                "session_id": "dated-thu-jun11",
                "template_session_id": "dated-thu-jun11",
                "start_at": datetime(2026, 6, 11, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 6, 11, 23, 45, tzinfo=UTC),
                "status": "scheduled",
                "scheduled_coach_id": "coach-scheduled",
                "actual_coach_id": "coach-replacement-b",
                "is_billable": True,
                "is_payable": True,
            },
            {
                "academy_id": "academy-b",
                "occurrence_id": "dated-thu-jun4:2026-06-18:18:00",
                "session_id": "dated-thu-jun4",
                "template_session_id": "dated-thu-jun4",
                "start_at": datetime(2026, 6, 18, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 6, 18, 23, 45, tzinfo=UTC),
                "status": "scheduled",
                "scheduled_coach_id": "coach-scheduled",
                "actual_coach_id": "coach-replacement-c",
                "is_billable": True,
                "is_payable": True,
            },
        ]
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.get("/api/v2/admin/sessions/dated-thu-jun4/occurrences")

    assert response.status_code == 200, response.text
    body = response.json()
    occurrence_ids = [row["occurrence_id"] for row in body["occurrences"]]
    assert occurrence_ids == [
        "dated-thu-jun4",
        "dated-thu-jun11",
        "dated-thu-jun4:2026-06-18:18:00",
    ]


@pytest.mark.asyncio
async def test_session_replacement_endpoint_rejects_non_session_weekday(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _FrozenAdminDateTime,
        "_now",
        datetime(2026, 6, 4, 14, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-replacement-wrong-weekday"]
    await db.sessions.insert_one(
        {
            "academy_id": "academy-b",
            "session_id": "series-wed",
            "title": "Wednesday Beginner",
            "location": "Court 1",
            "coach_id": "coach-scheduled",
            "capacity": 8,
            "status": "scheduled",
            "start_at": datetime(2026, 6, 3, 23, 0, tzinfo=UTC),
            "end_at": datetime(2026, 6, 3, 23, 45, tzinfo=UTC),
            "days_of_week": ["Wed"],
            "start_time": "18:00",
            "end_time": "18:45",
            "timezone": "America/Chicago",
        }
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.patch(
            "/api/v2/admin/sessions/series-wed/replacement",
            json={
                "date": "2026-06-11",
                "replacement_coach_id": "coach-replacement",
            },
        )

    assert response.status_code == 409, response.text
    assert "weekday" in response.json()["detail"]
    assert await db.session_occurrences.count_documents({"academy_id": "academy-b"}) == 0


@pytest.mark.asyncio
async def test_session_replacement_endpoint_rejects_date_outside_maintenance_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _FrozenAdminDateTime,
        "_now",
        datetime(2026, 6, 4, 14, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-replacement-outside-window"]
    await db.sessions.insert_one(
        {
            "academy_id": "academy-b",
            "session_id": "series-wed",
            "title": "Wednesday Beginner",
            "location": "Court 1",
            "coach_id": "coach-scheduled",
            "capacity": 8,
            "status": "scheduled",
            "start_at": datetime(2026, 6, 3, 23, 0, tzinfo=UTC),
            "end_at": datetime(2026, 6, 3, 23, 45, tzinfo=UTC),
            "days_of_week": ["Wed"],
            "start_time": "18:00",
            "end_time": "18:45",
            "timezone": "America/Chicago",
        }
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.patch(
            "/api/v2/admin/sessions/series-wed/replacement",
            json={
                "date": "2026-06-03",
                "replacement_coach_id": "coach-replacement",
            },
        )

    assert response.status_code == 409, response.text
    assert "60 days" in response.json()["detail"]
    assert await db.session_occurrences.count_documents({"academy_id": "academy-b"}) == 0


@pytest.mark.asyncio
async def test_replacement_endpoint_clears_draft_payout_snapshot_for_recalculation() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-replacement-draft-payout"]
    await db.session_occurrences.insert_one(
        {
            "academy_id": "academy-b",
            "occurrence_id": "occ-draft-payout",
            "session_id": "series-replacement",
            "template_session_id": "series-replacement",
            "start_at": datetime(2026, 6, 4, 23, 15, tzinfo=UTC),
            "end_at": datetime(2026, 6, 5, 0, 0, tzinfo=UTC),
            "status": "completed",
            "scheduled_coach_id": "coach-scheduled",
            "is_billable": True,
            "is_payable": True,
        }
    )
    await db.payout_periods.insert_one(
        {
            "academy_id": "academy-b",
            "period_id": "pp-draft",
            "coach_id": "coach-scheduled",
            "period_start": datetime(2026, 6, 1, tzinfo=UTC),
            "period_end": datetime(2026, 7, 1, tzinfo=UTC),
            "status": "draft",
            "currency": "USD",
            "total_minor": 2500,
            "unpaid_occurrence_ids": [],
            "generated_at": datetime(2026, 6, 6, tzinfo=UTC),
        }
    )
    await db.payout_period_lines.insert_one(
        {
            "academy_id": "academy-b",
            "period_id": "pp-draft",
            "occurrence_id": "occ-draft-payout",
            "coach_id": "coach-scheduled",
            "basis": "scheduled",
            "minutes": "45",
            "amount_minor": 2500,
            "currency": "USD",
            "rate_id": "rate-scheduled",
        }
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.patch(
            "/api/v2/admin/session-occurrences/occ-draft-payout/replacement",
            json={"replacement_coach_id": "coach-replacement"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["actual_coach_id"] == "coach-replacement"
    assert await db.payout_periods.count_documents({"academy_id": "academy-b"}) == 0
    assert await db.payout_period_lines.count_documents({"academy_id": "academy-b"}) == 0


@pytest.mark.asyncio
async def test_replacement_endpoint_rejects_finalized_payout_occurrence() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-replacement-approved-payout"]
    await db.session_occurrences.insert_one(
        {
            "academy_id": "academy-b",
            "occurrence_id": "occ-approved-payout",
            "session_id": "series-replacement",
            "template_session_id": "series-replacement",
            "start_at": datetime(2026, 6, 4, 23, 15, tzinfo=UTC),
            "end_at": datetime(2026, 6, 5, 0, 0, tzinfo=UTC),
            "status": "completed",
            "scheduled_coach_id": "coach-scheduled",
            "is_billable": True,
            "is_payable": True,
        }
    )
    await db.payout_periods.insert_one(
        {
            "academy_id": "academy-b",
            "period_id": "pp-approved",
            "coach_id": "coach-scheduled",
            "period_start": datetime(2026, 6, 1, tzinfo=UTC),
            "period_end": datetime(2026, 7, 1, tzinfo=UTC),
            "status": "approved",
            "currency": "USD",
            "total_minor": 2500,
            "unpaid_occurrence_ids": [],
            "generated_at": datetime(2026, 6, 6, tzinfo=UTC),
            "approved_at": datetime(2026, 6, 7, tzinfo=UTC),
        }
    )
    await db.payout_period_lines.insert_one(
        {
            "academy_id": "academy-b",
            "period_id": "pp-approved",
            "occurrence_id": "occ-approved-payout",
            "coach_id": "coach-scheduled",
            "basis": "scheduled",
            "minutes": "45",
            "amount_minor": 2500,
            "currency": "USD",
            "rate_id": "rate-scheduled",
        }
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.patch(
            "/api/v2/admin/session-occurrences/occ-approved-payout/replacement",
            json={"replacement_coach_id": "coach-replacement"},
        )

    assert response.status_code == 409, response.text
    assert "payout is approved or paid" in response.json()["detail"]
    stored = await db.session_occurrences.find_one(
        {"academy_id": "academy-b", "occurrence_id": "occ-approved-payout"}
    )
    assert stored.get("actual_coach_id") is None


@pytest.mark.parametrize("legacy_status", ["active", "open"])
@pytest.mark.asyncio
async def test_legacy_template_session_writer_get_normalizes_domain_for_registration_paths(
    legacy_status: str,
) -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()[
        f"admin-template-writer-normalization-{legacy_status}"
    ]
    await db.sessions.insert_one(
        {
            "academy_id": "academy-b",
            "session_id": f"tpl-registration-target-{legacy_status}",
            "name": "Registration Template",
            "location": "Court 4",
            "coach_id": "coach-4",
            "max_students": 7,
            "reserved_seats": 0,
            "status": legacy_status,
            "days_of_week": ["Mon"],
            "start_time": "17:00",
            "end_time": "18:00",
            "timezone": "America/Chicago",
        }
    )

    with tenant_scope("academy-b"):
        writer = MongoSessionWriter(db)
        session = await writer.get(f"tpl-registration-target-{legacy_status}")
        reserved = await writer.try_reserve_seat(f"tpl-registration-target-{legacy_status}")

    assert session is not None
    assert session.status == "scheduled"
    assert session.capacity == 7
    assert reserved is True
    stored = await db.sessions.find_one(
        {"academy_id": "academy-b", "session_id": f"tpl-registration-target-{legacy_status}"}
    )
    assert stored["reserved_seats"] == 1


@pytest.mark.asyncio
async def test_legacy_template_writer_reserves_by_object_id_when_session_id_missing() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-template-writer-object-id"]
    result = await db.sessions.insert_one(
        {
            "academy_id": "academy-b",
            "name": "ObjectId Registration Template",
            "location": "Court 5",
            "coach_id": "coach-5",
            "max_students": 4,
            "reserved_seats": 0,
            "status": "open",
            "days_of_week": ["Mon"],
            "start_time": "17:00",
            "end_time": "18:00",
            "timezone": "America/Chicago",
        }
    )
    listed_id = str(result.inserted_id)

    with tenant_scope("academy-b"):
        writer = MongoSessionWriter(db)
        repo = MongoSessionRepository(db)
        session = await writer.get(listed_id)
        session_via_repo = await repo.get(listed_id)
        [session_via_get_many] = await repo.get_many([listed_id])
        reserved = await writer.try_reserve_seat(listed_id)
        await writer.release_seat(listed_id)
        await writer.update_status(listed_id, "cancelled")

    assert session is not None
    assert session.session_id == listed_id
    assert session.status == "scheduled"
    assert session_via_repo is not None
    assert session_via_repo.session_id == listed_id
    assert session_via_get_many.session_id == listed_id
    assert reserved is True
    stored = await db.sessions.find_one({"_id": result.inserted_id})
    assert stored["reserved_seats"] == 0
    assert stored["status"] == "cancelled"


def test_list_sessions_coach_persona_returns_404(coach_on_admin_client):
    r = coach_on_admin_client.get("/api/v2/admin/sessions?date=2026-05-16")
    assert r.status_code == 404


def test_list_sessions_parent_persona_returns_404(parent_on_admin_client):
    r = parent_on_admin_client.get("/api/v2/admin/sessions?date=2026-05-16")
    assert r.status_code == 404


def test_list_session_occurrences_shows_assignment_state(admin_client):
    r = admin_client.get("/api/v2/admin/sessions/sess-1/occurrences")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["occurrences"] == [
        {
            "occurrence_id": "occ-admin-1",
            "session_id": "sess-1",
            "start_at": "2026-05-16T09:00:00Z",
            "end_at": "2026-05-16T10:30:00Z",
            "status": "scheduled",
            "scheduled_coach_id": "coach-1",
            "actual_coach_id": None,
            "substitute_coach_id": None,
            "attendance_marked_count": 0,
            "attendance_marked_by": [],
            "attendance_last_marked_at": None,
            "coach_attendance": [],
        }
    ]


def test_update_session_occurrence_actual_coach(admin_client):
    r = admin_client.patch(
        "/api/v2/admin/session-occurrences/occ-admin-1/coach",
        json={
            "actual_coach_id": "coach-2",
            "substitute_coach_id": "coach-3",
            "reason": "substitute",
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["occurrence_id"] == "occ-admin-1"
    assert body["actual_coach_id"] == "coach-2"
    assert body["substitute_coach_id"] == "coach-3"
    assert admin_client.seed["occurrences"].rows["occ-admin-1"].actual_coach_id == "coach-2"
    assert admin_client.seed["occurrences"].rows["occ-admin-1"].substitute_coach_id == "coach-3"


def test_admin_can_mark_occurrence_coach_attendance(admin_client):
    r = admin_client.patch(
        "/api/v2/admin/session-occurrences/occ-admin-1/coach-attendance",
        json={
            "coach_id": "coach-2",
            "status": "present",
            "role": "assistant",
            "rate_override_minor": 1500,
            "note": "Helped with beginner court",
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["occurrence_id"] == "occ-admin-1"
    assert body["coach_id"] == "coach-2"
    assert body["status"] == "present"
    assert body["role"] == "assistant"
    assert body["rate_override_minor"] == 1500
    assert body["note"] == "Helped with beginner court"

    listing = admin_client.get("/api/v2/admin/sessions/sess-1/occurrences").json()
    assert listing["occurrences"][0]["coach_attendance"][0]["coach_id"] == "coach-2"


def test_list_session_occurrences_wrong_persona_returns_404(coach_on_admin_client):
    r = coach_on_admin_client.get("/api/v2/admin/sessions/sess-1/occurrences")
    assert r.status_code == 404


def test_create_session_happy_path(admin_client):
    r = admin_client.post(
        "/api/v2/admin/sessions",
        json={
            "coach_id": "coach-2",
            "title": "Adult B",
            "location": "Court 2",
            "start_at": "2026-05-17T09:00:00Z",
            "end_at": "2026-05-17T10:30:00Z",
            "capacity": 6,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Adult B"
    assert body["capacity"] == 6
    # Confirms list reflects the new session.
    listing = admin_client.get("/api/v2/admin/sessions?date=2026-05-17").json()
    assert any(s["session_id"] == body["session_id"] for s in listing["sessions"])


def test_create_session_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.post(
        "/api/v2/admin/sessions",
        json={
            "coach_id": "x",
            "title": "x",
            "location": "x",
            "start_at": "2026-05-17T09:00:00Z",
            "end_at": "2026-05-17T10:30:00Z",
            "capacity": 4,
        },
    )
    assert r.status_code == 404


def test_cancel_session_returns_204(admin_client):
    r = admin_client.delete("/api/v2/admin/sessions/sess-1")
    assert r.status_code == 204
    # session is now cancelled in the seed
    assert admin_client.seed["sessions"].sessions["sess-1"].status == "cancelled"


def test_add_to_roster_then_list_enrollments(admin_client):
    r = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    assert r.status_code == 200, r.text
    enrollment_id = r.json()["enrollment_id"]
    # The composition's enrollment_query is a separate fake from the writer
    # (since the production code uses two ports). Wire them: copy the row.
    admin_client.seed["enrollment_query"].rows = dict(admin_client.seed["enrollments"].rows)
    listing = admin_client.get("/api/v2/admin/sessions/sess-1/enrollments").json()
    assert any(e["enrollment_id"] == enrollment_id for e in listing["enrollments"])
    assert any(e["student_name"] == "Alice" for e in listing["enrollments"])


def test_list_enrollments_includes_level_and_dues_status(admin_client):
    r = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    assert r.status_code == 200, r.text
    admin_client.seed["enrollment_query"].rows = dict(admin_client.seed["enrollments"].rows)
    admin_client.seed["students"].admin_levels["st-1"] = "7"
    admin_client.seed["students"].admin_status["st-1"] = "overdue"

    listing = admin_client.get("/api/v2/admin/sessions/sess-1/enrollments")

    assert listing.status_code == 200, listing.text
    [row] = listing.json()["enrollments"]
    assert row["level"] == "7"
    assert row["dues_status"] == "overdue"


def test_add_to_roster_wrong_persona_404(parent_on_admin_client):
    r = parent_on_admin_client.post(
        "/api/v2/admin/enrollments",
        json={"session_id": "sess-1", "student_id": "x", "parent_id": "x", "full_name": "x"},
    )
    assert r.status_code == 404


def test_pause_and_resume_enrollment(admin_client):
    # Create an enrollment first.
    r = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    enrollment_id = r.json()["enrollment_id"]

    p = admin_client.post(
        f"/api/v2/admin/enrollments/{enrollment_id}/pause",
        json={"effective_date": "2026-05-20", "reason": "temporary pause"},
    )
    assert p.status_code == 204
    assert admin_client.seed["enrollments"].rows[enrollment_id].status == "paused"
    paused_listing = admin_client.get("/api/v2/admin/sessions/sess-1/enrollments").json()
    assert paused_listing["enrollments"] == []
    waiting = [
        entry
        for entry in admin_client.seed["waitlist"].entries.values()
        if entry.student_id == "st-1" and entry.status == "waiting"
    ]
    assert len(waiting) == 1

    res = admin_client.post(f"/api/v2/admin/enrollments/{enrollment_id}/resume")
    assert res.status_code == 204
    assert admin_client.seed["enrollments"].rows[enrollment_id].status == "active"
    resumed_listing = admin_client.get("/api/v2/admin/sessions/sess-1/enrollments").json()
    assert [entry["enrollment_id"] for entry in resumed_listing["enrollments"]] == [enrollment_id]
    assert [
        entry
        for entry in admin_client.seed["waitlist"].entries.values()
        if entry.student_id == "st-1" and entry.status == "waiting"
    ] == []

    p2 = admin_client.post(
        f"/api/v2/admin/enrollments/{enrollment_id}/pause",
        json={"effective_date": "2026-05-21", "reason": "second temporary pause"},
    )
    assert p2.status_code == 204
    waiting_after_second_pause = [
        entry
        for entry in admin_client.seed["waitlist"].entries.values()
        if entry.student_id == "st-1" and entry.status == "waiting"
    ]
    assert len(waiting_after_second_pause) == 1


def test_transfer_enrollment_reserves_target_and_releases_source(admin_client):
    create_target = admin_client.post(
        "/api/v2/admin/sessions",
        json={
            "coach_id": "coach-2",
            "title": "Adult B",
            "location": "Court 2",
            "start_at": "2026-05-17T09:00:00Z",
            "end_at": "2026-05-17T10:30:00Z",
            "capacity": 6,
        },
    )
    target_session_id = create_target.json()["session_id"]
    add = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    enrollment_id = add.json()["enrollment_id"]

    r = admin_client.post(
        f"/api/v2/admin/enrollments/{enrollment_id}/transfer",
        json={
            "target_session_id": target_session_id,
            "effective_date": "2026-05-20",
            "reason": "schedule change",
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["session_id"] == target_session_id
    assert admin_client.seed["enrollments"].rows[enrollment_id].session_id == target_session_id
    assert admin_client.seed["enrollments"].move_history == [
        {
            "enrollment_id": enrollment_id,
            "from_session_id": "sess-1",
            "to_session_id": target_session_id,
        }
    ]
    assert admin_client.seed["sessions"].reserved[target_session_id] == 1
    assert admin_client.seed["sessions"].reserved["sess-1"] == 0


def test_cancel_enrollment_emits_event(admin_client):
    r = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    enrollment_id = r.json()["enrollment_id"]
    outbox_len_before = len(admin_client.seed["outbox"].events)
    d = admin_client.request(
        "DELETE",
        f"/api/v2/admin/enrollments/{enrollment_id}",
        json={"effective_date": "2026-05-20", "reason": "admin cleanup"},
    )
    assert d.status_code == 204
    # EnrollmentCancelled event was appended.
    new_events = admin_client.seed["outbox"].events[outbox_len_before:]
    assert any(e.name == "Enrollment.EnrollmentCancelled" for e in new_events)
