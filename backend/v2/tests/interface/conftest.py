"""Interface-test fixtures.

Builds a FastAPI app with the coach router and an in-memory test
composition so we never spin up Mongo. Auth is injected via FastAPI's
dependency override.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterator, Literal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.coaching.application.use_cases.mark_attendance import MarkAttendance
from backend.v2.contexts.enrollment.application.use_cases.get_session_roster import (
    GetSessionRoster,
)
from backend.v2.contexts.enrollment.application.use_cases.list_coach_sessions_for_date import (
    ListCoachSessionsForDate,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, RosterEntry, Session, Student
from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


# --- in-memory fakes ---


class FakeSessionQuery:
    def __init__(self, sessions: list[Session]) -> None:
        self._sessions = sessions

    async def for_coach_on_date(self, coach_id: str, on_date: date) -> list[Session]:
        return [
            s for s in self._sessions if s.coach_id == coach_id and s.start_at.date() == on_date
        ]

    async def get(self, session_id: str) -> Session | None:
        for s in self._sessions:
            if s.session_id == session_id:
                return s
        return None


class FakeEnrollmentQuery:
    def __init__(self, enrollments: list[Enrollment]) -> None:
        self._enrollments = enrollments

    async def active_for_session(self, session_id: str) -> list[Enrollment]:
        return [
            e for e in self._enrollments if e.session_id == session_id and e.status == "active"
        ]

    async def is_active(self, session_id: str, student_id: str) -> bool:
        return any(
            e.session_id == session_id and e.student_id == student_id and e.status == "active"
            for e in self._enrollments
        )


class FakeStudentQuery:
    def __init__(self, students: list[Student]) -> None:
        self._by_id = {s.student_id: s for s in students}

    async def by_ids(self, student_ids: list[str]) -> list[Student]:
        return [self._by_id[s] for s in student_ids if s in self._by_id]


class FakeAttendanceRepo:
    def __init__(self) -> None:
        self.saved: list = []

    async def save(self, attendance) -> None:
        self.saved.append(attendance)

    async def find_existing(self, session_id, student_id):
        for a in self.saved:
            if a.session_id == session_id and a.student_id == student_id:
                return a
        return None

    async def find_by_attendance_id(self, attendance_id):
        for a in self.saved:
            if a.attendance_id == attendance_id:
                return a
        return None


class FakeOutbox:
    def __init__(self) -> None:
        self.appended: list = []

    async def append(self, event, *, session=None) -> None:
        self.appended.append(event)

    async def pull_unprocessed(self, limit: int = 100):
        return []

    async def mark_processed(self, event_id: str) -> None:
        pass


class FakeIdempotencyStore:
    def __init__(self) -> None:
        self.data: dict = {}

    async def get(self, key: str):
        return self.data.get(key)

    async def put(self, key: str, value) -> None:
        self.data[key] = value


# --- seed data ---


def _now() -> datetime:
    return datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc)


@pytest.fixture()
def seed():
    sessions = [
        Session(
            session_id="s-today-1",
            academy_id="test-academy",
            coach_id="coach-1",
            title="Junior A",
            location="Court 1",
            start_at=datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 5, 16, 10, 30, tzinfo=timezone.utc),
            capacity=8,
            status="scheduled",
        ),
        Session(
            session_id="s-today-2",
            academy_id="test-academy",
            coach_id="coach-1",
            title="Adult B",
            location="Court 2",
            start_at=datetime(2026, 5, 16, 18, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 5, 16, 19, 30, tzinfo=timezone.utc),
            capacity=10,
            status="scheduled",
        ),
        Session(
            session_id="s-other-coach",
            academy_id="test-academy",
            coach_id="coach-2",
            title="Not mine",
            location="Court 3",
            start_at=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 5, 16, 13, 0, tzinfo=timezone.utc),
            capacity=4,
            status="scheduled",
        ),
    ]
    enrollments = [
        Enrollment(
            enrollment_id="e1",
            academy_id="test-academy",
            session_id="s-today-1",
            student_id="st1",
            status="active",
        ),
        Enrollment(
            enrollment_id="e2",
            academy_id="test-academy",
            session_id="s-today-1",
            student_id="st2",
            status="active",
        ),
    ]
    students = [
        Student(student_id="st1", academy_id="test-academy", parent_id="p1", full_name="Alice"),
        Student(student_id="st2", academy_id="test-academy", parent_id="p2", full_name="Bob"),
    ]
    return {
        "sessions": sessions,
        "enrollments": enrollments,
        "students": students,
    }


def _coach_claims() -> AuthClaims:
    return AuthClaims(
        user_id="coach-1",
        email="coach1@example.com",
        academy_id="test-academy",
        roles=("coach",),
    )


def _parent_claims() -> AuthClaims:
    return AuthClaims(
        user_id="p1",
        email="parent@example.com",
        academy_id="test-academy",
        roles=("parent",),
    )


def _admin_claims() -> AuthClaims:
    return AuthClaims(
        user_id="adm",
        email="admin@example.com",
        academy_id="test-academy",
        roles=("admin",),
    )


def _build_use_cases(seed_data) -> CoachUseCases:
    sessions = FakeSessionQuery(seed_data["sessions"])
    enrollments = FakeEnrollmentQuery(seed_data["enrollments"])
    students = FakeStudentQuery(seed_data["students"])

    # Adapters wiring coach lookups to enrollment queries.
    class _SL:
        async def is_coach_assigned(self, coach_id, sid, on_date):
            s = await sessions.get(sid)
            return s is not None and s.coach_id == coach_id and s.start_at.date() == on_date

        async def is_cancelled(self, sid):
            s = await sessions.get(sid)
            return s is not None and s.status == "cancelled"

        async def session_date(self, sid):
            s = await sessions.get(sid)
            return s.start_at.date() if s else None

    class _EL:
        async def is_active(self, sid, student_id):
            return await enrollments.is_active(sid, student_id)

    return CoachUseCases(
        list_today=ListCoachSessionsForDate(sessions=sessions),
        get_roster=GetSessionRoster(enrollments=enrollments, students=students),
        mark_attendance=MarkAttendance(
            attendance_repo=FakeAttendanceRepo(),
            session_lookup=_SL(),
            enrollment_lookup=_EL(),
            outbox=FakeOutbox(),
            idempotency_store=FakeIdempotencyStore(),
            academy_id="test-academy",
            clock=_now,
        ),
    )


def _make_app(claims: AuthClaims, use_cases: CoachUseCases) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(coach_router, prefix="/api/v2")

    async def _override_claims():
        return claims

    def _override_use_cases():
        return use_cases

    app.dependency_overrides[get_auth_claims] = _override_claims
    app.dependency_overrides[get_coach_use_cases] = _override_use_cases
    return app


@pytest.fixture()
def coach_client(seed) -> Iterator[TestClient]:
    use_cases = _build_use_cases(seed)
    app = _make_app(_coach_claims(), use_cases)
    with TestClient(app) as client:
        client.coach_use_cases = use_cases  # type: ignore[attr-defined]
        yield client


@pytest.fixture()
def parent_client(seed) -> Iterator[TestClient]:
    """Same routes mounted, but token represents a parent — wrong persona."""
    use_cases = _build_use_cases(seed)
    app = _make_app(_parent_claims(), use_cases)
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def admin_client(seed) -> Iterator[TestClient]:
    use_cases = _build_use_cases(seed)
    app = _make_app(_admin_claims(), use_cases)
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def anon_client(seed) -> Iterator[TestClient]:
    """No auth claims; the dependency raises 401."""
    use_cases = _build_use_cases(seed)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(coach_router, prefix="/api/v2")
    app.dependency_overrides[get_coach_use_cases] = lambda: use_cases
    # Do NOT override get_auth_claims; the default raises 401.
    with TestClient(app) as client:
        yield client
