"""Interface tests for Came / Didn't come and Pipeline moves (People CRM L3a).

The real admin and coach routers, with the real ``MarkTrialOutcome`` and
``MoveCardOnPipeline`` over the store fakes of
``tests/fixtures/trial_outcome_fakes.py`` (their store semantics are proven on
a real ``mongod`` in ``contract/test_trial_outcome_pipeline_real_mongo.py``).
Checks the persona gates (wrong persona is the 404 of docs/security-matrix.md),
the coach's session scope, the tenant, the 409s and the response shapes.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.crm.application.use_cases.pipeline_moves import MoveCardOnPipeline
from backend.v2.contexts.crm.domain.models import CrmContact
from backend.v2.contexts.enrollment.application.use_cases.trial_outcomes import MarkTrialOutcome
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.contexts.enrollment.domain.self_service import TrialRequest
from backend.v2.interfaces.admin import trial_outcome_routes as admin_trial_routes
from backend.v2.interfaces.admin.pipeline_routes import get_move_card
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.interfaces.coach import trial_outcome_routes as coach_trial_routes
from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import _current as _tenant
from backend.v2.tests.fixtures.trial_outcome_fakes import (
    FakeAssignments,
    FakeContactStore,
    FakeOccurrences,
    FakeTrialStore,
)

A = "acad-a"
B = "acad-b"
NOW = datetime(2026, 9, 24, 18, 30, tzinfo=UTC)
ADMIN_URL = "/api/v2/admin/self-service/trials/{rid}/outcome"
COACH_URL = "/api/v2/coach/trials/{rid}/outcome"
MOVE_URL = "/api/v2/admin/crm/contacts/{cid}/pipeline-move"


def _trial(request_id: str, *, academy: str = A, status: str = "approved") -> TrialRequest:
    return TrialRequest(
        request_id=request_id,
        academy_id=academy,
        parent_user_id="p-1",
        student_ref="prospective",
        prospective_child_name="Sample Child",
        requested_session_id="s-1",
        preferred_start="2026-09-20",
        preferred_end="2026-09-30",
        status=status,  # type: ignore[arg-type]
        assigned_occurrence_id="occ-1",
        created_at=NOW - timedelta(days=2),
    )


def _occ(academy: str) -> SessionOccurrence:
    return SessionOccurrence(
        occurrence_id="occ-1",
        academy_id=academy,
        session_id="s-1",
        start_at=NOW - timedelta(minutes=30),
        end_at=NOW + timedelta(minutes=30),
        scheduled_coach_id="coach-1",
    )


def _contact(contact_id: str, *, academy: str = A) -> CrmContact:
    return CrmContact(
        contact_id=contact_id,
        academy_id=academy,
        name="Sample Parent",
        phone_digits="5550102030",
        source="referral",
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
    )


class Caller:
    def __init__(self) -> None:
        self.be("staff-1", "admin")

    def be(self, user_id: str, *roles: str, academy_id: str = A) -> None:
        self.claims = AuthClaims(
            user_id=user_id,
            email=f"{user_id}@example.test",
            academy_id=academy_id,
            roles=roles,  # type: ignore[arg-type]
        )


@pytest.fixture
def caller() -> Caller:
    return Caller()


@pytest.fixture
def trials() -> FakeTrialStore:
    return FakeTrialStore(
        _trial("tr-1"), _trial("tr-pending", status="pending"), _trial("tr-b", academy=B)
    )


@pytest.fixture
def contacts() -> FakeContactStore:
    return FakeContactStore(_contact("c-1"), _contact("c-b", academy=B))


@pytest.fixture
def client(
    caller: Caller, trials: FakeTrialStore, contacts: FakeContactStore
) -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.include_router(coach_router, prefix="/api/v2")
    mark = MarkTrialOutcome(
        trials=trials,
        occurrences=FakeOccurrences(_occ(A), _occ(B)),
        assignments=FakeAssignments(("coach-1", "s-1")),
        clock=lambda: NOW,
    )
    move = MoveCardOnPipeline(contacts, clock=lambda: NOW)

    async def claims() -> AuthClaims:
        _tenant.set(caller.claims.academy_id)
        return caller.claims

    app.dependency_overrides[get_auth_claims] = claims
    app.dependency_overrides[admin_trial_routes.get_mark_trial_outcome] = lambda: mark
    app.dependency_overrides[coach_trial_routes.get_mark_trial_outcome] = lambda: mark
    app.dependency_overrides[get_move_card] = lambda: move
    with TestClient(app) as c:
        yield c


# --- admin Inbox: Came / Didn't come ---


def test_admin_marks_came_and_gets_the_updated_row(client: TestClient) -> None:
    response = client.post(ADMIN_URL.format(rid="tr-1"), json={"outcome": "came"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["status"], body["outcome"], body["outcome_by"]) == ("completed", "came", "staff-1")
    assert body["request_id"] == "tr-1"
    assert "academy_id" not in body and "parent_user_id" not in body


def test_admin_gate_matches_approve_and_deny(client: TestClient, caller: Caller) -> None:
    """Same ``require_persona("admin")`` gate as the Inbox approve/deny routes:
    a staff tier alone (no ``admin`` role) gets the wrong-persona 404."""
    caller.be("staff-2", "admin", "front_desk")
    ok = client.post(ADMIN_URL.format(rid="tr-1"), json={"outcome": "no_show"})
    assert ok.status_code == 200, ok.text
    caller.be("staff-3", "front_desk")
    assert client.post(ADMIN_URL.format(rid="tr-1"), json={"outcome": "came"}).status_code == 404


def test_admin_pending_trial_is_409_with_reason(client: TestClient) -> None:
    response = client.post(ADMIN_URL.format(rid="tr-pending"), json={"outcome": "came"})
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "Enrollment.TrialOutcomeNotAllowed"
    assert error["details"]["reason"] == "status_pending"


def test_admin_other_academy_trial_is_404(client: TestClient, trials: FakeTrialStore) -> None:
    response = client.post(ADMIN_URL.format(rid="tr-b"), json={"outcome": "came"})
    assert response.status_code == 404
    assert trials.rows[(B, "tr-b")].status == "approved"


def test_admin_rejects_unknown_outcome_and_extra_fields(client: TestClient) -> None:
    assert client.post(ADMIN_URL.format(rid="tr-1"), json={"outcome": "maybe"}).status_code == 422
    extra = {"outcome": "came", "academy_id": B}
    assert client.post(ADMIN_URL.format(rid="tr-1"), json=extra).status_code == 422


@pytest.mark.parametrize("role", ["coach", "parent"])
def test_admin_route_is_404_for_coach_and_parent(
    client: TestClient, caller: Caller, role: str
) -> None:
    caller.be("someone", role)
    response = client.post(ADMIN_URL.format(rid="tr-1"), json={"outcome": "came"})
    assert response.status_code == 404


# --- coach Today: Came / Didn't come ---


def test_coach_marks_a_trial_on_their_session(client: TestClient, caller: Caller) -> None:
    caller.be("coach-1", "coach")
    response = client.post(COACH_URL.format(rid="tr-1"), json={"outcome": "came"})
    assert response.status_code == 200, response.text
    assert response.json() == {"request_id": "tr-1", "status": "completed", "outcome": "came"}


def test_coach_on_another_class_gets_404(
    client: TestClient, caller: Caller, trials: FakeTrialStore
) -> None:
    caller.be("coach-2", "coach")
    for rid in ("tr-1", "tr-pending", "tr-b", "missing"):
        response = client.post(COACH_URL.format(rid=rid), json={"outcome": "came"})
        assert response.status_code == 404, rid
    assert trials.writes == 0


def test_coach_supervisor_may_mark_any_trial_of_the_academy(
    client: TestClient, caller: Caller
) -> None:
    caller.be("owner-1", "owner")
    response = client.post(COACH_URL.format(rid="tr-1"), json={"outcome": "no_show"})
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "no_show"


def test_coach_route_is_404_for_a_parent(client: TestClient, caller: Caller) -> None:
    caller.be("p-1", "parent")
    response = client.post(COACH_URL.format(rid="tr-1"), json={"outcome": "came"})
    assert response.status_code == 404


# --- Pipeline moves ---


def test_move_writes_override_and_answers_the_card(client: TestClient) -> None:
    response = client.post(MOVE_URL.format(cid="c-1"), json={"to_column": "trial_booked"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["contact_id"] == "c-1"
    assert body["column"] == "trial_booked"
    assert body["pipeline_status"] == "lead"
    assert body["pipeline_override"]["set_by"] == "staff-1"
    assert body["pipeline_override"]["column"] == "trial_booked"


def test_move_forward_skip_is_409(client: TestClient, contacts: FakeContactStore) -> None:
    response = client.post(MOVE_URL.format(cid="c-1"), json={"to_column": "registered"})
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "Crm.PipelineMoveNotAllowed"
    assert error["details"]["reason"] == "stage_skip"
    assert contacts.writes == 0


def test_move_to_enrolled_is_not_accepted(client: TestClient) -> None:
    response = client.post(MOVE_URL.format(cid="c-1"), json={"to_column": "enrolled"})
    assert response.status_code == 422


def test_move_other_academy_contact_is_404(client: TestClient, contacts: FakeContactStore) -> None:
    response = client.post(MOVE_URL.format(cid="c-b"), json={"to_column": "trial_booked"})
    assert response.status_code == 404
    assert contacts.rows[(B, "c-b")].pipeline_override is None


@pytest.mark.parametrize("role", ["coach", "parent"])
def test_move_is_404_for_coach_and_parent(client: TestClient, caller: Caller, role: str) -> None:
    caller.be("someone", role)
    response = client.post(MOVE_URL.format(cid="c-1"), json={"to_column": "trial_booked"})
    assert response.status_code == 404
