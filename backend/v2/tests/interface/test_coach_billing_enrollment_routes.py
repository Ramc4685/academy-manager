"""Interface tests for coach billing-enrollment routes.

GET  /api/v2/coach/billing-enrollments?session_id=<id>
GET  /api/v2/coach/billing-enrollments/{enrollment_id}/move/preview
POST /api/v2/coach/billing-enrollments/{enrollment_id}/move

Tests:
- list returns enrollments for students in an assigned session
- move preview returns credit/charge/net cents (no side effects)
- move applies the move and changes session_type_id on the enrollment
- unauthenticated request returns 401
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.billing.application.use_cases.session_type_ops import (
    ListSessionTypes,
    ListStudentBillingEnrollments,
    MoveStudentSessionType,
    PreviewStudentSessionTypeMove,
)
from backend.v2.contexts.billing.domain.session_type import SessionType, StudentBillingEnrollment
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

_NOW = datetime(2026, 5, 16, 9, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------


@dataclass
class _FakeBillingEnrollmentRepo:
    rows: dict[str, StudentBillingEnrollment] = field(default_factory=dict)

    async def save(self, enrollment: StudentBillingEnrollment) -> None:
        self.rows[enrollment.enrollment_id] = enrollment

    async def get(self, enrollment_id: str) -> StudentBillingEnrollment | None:
        return self.rows.get(enrollment_id)

    async def list_for_student(self, student_id: str) -> list[StudentBillingEnrollment]:
        return [e for e in self.rows.values() if e.student_id == student_id]

    async def list_for_parent(self, parent_id: str) -> list[StudentBillingEnrollment]:
        return [e for e in self.rows.values() if e.parent_id == parent_id]

    async def get_by_stripe_subscription(
        self, stripe_subscription_id: str
    ) -> StudentBillingEnrollment | None:
        return next(
            (e for e in self.rows.values() if e.stripe_subscription_id == stripe_subscription_id),
            None,
        )


@dataclass
class _FakeSessionEnrollmentRepo:
    """Fake enrollment repo for the session-ownership guard (active_for_student)."""

    # student_id -> list of (session_id, status)
    entries: dict[str, list[str]] = field(default_factory=dict)

    async def active_for_student(self, student_id: str) -> list[_SessionEnrollmentStub]:
        return [_SessionEnrollmentStub(sid) for sid in self.entries.get(student_id, [])]


class _SessionEnrollmentStub:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id


@dataclass
class _FakeSessionTypeRepo:
    rows: dict[str, SessionType] = field(default_factory=dict)

    async def save(self, st: SessionType) -> None:
        self.rows[st.session_type_id] = st

    async def get(self, session_type_id: str) -> SessionType | None:
        return self.rows.get(session_type_id)

    async def list_active(self) -> list[SessionType]:
        return [st for st in self.rows.values() if st.is_active]

    async def soft_delete(self, session_type_id: str) -> None:
        st = self.rows[session_type_id]
        self.rows[session_type_id] = st.model_copy(update={"is_active": False})


class _FakeAssignedSessions:
    """Minimal assigned-sessions lookup used by list_billing_enrollments guard."""

    def __init__(self, assigned: dict[str, set[str]]) -> None:
        # assigned: coach_id -> set of session_ids
        self._assigned = assigned

    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool:
        return session_id in self._assigned.get(coach_id, set())


class _FakeRosterQuery:
    """Minimal roster query that returns enrollment stubs keyed by session."""

    def __init__(self, roster: dict[str, list[str]]) -> None:
        # roster: session_id -> list of student_ids
        self._roster = roster

    async def execute(self, session_id: str):
        """Returns objects with .student_id attribute."""
        student_ids = self._roster.get(session_id, [])
        return [_RosterEntry(sid) for sid in student_ids]


class _RosterEntry:
    def __init__(self, student_id: str) -> None:
        self.student_id = student_id


class _FakeEventSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def record_session_type_changed(self, **kwargs) -> None:
        self.events.append(kwargs)


# ---------------------------------------------------------------------------
# Seed data factories
# ---------------------------------------------------------------------------


async def _async_none(*_args, **_kwargs):
    return None


def _make_session_type(st_id: str, name: str, price_cents: int) -> SessionType:
    return SessionType(
        session_type_id=st_id,
        academy_id="acad",
        name=name,
        price_cents=price_cents,
        billing_period="monthly",
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_billing_enrollment(
    enrollment_id: str,
    student_id: str,
    session_type_id: str,
) -> StudentBillingEnrollment:
    return StudentBillingEnrollment(
        enrollment_id=enrollment_id,
        academy_id="acad",
        student_id=student_id,
        parent_id="parent-1",
        session_type_id=session_type_id,
        billing_start_date=_NOW,
        status="active",
        enrolled_at=_NOW,
        updated_at=_NOW,
    )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

_COACH_SESSION_ID = "sess-1"
_STUDENT_ID = "st-1"
_ENROLLMENT_ID = "be-1"
_ST_FROM_ID = "st-beginner"
_ST_TO_ID = "st-advanced"


def _build_use_cases(
    billing_enrollments: _FakeBillingEnrollmentRepo,
    session_types: _FakeSessionTypeRepo,
    event_sink: _FakeEventSink,
    stripe: FakeStripeGateway,
    session_enrollment_repo: _FakeSessionEnrollmentRepo | None = None,
) -> CoachUseCases:
    assigned = _FakeAssignedSessions({"coach-1": {_COACH_SESSION_ID}})
    roster = _FakeRosterQuery({_COACH_SESSION_ID: [_STUDENT_ID]})

    if session_enrollment_repo is None:
        # Default: student is enrolled in the coach's session
        session_enrollment_repo = _FakeSessionEnrollmentRepo(
            entries={_STUDENT_ID: [_COACH_SESSION_ID]}
        )

    list_billing_uc = ListStudentBillingEnrollments(enrollments=billing_enrollments)
    list_session_types_uc = ListSessionTypes(session_types=session_types)
    preview_uc = PreviewStudentSessionTypeMove(
        enrollments=billing_enrollments,
        session_types=session_types,
    )
    move_uc = MoveStudentSessionType(
        enrollments=billing_enrollments,
        session_types=session_types,
        stripe=stripe,
        event_sink=event_sink,
        clock=lambda: _NOW,
    )

    return CoachUseCases(
        list_today=AsyncMock(),  # type: ignore[arg-type]
        get_roster=roster,  # type: ignore[arg-type]
        mark_attendance=AsyncMock(),  # type: ignore[arg-type]
        bulk_mark_attendance=AsyncMock(),  # type: ignore[arg-type]
        get_dashboard_metrics=AsyncMock(),  # type: ignore[arg-type]
        create_lesson_plan=AsyncMock(),  # type: ignore[arg-type]
        list_lesson_plans=AsyncMock(),  # type: ignore[arg-type]
        create_progress_note=AsyncMock(),  # type: ignore[arg-type]
        list_progress_notes=AsyncMock(),  # type: ignore[arg-type]
        assigned_sessions=assigned,  # type: ignore[arg-type]
        add_student_to_roster=AsyncMock(),  # type: ignore[arg-type]
        remove_student_from_roster=AsyncMock(),  # type: ignore[arg-type]
        create_feedback=AsyncMock(),  # type: ignore[arg-type]
        list_feedback=AsyncMock(),  # type: ignore[arg-type]
        list_billing_enrollments=list_billing_uc,
        preview_student_session_type_move=preview_uc,
        move_student_session_type=move_uc,
        list_session_types=list_session_types_uc,
        get_billing_enrollment=billing_enrollments.get,
        get_active_session_enrollments_for_student=session_enrollment_repo.active_for_student,
        list_all_sessions=_async_none,
        get_profile=_async_none,
        update_profile=_async_none,
    )


def _coach_claims() -> AuthClaims:
    return AuthClaims(
        user_id="coach-1",
        email="coach@example.com",
        academy_id="acad",
        roles=("coach",),
    )


def _non_coach_claims(role: str) -> AuthClaims:
    return AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


def _build_app(claims: AuthClaims, use_cases: CoachUseCases) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(coach_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.dependency_overrides[get_coach_use_cases] = lambda: use_cases
    return app


def _build_anon_app(use_cases: CoachUseCases) -> FastAPI:
    """No auth override → 401 on every request."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(coach_router, prefix="/api/v2")
    app.dependency_overrides[get_coach_use_cases] = lambda: use_cases
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def setup():
    billing_enrollments = _FakeBillingEnrollmentRepo()
    session_types = _FakeSessionTypeRepo()
    event_sink = _FakeEventSink()
    stripe = FakeStripeGateway()

    # Seed session types
    session_types.rows[_ST_FROM_ID] = _make_session_type(_ST_FROM_ID, "Beginner", 5000)
    session_types.rows[_ST_TO_ID] = _make_session_type(_ST_TO_ID, "Advanced", 8000)

    # Seed billing enrollment
    billing_enrollments.rows[_ENROLLMENT_ID] = _make_billing_enrollment(
        _ENROLLMENT_ID, _STUDENT_ID, _ST_FROM_ID
    )

    use_cases = _build_use_cases(billing_enrollments, session_types, event_sink, stripe)
    return {
        "billing_enrollments": billing_enrollments,
        "session_types": session_types,
        "event_sink": event_sink,
        "stripe": stripe,
        "use_cases": use_cases,
    }


