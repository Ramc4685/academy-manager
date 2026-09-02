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

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import backend.v2.composition.admin as admin_composition
from backend.v2.composition.admin import compose_admin
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.coaching.domain.payout import CoachRate
from backend.v2.contexts.coaching.infrastructure.mongo_payout_read_models import (
    MongoPayableOccurrenceQuery,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import MongoSessionRepository
from backend.v2.contexts.enrollment.infrastructure.mongo_session_writer import MongoSessionWriter
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.interfaces.admin.views import AdminSessionView
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


def _percent_rate(coach_id: str = "coach-percent") -> CoachRate:
    return CoachRate(
        rate_id=f"rate-{coach_id}",
        academy_id="acad",
        coach_id=coach_id,
        billing_unit="percent_of_revenue",
        amount_minor=0,
        percent_bps=6000,
        currency="USD",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_until=None,
        status="active",
    )


class _ListCoachPayRates:
    def __init__(self, rates: list[CoachRate]) -> None:
        self.rates = rates

    async def execute(self, *, coach_id: str) -> list[CoachRate]:
        return [rate for rate in self.rates if rate.coach_id == coach_id]


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
async def test_admin_session_enrollments_include_pathway_placement_fields() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-session-pathway-roster"]
    now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    await db.sessions.insert_one(
        {
            "academy_id": "academy-b",
            "session_id": "sess-pathway",
            "title": "Pathway Session",
            "coach_id": "coach-1",
            "capacity": 8,
            "status": "scheduled",
            "start_at": now,
            "end_at": now + timedelta(hours=1),
        }
    )
    await db.students.insert_one(
        {
            "academy_id": "academy-b",
            "student_id": "st-pathway",
            "first_name": "Maya",
            "last_name": "Raman",
            "full_name": "Maya Raman",
            "parent_id": "parent-1",
            "status": "active",
            "level": "7",
            "is_deleted": False,
            "created_at": now,
        }
    )
    await db.enrollments.insert_one(
        {
            "academy_id": "academy-b",
            "enrollment_id": "enr-pathway",
            "session_id": "sess-pathway",
            "student_id": "st-pathway",
            "parent_id": "parent-1",
            "status": "active",
            "enrolled_at": now,
            "created_at": now,
        }
    )
    await db.skill_programs.insert_one(
        {
            "academy_id": "academy-b",
            "program_id": "program-1",
            "sport": "badminton",
            "name": "Badminton Skill Pathway",
            "description": "",
            "is_active": True,
            "created_at": now,
            "updated_at": now,
            "created_by": "admin-1",
        }
    )
    await db.skill_levels.insert_one(
        {
            "academy_id": "academy-b",
            "level_id": "level-2",
            "program_id": "program-1",
            "sequence": 2,
            "name": "Rally Builder",
            "description": "",
            "completion_rule": "ALL_REQUIRED_SKILLS",
            "requires_coach_recommendation": True,
            "requires_admin_approval": False,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
            "created_by": "admin-1",
        }
    )
    await db.skills.insert_many(
        [
            {
                "academy_id": "academy-b",
                "skill_id": "skill-1",
                "level_id": "level-2",
                "program_id": "program-1",
                "sequence": 1,
                "name": "Serve",
                "description": "",
                "is_required": True,
                "scoring_type": "ATTEMPT_BASED",
                "pass_threshold_pct": 70.0,
                "coach_override_allowed": False,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
                "created_by": "admin-1",
            },
            {
                "academy_id": "academy-b",
                "skill_id": "skill-2",
                "level_id": "level-2",
                "program_id": "program-1",
                "sequence": 2,
                "name": "Clear",
                "description": "",
                "is_required": True,
                "scoring_type": "ATTEMPT_BASED",
                "pass_threshold_pct": 70.0,
                "coach_override_allowed": False,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
                "created_by": "admin-1",
            },
        ]
    )
    await db.student_level_progress.insert_one(
        {
            "academy_id": "academy-b",
            "progress_id": "progress-1",
            "student_id": "st-pathway",
            "program_id": "program-1",
            "level_id": "level-2",
            "status": "active",
            "started_at": now,
            "completed_at": None,
            "created_at": now,
        }
    )
    await db.student_skill_progress.insert_one(
        {
            "academy_id": "academy-b",
            "skill_progress_id": "skill-progress-1",
            "student_id": "st-pathway",
            "skill_id": "skill-1",
            "level_id": "level-2",
            "program_id": "program-1",
            "status": "PASSED",
            "introduced_at": None,
            "last_updated_at": now,
            "last_updated_by": "coach-1",
        }
    )

    app = _mongo_admin_app(db)

    with TestClient(app) as client:
        response = client.get("/api/v2/admin/sessions/sess-pathway/enrollments")

    assert response.status_code == 200, response.text
    [row] = response.json()["enrollments"]
    assert row["pathway_program_id"] == "program-1"
    assert row["pathway_level_id"] == "level-2"
    assert row["pathway_level_sequence"] == 2
    assert row["pathway_level_name"] == "Rally Builder"
    assert row["pathway_placement_status"] == "active"
    assert row["pathway_skills_total"] == 2
    assert row["pathway_skills_completed"] == 1
    assert row["pathway_completion_percentage"] == 50


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
async def test_admin_session_create_and_edit_persist_monthly_amount_cents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-session-monthly-fee"]

    with TestClient(_mongo_admin_app(db)) as client:
        create_response = client.post(
            "/api/v2/admin/sessions",
            json={
                "coach_id": "coach-fee",
                "title": "Beginner Monthly",
                "location": "Court 1",
                "days_of_week": ["Wed"],
                "start_time": "18:00",
                "end_time": "18:45",
                "timezone": "America/Chicago",
                "capacity": 15,
                "amount_cents": 6000,
            },
        )

    assert create_response.status_code == 200, create_response.text
    created = create_response.json()
    assert created["amount_cents"] == 6000
    stored = await db.sessions.find_one(
        {"academy_id": "academy-b", "session_id": created["session_id"]}
    )
    assert stored is not None
    assert stored["amount_cents"] == 6000

    with TestClient(_mongo_admin_app(db)) as client:
        edit_response = client.patch(
            f"/api/v2/admin/sessions/{created['session_id']}",
            json={"amount_cents": 7500, "reason": "monthly fee updated"},
        )

    assert edit_response.status_code == 200, edit_response.text
    assert edit_response.json()["amount_cents"] == 7500
    updated = await db.sessions.find_one(
        {"academy_id": "academy-b", "session_id": created["session_id"]}
    )
    assert updated is not None
    assert updated["amount_cents"] == 7500

    with TestClient(_mongo_admin_app(db)) as client:
        clear_response = client.patch(
            f"/api/v2/admin/sessions/{created['session_id']}",
            json={"amount_cents": None, "reason": "pricing not configured"},
        )

    assert clear_response.status_code == 200, clear_response.text
    assert clear_response.json()["amount_cents"] is None
    cleared = await db.sessions.find_one(
        {"academy_id": "academy-b", "session_id": created["session_id"]}
    )
    assert cleared is not None
    assert cleared["amount_cents"] is None


def test_admin_session_create_blocks_missing_price_for_percent_paid_coach(admin_client) -> None:
    admin_client.use_cases.list_coach_pay_rates = _ListCoachPayRates([_percent_rate()])

    response = admin_client.post(
        "/api/v2/admin/sessions",
        json={
            "coach_id": "coach-percent",
            "title": "Percent Missing Price",
            "location": "Court 1",
            "days_of_week": ["Wed"],
            "start_time": "18:00",
            "end_time": "18:45",
            "timezone": "America/Chicago",
            "capacity": 15,
        },
    )

    assert response.status_code == 400
    assert "Percent-of-revenue coach pay requires a session price" in response.json()["detail"]


def test_admin_session_create_allows_explicit_zero_price_for_percent_paid_coach(
    admin_client,
) -> None:
    admin_client.use_cases.list_coach_pay_rates = _ListCoachPayRates([_percent_rate()])

    response = admin_client.post(
        "/api/v2/admin/sessions",
        json={
            "coach_id": "coach-percent",
            "title": "Percent Free Session",
            "location": "Court 1",
            "days_of_week": ["Thu"],
            "start_time": "19:00",
            "end_time": "19:45",
            "timezone": "America/Chicago",
            "capacity": 15,
            "amount_cents": 0,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["amount_cents"] == 0


@pytest.mark.asyncio
async def test_admin_session_edit_blocks_clearing_price_for_percent_paid_coach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-session-percent-clear-blocked"]
    await db.sessions.insert_one(
        {
            "academy_id": "academy-b",
            "session_id": "session-percent-price",
            "title": "Percent Price",
            "location": "Court 1",
            "coach_id": "coach-percent",
            "capacity": 15,
            "amount_cents": 7500,
            "status": "scheduled",
            "days_of_week": ["Wed"],
            "start_time": "18:00",
            "end_time": "18:45",
            "timezone": "America/Chicago",
            "start_at": datetime(2026, 6, 3, 23, 0, tzinfo=UTC),
            "end_at": datetime(2026, 6, 3, 23, 45, tzinfo=UTC),
        }
    )
    await db.coach_rates.insert_one(
        {
            "academy_id": "academy-b",
            "rate_id": "rate-percent",
            "coach_id": "coach-percent",
            "billing_unit": "percent_of_revenue",
            "amount_minor": 0,
            "percent_bps": 6000,
            "currency": "USD",
            "effective_from": datetime(2026, 1, 1, tzinfo=UTC),
            "effective_until": None,
            "status": "active",
        }
    )

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.patch(
            "/api/v2/admin/sessions/session-percent-price",
            json={"amount_cents": None, "reason": "pricing not configured"},
        )

    assert response.status_code == 400
    assert "Percent-of-revenue coach pay requires a session price" in response.json()["detail"]
    stored = await db.sessions.find_one(
        {"academy_id": "academy-b", "session_id": "session-percent-price"}
    )
    assert stored is not None
    assert stored["amount_cents"] == 7500


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
async def test_session_replacement_endpoint_uses_matching_dated_weekly_series_date(
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
                "date": "2026-06-11",
                "replacement_coach_id": "coach-replacement",
                "reason": "coach unavailable",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == "dated-thu-jun11"
    assert body["scheduled_coach_id"] == "coach-scheduled"
    assert body["actual_coach_id"] == "coach-replacement"
    assert body["start_at"].startswith("2026-06-11T23:00:00")
    stored = await db.session_occurrences.find_one(
        {"academy_id": "academy-b", "occurrence_id": body["occurrence_id"]}
    )
    assert stored is not None
    assert stored["session_id"] == "dated-thu-jun11"
    assert stored["scheduled_coach_id"] == "coach-scheduled"
    assert stored["actual_coach_id"] == "coach-replacement"

    with TestClient(_mongo_admin_app(db)) as client:
        unscheduled = client.patch(
            "/api/v2/admin/sessions/dated-thu-jun4/replacement",
            json={
                "date": "2026-06-18",
                "replacement_coach_id": "coach-replacement",
                "reason": "coach unavailable",
            },
        )

    assert unscheduled.status_code == 409, unscheduled.text
    assert "scheduled session date" in unscheduled.json()["detail"]


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
        json={
            "effective_date": "2026-05-20",
            "reason": "temporary pause",
            "review_on": "2026-06-01",
        },
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
        json={
            "effective_date": "2026-05-21",
            "reason": "second temporary pause",
            "review_on": "2026-06-02",
        },
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


def test_override_enrollment_fee_updates_regular_enrollment(admin_client):
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

    waived = admin_client.post(
        f"/api/v2/admin/enrollments/{enrollment_id}/fee",
        json={"amount_cents": 0, "reason": "scholarship"},
    )
    assert waived.status_code == 204, waived.text
    assert admin_client.seed["enrollments"].amounts[enrollment_id] == 0

    cleared = admin_client.post(
        f"/api/v2/admin/enrollments/{enrollment_id}/fee",
        json={"amount_cents": None, "reason": "restore default"},
    )
    assert cleared.status_code == 204, cleared.text
    assert admin_client.seed["enrollments"].amounts[enrollment_id] is None


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


def test_admin_can_correct_student_attendance_any_time(admin_client):
    # Fixture clock is >48h after the seeded mark — the coach window is
    # irrelevant for admins (#517).
    r = admin_client.patch(
        "/api/v2/admin/session-occurrences/occ-admin-1/attendance/st-1",
        json={"status": "absent", "reason": "parent reported no-show"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "absent"
    assert body["previous_status"] == "present"
    assert body["corrected_by"] == "u-admin"
    assert body["corrected_at"]


def test_admin_correct_student_attendance_missing_mark_404(admin_client):
    r = admin_client.patch(
        "/api/v2/admin/session-occurrences/occ-admin-1/attendance/ghost",
        json={"status": "absent"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "Coaching.AttendanceNotFound"


# --- issue #467: cancel is a soft delete; cancelled sessions must not re-list ---


@pytest.mark.asyncio
async def test_cancelled_sessions_excluded_from_upcoming_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for #467.

    `DELETE /admin/sessions/{id}` only stamps status="cancelled"; the doc stays
    in `sessions`. Both the dated query and the recurring-template query must
    drop cancelled rows, while docs with a missing/None status still list.
    """
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-upcoming-cancelled"]
    start = datetime(2026, 6, 3, 15, 0, tzinfo=UTC)
    await db.sessions.insert_many(
        [
            {
                "academy_id": "academy-b",
                "session_id": "sess-live",
                "title": "Live Dated",
                "location": "Court 1",
                "coach_id": "coach-1",
                "capacity": 8,
                "status": "scheduled",
                "start_at": start,
                "end_at": start + timedelta(hours=1),
            },
            {
                "academy_id": "academy-b",
                "session_id": "sess-cancelled",
                "title": "Cancelled Dated",
                "location": "Court 2",
                "coach_id": "coach-2",
                "capacity": 8,
                "status": "cancelled",
                "start_at": start + timedelta(hours=2),
                "end_at": start + timedelta(hours=3),
            },
            {
                # Legacy doc with no status field at all — must still appear.
                "academy_id": "academy-b",
                "session_id": "sess-no-status",
                "title": "Legacy No Status",
                "location": "Court 3",
                "coach_id": "coach-3",
                "capacity": 8,
                "start_at": start + timedelta(days=1),
                "end_at": start + timedelta(days=1, hours=1),
            },
            {
                # Legacy doc with an explicit null status — must still appear.
                "academy_id": "academy-b",
                "session_id": "sess-null-status",
                "title": "Legacy Null Status",
                "location": "Court 4",
                "coach_id": "coach-4",
                "capacity": 8,
                "status": None,
                "start_at": start + timedelta(days=2),
                "end_at": start + timedelta(days=2, hours=1),
            },
            {
                "academy_id": "academy-b",
                "session_id": "tpl-live",
                "name": "Live Recurring",
                "location": "Court 5",
                "coach_id": "coach-5",
                "max_students": 10,
                "status": "active",
                "days_of_week": ["Mon"],
                "start_time": "09:15",
                "end_time": "10:15",
                "timezone": "America/Chicago",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
            },
            {
                "academy_id": "academy-b",
                "session_id": "tpl-cancelled",
                "name": "Cancelled Recurring",
                "location": "Court 6",
                "coach_id": "coach-6",
                "max_students": 10,
                "status": "cancelled",
                "days_of_week": ["Mon", "Wed"],
                "start_time": "11:15",
                "end_time": "12:15",
                "timezone": "America/Chicago",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
            },
        ]
    )

    app = _mongo_admin_app(db)
    with TestClient(app) as client:
        response = client.get("/api/v2/admin/sessions?window=upcoming")

    assert response.status_code == 200, response.text
    sessions = response.json()["sessions"]
    session_ids = [session["session_id"] for session in sessions]

    assert "sess-cancelled" not in session_ids
    assert "tpl-cancelled" not in session_ids
    # No synthesized occurrence of the cancelled template leaked in either.
    assert not any(row["title"] == "Cancelled Recurring" for row in sessions)
    assert not any(row["status"] == "cancelled" for row in sessions)

    # Live rows and legacy status-less rows are untouched.
    assert "sess-live" in session_ids
    assert "tpl-live" in session_ids
    assert "sess-no-status" in session_ids
    assert "sess-null-status" in session_ids


@pytest.mark.asyncio
async def test_cancelled_sessions_excluded_from_date_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `?date=` branch has the same status-blindness; fix it consistently."""
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-date-cancelled"]
    start = datetime(2026, 6, 3, 15, 0, tzinfo=UTC)
    await db.sessions.insert_many(
        [
            {
                "academy_id": "academy-b",
                "session_id": "sess-live",
                "title": "Live Dated",
                "location": "Court 1",
                "coach_id": "coach-1",
                "capacity": 8,
                "status": "scheduled",
                "start_at": start,
                "end_at": start + timedelta(hours=1),
            },
            {
                "academy_id": "academy-b",
                "session_id": "sess-cancelled",
                "title": "Cancelled Dated",
                "location": "Court 2",
                "coach_id": "coach-2",
                "capacity": 8,
                "status": "cancelled",
                "start_at": start + timedelta(hours=2),
                "end_at": start + timedelta(hours=3),
            },
            {
                "academy_id": "academy-b",
                "session_id": "sess-no-status",
                "title": "Legacy No Status",
                "location": "Court 3",
                "coach_id": "coach-3",
                "capacity": 8,
                "start_at": start + timedelta(hours=4),
                "end_at": start + timedelta(hours=5),
            },
            {
                "academy_id": "academy-b",
                "session_id": "tpl-cancelled",
                "name": "Cancelled Recurring",
                "location": "Court 4",
                "coach_id": "coach-4",
                "max_students": 10,
                "status": "cancelled",
                "days_of_week": ["Wed"],
                "start_time": "09:15",
                "end_time": "10:15",
                "timezone": "America/Chicago",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
            },
        ]
    )

    app = _mongo_admin_app(db)
    with TestClient(app) as client:
        response = client.get("/api/v2/admin/sessions?date=2026-06-03")

    assert response.status_code == 200, response.text
    session_ids = [session["session_id"] for session in response.json()["sessions"]]
    assert "sess-cancelled" not in session_ids
    assert "tpl-cancelled" not in session_ids
    assert "sess-live" in session_ids
    assert "sess-no-status" in session_ids


@pytest.mark.asyncio
async def test_cancel_session_then_relist_drops_the_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end #467: DELETE then re-list, and the row is gone."""
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-cancel-then-relist"]
    start = datetime(2026, 6, 3, 15, 0, tzinfo=UTC)
    await db.sessions.insert_many(
        [
            {
                "academy_id": "academy-b",
                "session_id": "sess-doomed",
                "title": "Doomed Dated",
                "location": "Court 1",
                "coach_id": "coach-1",
                "capacity": 8,
                "status": "scheduled",
                "start_at": start,
                "end_at": start + timedelta(hours=1),
            },
            {
                "academy_id": "academy-b",
                "session_id": "tpl-doomed",
                "name": "Doomed Recurring",
                "location": "Court 2",
                "coach_id": "coach-2",
                "max_students": 10,
                "status": "active",
                "days_of_week": ["Mon"],
                "start_time": "09:15",
                "end_time": "10:15",
                "timezone": "America/Chicago",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
            },
        ]
    )

    app = _mongo_admin_app(db)
    with TestClient(app) as client:
        before = client.get("/api/v2/admin/sessions?window=upcoming")
        assert before.status_code == 200, before.text
        before_ids = [row["session_id"] for row in before.json()["sessions"]]
        assert "sess-doomed" in before_ids
        assert "tpl-doomed" in before_ids

        assert client.delete("/api/v2/admin/sessions/sess-doomed").status_code == 204
        assert client.delete("/api/v2/admin/sessions/tpl-doomed").status_code == 204

        after = client.get("/api/v2/admin/sessions?window=upcoming")

    assert after.status_code == 200, after.text
    after_ids = [row["session_id"] for row in after.json()["sessions"]]
    assert "sess-doomed" not in after_ids
    assert "tpl-doomed" not in after_ids

    # Soft delete: the docs are still in Mongo, just flagged.
    stored = await db.sessions.find_one({"academy_id": "academy-b", "session_id": "sess-doomed"})
    assert stored is not None
    assert stored["status"] == "cancelled"


# NOTE: there is deliberately no `admin_client` (fake-composition) mirror of the
# three tests above. The fake `list_admin_sessions` in conftest is a hand-written
# double, so a test through it would only assert that the double does what the
# double was written to do — it passed with both production fixes reverted.
# The mongomock tests above exercise the real Mongo filters instead.


# --- issue #467: cancelling a session must cancel its future occurrences ------
#
# `sessions.status` is not what the downstream readers look at. Coach payroll,
# the admin expected-payroll report and the coach day view all key off the
# OCCURRENCE's own status, so a cancelled session whose `session_occurrences`
# rows stay "scheduled" keeps showing up on coach screens and keeps accruing
# expected pay — while the admin listing fix hides it from the admin.


_CANCEL_TEMPLATE = {
    "academy_id": "academy-b",
    "session_id": "tpl-cancel",
    "name": "Doomed Recurring",
    "location": "Court 1",
    "coach_id": "coach-1",
    "max_students": 10,
    "amount_cents": 12000,
    "status": "active",
    "days_of_week": ["Mon", "Wed"],
    "start_time": "09:15",
    "end_time": "10:15",
    "timezone": "America/Chicago",
    "start_date": "2026-05-01",
    "end_date": "2026-07-31",
}

# 09:15 America/Chicago == 14:15Z during CDT.
_OCC_PAST_START = datetime(2026, 5, 27, 14, 15, tzinfo=UTC)  # before the frozen now
_OCC_FUTURE_CLEAN_START = datetime(2026, 6, 15, 14, 15, tzinfo=UTC)
_OCC_FUTURE_ATTENDED_START = datetime(2026, 6, 17, 14, 15, tzinfo=UTC)
# Past the 60-day maintenance window (frozen now + 60d == 2026-07-31). Normal
# occurrence maintenance never looks this far ahead; a cancel has to.
_OCC_BEYOND_WINDOW_START = datetime(2026, 9, 2, 14, 15, tzinfo=UTC)


def _occurrence(occurrence_id: str, start_at: datetime) -> dict[str, object]:
    return {
        "occurrence_id": occurrence_id,
        "academy_id": "academy-b",
        "session_id": "tpl-cancel",
        "template_session_id": "tpl-cancel",
        "start_at": start_at,
        "end_at": start_at + timedelta(hours=1),
        "status": "scheduled",
        "scheduled_coach_id": "coach-1",
        "actual_coach_id": None,
        "substitute_coach_id": None,
        "is_billable": True,
        "is_payable": True,
    }


async def _seed_cancel_fixture(db) -> None:
    await db.sessions.insert_one(dict(_CANCEL_TEMPLATE))
    await db.session_occurrences.insert_many(
        [
            _occurrence("occ-past", _OCC_PAST_START),
            _occurrence("occ-future-clean", _OCC_FUTURE_CLEAN_START),
            _occurrence("occ-future-attended", _OCC_FUTURE_ATTENDED_START),
            _occurrence("occ-beyond-window", _OCC_BEYOND_WINDOW_START),
        ]
    )
    # The past class really happened: student attendance was taken.
    await db.attendance.insert_one(
        {
            "academy_id": "academy-b",
            "occurrence_id": "occ-past",
            "student_id": "student-1",
            "status": "present",
        }
    )
    # A future occurrence that has already been acted on (coach attendance
    # marked ahead of time) is NOT clean and must survive the cancel untouched.
    await db.coach_attendance.insert_one(
        {
            "academy_id": "academy-b",
            "occurrence_id": "occ-future-attended",
            "coach_id": "coach-1",
            "status": "present",
            "role": "lead",
        }
    )


@pytest.mark.asyncio
async def test_cancel_session_cancels_future_occurrences_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for #467: the occurrences must follow the parent session."""
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-cancel-occurrences"]
    await _seed_cancel_fixture(db)

    app = _mongo_admin_app(db)
    with TestClient(app) as client:
        assert client.delete("/api/v2/admin/sessions/tpl-cancel").status_code == 204

    cancelled = await db.session_occurrences.find_one({"occurrence_id": "occ-future-clean"})
    assert cancelled is not None
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancellation_reason"] == "session_cancelled"

    # Past attendance is history — the class happened and the coach gets paid.
    past = await db.session_occurrences.find_one({"occurrence_id": "occ-past"})
    assert past is not None
    assert past["status"] == "scheduled"
    assert "cancellation_reason" not in past

    # A future occurrence somebody already acted on is left alone too.
    acted_on = await db.session_occurrences.find_one({"occurrence_id": "occ-future-attended"})
    assert acted_on is not None
    assert acted_on["status"] == "scheduled"

    # A clean future occurrence materialised BEYOND the 60-day maintenance
    # window is still reached: a cancel drops the query's upper bound, so the
    # far end of a long series cannot stay live after the session is cancelled.
    beyond = await db.session_occurrences.find_one({"occurrence_id": "occ-beyond-window"})
    assert beyond is not None
    assert beyond["status"] == "cancelled"
    assert beyond["cancellation_reason"] == "session_cancelled"

    # Soft cancel: nothing was deleted.
    assert await db.session_occurrences.count_documents({"academy_id": "academy-b"}) == 4


@pytest.mark.asyncio
async def test_cancelled_session_occurrences_leave_payroll_and_coach_day_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#467 downstream: the readers that key off occurrence status agree."""
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-cancel-downstream"]
    await _seed_cancel_fixture(db)

    occurrences_repo = MongoSessionOccurrenceRepository(db)
    payable_query = MongoPayableOccurrenceQuery(db)
    period_start = datetime(2026, 6, 1, tzinfo=UTC)
    period_end = datetime(2026, 7, 1, tzinfo=UTC)

    with tenant_scope("academy-b"):
        before_day_view = await occurrences_repo.list_for_coach_on_date(
            coach_id="coach-1",
            on_date=date(2026, 6, 15),
        )
    assert [o.occurrence_id for o in before_day_view] == ["occ-future-clean"]

    before_payable = await payable_query.list_in_period("academy-b", period_start, period_end)
    assert "occ-future-clean" in {o.occurrence_id for o in before_payable}

    app = _mongo_admin_app(db)
    with TestClient(app) as client:
        assert client.delete("/api/v2/admin/sessions/tpl-cancel").status_code == 204

    # Coach day view no longer offers the cancelled class.
    with tenant_scope("academy-b"):
        after_day_view = await occurrences_repo.list_for_coach_on_date(
            coach_id="coach-1",
            on_date=date(2026, 6, 15),
        )
    assert after_day_view == []

    # Payroll: the occurrence is reported as cancelled, so ComputePayout's
    # `status == "completed"` eligibility rule can never pay for it.
    after_payable = {
        o.occurrence_id: o
        for o in await payable_query.list_in_period("academy-b", period_start, period_end)
    }
    assert after_payable["occ-future-clean"].status == "cancelled"
    # The already-acted-on occurrence keeps its payable status.
    assert after_payable["occ-future-attended"].status != "cancelled"


# --- issue #610: add-to-roster error surfacing -----------------------------


def test_add_to_roster_duplicate_returns_409_with_student_name(admin_client) -> None:
    """A repeat add is a 409 the admin can act on, not a 500 and not a dupe row."""
    payload = {
        "session_id": "sess-1",
        "student_id": "st-1",
        "parent_id": "p-1",
        "full_name": "Alice",
    }
    first = admin_client.post("/api/v2/admin/enrollments", json=payload)
    assert first.status_code == 200, first.text
    seats_after_first = dict(admin_client.seed["sessions"].reserved)

    second = admin_client.post("/api/v2/admin/enrollments", json=payload)

    assert second.status_code == 409, second.text
    body = second.json()
    # The global DomainError handler owns this shape — the route's except arm
    # must not have converted it into a 500.
    assert body["error"]["code"] == "Enrollment.StudentAlreadyOnRoster"
    assert "Alice" in body["error"]["message"]
    # No second enrollment row, and no second seat burned.
    assert len(admin_client.seed["enrollments"].rows) == 1
    assert dict(admin_client.seed["sessions"].reserved) == seats_after_first


def test_add_to_roster_unexpected_error_returns_actionable_500(admin_client, caplog) -> None:
    """A genuinely unexpected failure is logged with context and named clearly."""

    class _Boom:
        async def execute(self, cmd):
            raise RuntimeError("motor exploded")

    admin_client.use_cases.edit_roster_add = _Boom()

    with caplog.at_level("ERROR"):
        r = admin_client.post(
            "/api/v2/admin/enrollments",
            json={
                "session_id": "sess-1",
                "student_id": "st-1",
                "parent_id": "p-1",
                "full_name": "Alice",
            },
        )

    assert r.status_code == 500
    detail = r.json()["detail"]
    assert detail != "Internal Server Error"
    assert "sess-1" in detail and "st-1" in detail
    records = [rec for rec in caplog.records if rec.message == "admin.roster_add_failed"]
    assert records, "expected the stable admin.roster_add_failed marker"
    assert records[0].session_id == "sess-1"  # type: ignore[attr-defined]
    assert records[0].student_id == "st-1"  # type: ignore[attr-defined]


def test_add_to_roster_full_session_reports_the_real_numbers(admin_client) -> None:
    sessions = admin_client.seed["sessions"]
    session = sessions.sessions["sess-1"]
    sessions.sessions["sess-1"] = session.model_copy(update={"capacity": 1})

    first = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    assert first.status_code == 200, first.text

    second = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-2",
            "parent_id": "p-1",
            "full_name": "Bob",
        },
    )

    assert second.status_code == 409, second.text
    error = second.json()["error"]
    assert error["code"] == "Enrollment.CapacityExceeded"
    assert error["details"]["capacity"] == 1
    assert error["details"]["active_enrollments"] == 1
    # The seat counter did not move on the refused add.
    assert sessions.reserved["sess-1"] == 1


# --- #613 communication pack ------------------------------------------------

_PACK_PAYLOAD = {
    "whatsapp_group_link": "https://chat.whatsapp.com/AbCd1234",
    "venue_address": "12 Court Lane\nAustin, TX 78701",
    "parking_notes": "Free lot behind the building.",
    "what_to_bring": "Racquet, water bottle, indoor shoes.",
    "arrival_minutes_before": 15,
    "coach_contact_policy": "Message the coach through the app, not on WhatsApp.",
    "absence_policy": "Tell us 24 hours ahead to book a make-up.",
}


async def _create_pack_session(db, client, **overrides) -> dict:
    body = {
        "coach_id": "coach-pack",
        "title": "Pack Session",
        "location": "Court 1",
        "days_of_week": ["Wed"],
        "start_time": "18:00",
        "end_time": "18:45",
        "timezone": "America/Chicago",
        "capacity": 15,
        **overrides,
    }
    response = client.post("/api/v2/admin/sessions", json=body)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_communication_pack_survives_the_round_trip_to_the_get_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression guard for the #609 class of bug.

    POST/PATCH render the view from the domain aggregate while GET/LIST render
    it from the hand-written projection in composition/admin.py, so a field
    dropped from the projection looks perfectly correct on save and comes back
    blank on reload. Asserting on the GET route is the whole point.
    """
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-session-pack-round-trip"]

    with TestClient(_mongo_admin_app(db)) as client:
        created = await _create_pack_session(db, client, amount_cents=6000, **_PACK_PAYLOAD)
        session_id = created["session_id"]

        # 1. The create response (aggregate-rendered) carries the pack.
        for field, value in _PACK_PAYLOAD.items():
            assert created[field] == value, field

        # 2. The detail route (projection-rendered) carries the same values.
        detail = client.get(f"/api/v2/admin/sessions/{session_id}")
        assert detail.status_code == 200, detail.text
        for field, value in _PACK_PAYLOAD.items():
            assert detail.json()[field] == value, f"{field} dropped by the admin projection"
        # #609 drive-by, verified through the route that was actually broken.
        assert detail.json()["amount_cents"] == 6000

        # 3. An edit persists and reloads.
        edited = client.patch(
            f"/api/v2/admin/sessions/{session_id}",
            json={"parking_notes": "Street parking only.", "arrival_minutes_before": 20},
        )
        assert edited.status_code == 200, edited.text
        reloaded = client.get(f"/api/v2/admin/sessions/{session_id}").json()
        assert reloaded["parking_notes"] == "Street parking only."
        assert reloaded["arrival_minutes_before"] == 20
        # Untouched fields are not collateral damage of a partial PATCH.
        assert reloaded["whatsapp_group_link"] == _PACK_PAYLOAD["whatsapp_group_link"]

        # 4. An explicit null clears — an admin who can set a link can remove it.
        cleared = client.patch(
            f"/api/v2/admin/sessions/{session_id}",
            json={"whatsapp_group_link": None},
        )
        assert cleared.status_code == 200, cleared.text
        assert (
            client.get(f"/api/v2/admin/sessions/{session_id}").json()["whatsapp_group_link"] is None
        )


@pytest.mark.asyncio
async def test_communication_pack_survives_the_list_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The list route synthesizes recurring rows from template docs; the pack
    has to ride along through that expansion and the series de-dupe."""
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-session-pack-list"]

    with TestClient(_mongo_admin_app(db)) as client:
        created = await _create_pack_session(db, client, **_PACK_PAYLOAD)
        listing = client.get("/api/v2/admin/sessions?window=upcoming")
        assert listing.status_code == 200, listing.text

    rows = [s for s in listing.json()["sessions"] if s["session_id"] == created["session_id"]]
    assert rows, "created session missing from the upcoming listing"
    for field, value in _PACK_PAYLOAD.items():
        assert rows[0][field] == value, f"{field} dropped between the template doc and the list row"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_link",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "//evil.host/group",
        "chat.whatsapp.com/AbCd1234",
        "https://\nchat.whatsapp.com/AbCd1234",
    ],
)
async def test_communication_pack_rejects_non_http_group_links(
    monkeypatch: pytest.MonkeyPatch, bad_link: str
) -> None:
    """The link is rendered as an email href. Escaping stops attribute
    breakout; only this scheme allowlist stops `javascript:`."""
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-session-pack-bad-link"]

    with TestClient(_mongo_admin_app(db)) as client:
        created = await _create_pack_session(db, client)
        response = client.patch(
            f"/api/v2/admin/sessions/{created['session_id']}",
            json={"whatsapp_group_link": bad_link},
        )

    assert response.status_code == 422, response.text
    stored = await db.sessions.find_one(
        {"academy_id": "academy-b", "session_id": created["session_id"]}
    )
    assert stored is not None
    assert stored.get("whatsapp_group_link") is None


@pytest.mark.asyncio
async def test_communication_pack_blank_group_link_clears_rather_than_storing_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-session-pack-blank-link"]

    with TestClient(_mongo_admin_app(db)) as client:
        created = await _create_pack_session(
            db, client, whatsapp_group_link="https://chat.whatsapp.com/AbCd1234"
        )
        response = client.patch(
            f"/api/v2/admin/sessions/{created['session_id']}",
            json={"whatsapp_group_link": "   "},
        )
        assert response.status_code == 200, response.text
        assert (
            client.get(f"/api/v2/admin/sessions/{created['session_id']}").json()[
                "whatsapp_group_link"
            ]
            is None
        )


@pytest.mark.asyncio
async def test_admin_session_projection_emits_every_view_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structural guard against the #609 class of bug recurring.

    `_build_admin_session_rows` is a hand-written dict and `AdminSessionView`
    defaults every optional field to None, so a field left out of the
    projection is invisible: no exception, no validation error, just a value
    that silently reverts on reload. This asserts the two stay in step for
    EVERY field, not only today's.
    """
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-session-projection-fields"]

    app = _mongo_admin_app(db)
    with TestClient(app) as client:
        created = await _create_pack_session(db, client, amount_cents=6000, **_PACK_PAYLOAD)

    with tenant_scope("academy-b"):
        row = await app.state.admin.get_admin_session(created["session_id"])

    assert row is not None
    missing = set(AdminSessionView.model_fields) - set(row)
    assert not missing, f"admin session projection drops: {sorted(missing)}"
