"""Interface tests for parent makeup-request routes (R2)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.application.use_cases.makeup_requests import (
    MakeupTargetView,
    SubmitMakeupRequestCommand,
)
from backend.v2.contexts.enrollment.domain.self_service import DuplicateMakeupRequest, MakeupRequest
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


def _makeup_request(
    *,
    request_id: str = "req-1",
    student_id: str = "student-1",
    missed_occurrence_id: str = "occ-1",
    status: str = "pending",
) -> MakeupRequest:
    return MakeupRequest(
        request_id=request_id,
        academy_id="acad",
        student_id=student_id,
        parent_id="parent-1",
        missed_occurrence_id=missed_occurrence_id,
        status=status,  # type: ignore[arg-type]
        expires_at=datetime(2026, 8, 1, tzinfo=UTC),
        created_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
    )


class _ParentUseCases:
    def __init__(
        self,
        *,
        submit_result: MakeupRequest | None = None,
        submit_error: Exception | None = None,
        list_result: list[MakeupRequest] | None = None,
        targets_result: list[MakeupTargetView] | None = None,
    ) -> None:
        self._submit_result = submit_result or _makeup_request()
        self._submit_error = submit_error
        self._list_result = list_result if list_result is not None else [_makeup_request()]
        self._targets_result = targets_result if targets_result is not None else []
        self.submitted_commands: list[SubmitMakeupRequestCommand] = []
        self.targets_calls: list[dict[str, str]] = []

    class _Submit:
        def __init__(self, outer: _ParentUseCases) -> None:
            self._outer = outer

        async def execute(self, cmd: SubmitMakeupRequestCommand) -> MakeupRequest:
            self._outer.submitted_commands.append(cmd)
            if self._outer._submit_error is not None:
                raise self._outer._submit_error
            return self._outer._submit_result

    class _List:
        def __init__(self, outer: _ParentUseCases) -> None:
            self._outer = outer

        async def execute(self, parent_id: str) -> list[MakeupRequest]:
            return self._outer._list_result

    class _Targets:
        def __init__(self, outer: _ParentUseCases) -> None:
            self._outer = outer

        async def execute(
            self, *, parent_id: str, student_id: str, missed_occurrence_id: str
        ) -> list[MakeupTargetView]:
            self._outer.targets_calls.append(
                {
                    "parent_id": parent_id,
                    "student_id": student_id,
                    "missed_occurrence_id": missed_occurrence_id,
                }
            )
            return self._outer._targets_result

    @property
    def submit_makeup_request(self):
        return self._Submit(self)

    @property
    def list_parent_makeups(self):
        return self._List(self)

    @property
    def list_eligible_makeup_targets(self):
        return self._Targets(self)


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


def test_post_makeup_request_returns_201() -> None:
    use_cases = _ParentUseCases(submit_result=_makeup_request(status="pending"))
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/parent/makeups",
            json={"student_id": "student-1", "missed_occurrence_id": "occ-1"},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["request_id"] == "req-1"
    assert body["student_id"] == "student-1"
    assert body["missed_occurrence_id"] == "occ-1"
    assert body["status"] == "pending"
    [cmd] = use_cases.submitted_commands
    assert cmd.parent_id == "parent-1"
    assert cmd.student_id == "student-1"
    assert cmd.missed_occurrence_id == "occ-1"
    assert cmd.requested_target_occurrence_id is None


def test_post_makeup_request_with_requested_target() -> None:
    use_cases = _ParentUseCases()
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/parent/makeups",
            json={
                "student_id": "student-1",
                "missed_occurrence_id": "occ-1",
                "requested_target_occurrence_id": "occ-target",
            },
        )

    assert response.status_code == 201, response.text
    [cmd] = use_cases.submitted_commands
    assert cmd.requested_target_occurrence_id == "occ-target"


def test_get_makeups_lists_all_statuses_including_expired() -> None:
    use_cases = _ParentUseCases(
        list_result=[
            _makeup_request(request_id="req-pending", status="pending"),
            _makeup_request(request_id="req-expired", status="expired"),
        ]
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.get("/api/v2/parent/makeups")

    assert response.status_code == 200, response.text
    body = response.json()
    statuses = {r["request_id"]: r["status"] for r in body["makeups"]}
    assert statuses == {"req-pending": "pending", "req-expired": "expired"}


def test_get_eligible_targets_returns_targets() -> None:
    use_cases = _ParentUseCases(
        targets_result=[
            MakeupTargetView(
                occurrence_id="occ-target",
                session_id="session-target",
                title="Target session",
                start_at=datetime(2026, 7, 12, 10, 0, tzinfo=UTC),
                end_at=datetime(2026, 7, 12, 11, 0, tzinfo=UTC),
                open_slots=3,
            )
        ]
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.get(
            "/api/v2/parent/makeups/eligible-targets",
            params={"student_id": "student-1", "missed_occurrence_id": "occ-1"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["targets"]) == 1
    assert body["targets"][0]["occurrence_id"] == "occ-target"
    assert body["targets"][0]["open_slots"] == 3
    [call] = use_cases.targets_calls
    assert call == {
        "parent_id": "parent-1",
        "student_id": "student-1",
        "missed_occurrence_id": "occ-1",
    }


def test_wrong_persona_cannot_submit_makeup_request() -> None:
    with _make_client("admin") as client:
        response = client.post(
            "/api/v2/parent/makeups",
            json={"student_id": "student-1", "missed_occurrence_id": "occ-1"},
        )

    assert response.status_code == 404


def test_wrong_persona_cannot_list_makeups() -> None:
    with _make_client("coach") as client:
        response = client.get("/api/v2/parent/makeups")

    assert response.status_code == 404


def test_wrong_persona_cannot_list_eligible_targets() -> None:
    with _make_client("admin") as client:
        response = client.get(
            "/api/v2/parent/makeups/eligible-targets",
            params={"student_id": "student-1", "missed_occurrence_id": "occ-1"},
        )

    assert response.status_code == 404


def test_duplicate_makeup_request_returns_409_with_error_code() -> None:
    use_cases = _ParentUseCases(
        submit_error=DuplicateMakeupRequest("already requested", occurrence_id="occ-1")
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/parent/makeups",
            json={"student_id": "student-1", "missed_occurrence_id": "occ-1"},
        )

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"]["code"] == "Enrollment.DuplicateMakeupRequest"
