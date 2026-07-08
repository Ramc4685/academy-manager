"""Interface tests for parent trial-request routes (R3, Task 7)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.application.use_cases.trial_requests import (
    SubmitTrialRequestCommand,
)
from backend.v2.contexts.enrollment.domain.errors import StudentNotFound
from backend.v2.contexts.enrollment.domain.self_service import (
    DuplicateTrialRequest,
    TrialRequest,
    TrialSessionNotAvailable,
)
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


def _claims(role: str = "parent") -> AuthClaims:
    return AuthClaims(
        user_id="parent-1",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


def _trial_request(**overrides) -> TrialRequest:
    defaults = dict(
        request_id="req-1",
        academy_id="acad",
        parent_user_id="parent-1",
        student_ref="existing_student",
        student_id="student-1",
        requested_session_id="session-1",
        preferred_start="2026-07-15",
        preferred_end="2026-07-22",
        status="pending",
        created_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
    )
    defaults.update(overrides)
    return TrialRequest(**defaults)


class _ParentUseCases:
    def __init__(
        self,
        *,
        submit_result: TrialRequest | None = None,
        submit_error: Exception | None = None,
        list_result: list[TrialRequest] | None = None,
    ) -> None:
        self._submit_result = submit_result or _trial_request()
        self._submit_error = submit_error
        self._list_result = list_result if list_result is not None else [_trial_request()]
        self.submit_commands: list[SubmitTrialRequestCommand] = []

    class _Submit:
        def __init__(self, outer: _ParentUseCases) -> None:
            self._outer = outer

        async def execute(self, cmd: SubmitTrialRequestCommand) -> TrialRequest:
            self._outer.submit_commands.append(cmd)
            if self._outer._submit_error is not None:
                raise self._outer._submit_error
            return self._outer._submit_result

    class _List:
        def __init__(self, outer: _ParentUseCases) -> None:
            self._outer = outer

        async def execute(self, parent_user_id: str) -> list[TrialRequest]:
            return self._outer._list_result

    @property
    def submit_trial_request(self):
        return self._Submit(self)

    @property
    def list_parent_trial_requests(self):
        return self._List(self)


@contextmanager
def _make_client(
    role: str = "parent",
    use_cases: _ParentUseCases | None = None,
) -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_parent_use_cases] = lambda: use_cases or _ParentUseCases()
    with TestClient(app) as client:
        yield client


# --- POST /parent/trial-requests ---------------------------------------------


def test_create_trial_request_returns_201() -> None:
    use_cases = _ParentUseCases(submit_result=_trial_request(request_id="req-1"))
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/parent/trial-requests",
            json={
                "student_ref": "existing_student",
                "student_id": "student-1",
                "requested_session_id": "session-1",
                "preferred_start": "2026-07-15",
                "preferred_end": "2026-07-22",
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["request_id"] == "req-1"
    assert body["status"] == "pending"
    [cmd] = use_cases.submit_commands
    assert cmd.parent_user_id == "parent-1"
    assert cmd.student_ref == "existing_student"
    assert cmd.student_id == "student-1"


def test_create_trial_request_prospective_child() -> None:
    use_cases = _ParentUseCases(
        submit_result=_trial_request(
            student_ref="prospective", student_id=None, prospective_child_name="New Kid"
        )
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/parent/trial-requests",
            json={
                "student_ref": "prospective",
                "prospective_child_name": "New Kid",
                "requested_session_id": "session-1",
                "preferred_start": "2026-07-15",
                "preferred_end": "2026-07-22",
            },
        )

    assert response.status_code == 201, response.text
    [cmd] = use_cases.submit_commands
    assert cmd.student_ref == "prospective"
    assert cmd.prospective_child_name == "New Kid"


def test_create_trial_request_duplicate_returns_409() -> None:
    use_cases = _ParentUseCases(
        submit_error=DuplicateTrialRequest(
            "already exists", parent_user_id="parent-1", session_id="session-1"
        )
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/parent/trial-requests",
            json={
                "student_ref": "existing_student",
                "student_id": "student-1",
                "requested_session_id": "session-1",
                "preferred_start": "2026-07-15",
                "preferred_end": "2026-07-22",
            },
        )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "Enrollment.DuplicateTrialRequest"


def test_create_trial_request_session_unavailable_returns_409() -> None:
    use_cases = _ParentUseCases(
        submit_error=TrialSessionNotAvailable("not available", session_id="session-1")
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/parent/trial-requests",
            json={
                "student_ref": "existing_student",
                "student_id": "student-1",
                "requested_session_id": "session-1",
                "preferred_start": "2026-07-15",
                "preferred_end": "2026-07-22",
            },
        )

    assert response.status_code == 409, response.text


def test_create_trial_request_student_not_found_returns_404() -> None:
    use_cases = _ParentUseCases(submit_error=StudentNotFound("not found", student_id="student-1"))
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/parent/trial-requests",
            json={
                "student_ref": "existing_student",
                "student_id": "student-1",
                "requested_session_id": "session-1",
                "preferred_start": "2026-07-15",
                "preferred_end": "2026-07-22",
            },
        )

    assert response.status_code == 404, response.text


# --- GET /parent/trial-requests -----------------------------------------------


def test_list_trial_requests_returns_rows() -> None:
    use_cases = _ParentUseCases(list_result=[_trial_request(request_id="req-1")])
    with _make_client(use_cases=use_cases) as client:
        response = client.get("/api/v2/parent/trial-requests")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["trials"]) == 1
    assert body["trials"][0]["request_id"] == "req-1"


# --- wrong persona -> 404 ------------------------------------------------------


def test_wrong_persona_cannot_create_trial_request() -> None:
    with _make_client("admin") as client:
        response = client.post(
            "/api/v2/parent/trial-requests",
            json={
                "student_ref": "existing_student",
                "student_id": "student-1",
                "requested_session_id": "session-1",
                "preferred_start": "2026-07-15",
                "preferred_end": "2026-07-22",
            },
        )

    assert response.status_code == 404


def test_wrong_persona_cannot_list_trial_requests() -> None:
    with _make_client("coach") as client:
        response = client.get("/api/v2/parent/trial-requests")

    assert response.status_code == 404