@pytest.fixture()
def coach_client(setup) -> Iterator[TestClient]:
    app = _build_app(_coach_claims(), setup["use_cases"])
    with TestClient(app, raise_server_exceptions=True) as c:
        c.setup = setup  # type: ignore[attr-defined]
        yield c


@pytest.fixture()
def anon_client(setup) -> Iterator[TestClient]:
    app = _build_anon_app(setup["use_cases"])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_list_billing_enrollments_returns_enrollments(coach_client):
    resp = coach_client.get(f"/api/v2/coach/billing-enrollments?session_id={_COACH_SESSION_ID}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    entry = body[0]
    assert entry["enrollment_id"] == _ENROLLMENT_ID
    assert entry["student_id"] == _STUDENT_ID
    assert entry["session_type_id"] == _ST_FROM_ID
    assert entry["session_type_name"] == "Beginner"
    assert entry["status"] == "active"


def test_list_billing_enrollments_without_session_id_returns_422(coach_client):
    resp = coach_client.get("/api/v2/coach/billing-enrollments")
    assert resp.status_code == 422, resp.text


def test_list_billing_enrollments_unassigned_session_returns_403(coach_client):
    resp = coach_client.get("/api/v2/coach/billing-enrollments?session_id=other-sess")
    assert resp.status_code == 403, resp.text


def test_move_preview_returns_proration(coach_client):
    resp = coach_client.get(
        f"/api/v2/coach/billing-enrollments/{_ENROLLMENT_ID}/move/preview"
        f"?to_session_type_id={_ST_TO_ID}"
        f"&move_date=2026-05-16T09:00:00Z"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "credit_cents" in body
    assert "charge_cents" in body
    assert "net_cents" in body
    assert body["from_session_type_id"] == _ST_FROM_ID
    assert body["to_session_type_id"] == _ST_TO_ID
    # Proration sanity: net = charge - credit
    assert body["net_cents"] == body["charge_cents"] - body["credit_cents"]


def test_move_preview_missing_enrollment_returns_404(coach_client):
    resp = coach_client.get(
        f"/api/v2/coach/billing-enrollments/nonexistent/move/preview"
        f"?to_session_type_id={_ST_TO_ID}"
    )
    assert resp.status_code == 404, resp.text


def test_move_preview_missing_to_session_type_returns_404(coach_client):
    resp = coach_client.get(
        f"/api/v2/coach/billing-enrollments/{_ENROLLMENT_ID}/move/preview"
        f"?to_session_type_id=nonexistent-st"
    )
    assert resp.status_code == 404, resp.text


def test_move_applies_move(coach_client):
    resp = coach_client.post(
        f"/api/v2/coach/billing-enrollments/{_ENROLLMENT_ID}/move",
        json={
            "to_session_type_id": _ST_TO_ID,
            "move_date": "2026-05-16T09:00:00Z",
            "reason": "student requested upgrade",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "enrollment" in body
    assert "proration" in body
    assert body["enrollment"]["session_type_id"] == _ST_TO_ID
    assert body["enrollment"]["session_type_name"] == "Advanced"
    assert body["proration"]["to_session_type_id"] == _ST_TO_ID

    # Verify the enrollment was actually persisted with new session_type_id
    updated = coach_client.setup["billing_enrollments"].rows[_ENROLLMENT_ID]
    assert updated.session_type_id == _ST_TO_ID


def test_move_fires_event(coach_client):
    coach_client.post(
        f"/api/v2/coach/billing-enrollments/{_ENROLLMENT_ID}/move",
        json={"to_session_type_id": _ST_TO_ID},
    )
    events = coach_client.setup["event_sink"].events
    assert len(events) == 1
    ev = events[0]
    assert ev["from_session_type_id"] == _ST_FROM_ID
    assert ev["to_session_type_id"] == _ST_TO_ID
    assert ev["actor_id"] == "coach-1"


def test_move_missing_enrollment_returns_404(coach_client):
    resp = coach_client.post(
        "/api/v2/coach/billing-enrollments/nonexistent/move",
        json={"to_session_type_id": _ST_TO_ID},
    )
    assert resp.status_code == 404, resp.text


def test_coach_cannot_access_without_auth(anon_client):
    resp = anon_client.get(f"/api/v2/coach/billing-enrollments?session_id={_COACH_SESSION_ID}")
    assert resp.status_code == 401, resp.text


def test_non_coach_persona_gets_404(setup):
    """Parent token on coach routes should return 404 (persona mismatch)."""
    app = _build_app(_non_coach_claims("parent"), setup["use_cases"])
    with TestClient(app) as c:
        resp = c.get(f"/api/v2/coach/billing-enrollments?session_id={_COACH_SESSION_ID}")
    assert resp.status_code == 404, resp.text


def test_move_preview_returns_403_when_student_not_in_coach_session(setup):
    """A coach cannot preview a move for a student enrolled in another coach's session."""
    # Rebuild use cases with a session enrollment repo that maps the student to a different session.
    unowned_session_enrollment_repo = _FakeSessionEnrollmentRepo(
        entries={_STUDENT_ID: ["other-sess-99"]}
    )
    use_cases = _build_use_cases(
        setup["billing_enrollments"],
        setup["session_types"],
        setup["event_sink"],
        setup["stripe"],
        session_enrollment_repo=unowned_session_enrollment_repo,
    )
    app = _build_app(_coach_claims(), use_cases)
    with TestClient(app, raise_server_exceptions=True) as c:
        resp = c.get(
            f"/api/v2/coach/billing-enrollments/{_ENROLLMENT_ID}/move/preview"
            f"?to_session_type_id={_ST_TO_ID}"
        )
    assert resp.status_code == 403, resp.text


def test_move_returns_403_when_student_not_in_coach_session(setup):
    """A coach cannot apply a move for a student enrolled in another coach's session."""
    unowned_session_enrollment_repo = _FakeSessionEnrollmentRepo(
        entries={_STUDENT_ID: ["other-sess-99"]}
    )
    use_cases = _build_use_cases(
        setup["billing_enrollments"],
        setup["session_types"],
        setup["event_sink"],
        setup["stripe"],
        session_enrollment_repo=unowned_session_enrollment_repo,
    )
    app = _build_app(_coach_claims(), use_cases)
    with TestClient(app, raise_server_exceptions=True) as c:
        resp = c.post(
            f"/api/v2/coach/billing-enrollments/{_ENROLLMENT_ID}/move",
            json={"to_session_type_id": _ST_TO_ID},
        )
    assert resp.status_code == 403, resp.text


def test_move_returns_403_when_student_has_no_session_enrollments(setup):
    """A coach cannot move a billing enrollment for a student with no active session."""
    empty_session_enrollment_repo = _FakeSessionEnrollmentRepo(entries={})
    use_cases = _build_use_cases(
        setup["billing_enrollments"],
        setup["session_types"],
        setup["event_sink"],
        setup["stripe"],
        session_enrollment_repo=empty_session_enrollment_repo,
    )
    app = _build_app(_coach_claims(), use_cases)
    with TestClient(app, raise_server_exceptions=True) as c:
        resp = c.post(
            f"/api/v2/coach/billing-enrollments/{_ENROLLMENT_ID}/move",
            json={"to_session_type_id": _ST_TO_ID},
        )
    assert resp.status_code == 403, resp.text
