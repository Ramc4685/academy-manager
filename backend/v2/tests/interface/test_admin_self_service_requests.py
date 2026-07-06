"""Interface tests for admin self-service review routes (R2, Task 5)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.application.use_cases.makeup_requests import (
    AbsenceNoticeAdminView,
    ApproveMakeupRequestCommand,
    DenyMakeupRequestCommand,
    MakeupRequestAdminView,
)
from backend.v2.contexts.enrollment.domain.self_service import (
    MakeupRequest,
    MakeupRequestNotPending,
    MakeupWindowExpired,
    OccurrenceFull,
)
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


def _claims(role: str = "admin") -> AuthClaims:
    return AuthClaims(
        user_id="admin-1",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


def _makeup_request(
    *,
    request_id: str = "req-1",
    student_id: str = "student-1",
    status: str = "pending",
) -> MakeupRequest:
    return MakeupRequest(
        request_id=request_id,
        academy_id="acad",
        student_id=student_id,
        parent_id="parent-1",
        missed_occurrence_id="occ-missed",
        status=status,  # type: ignore[arg-type]
        expires_at=datetime(2026, 8, 1, tzinfo=UTC),
        created_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
    )


def _makeup_admin_view(**overrides) -> MakeupRequestAdminView:
    request = _makeup_request(
        **{k: v for k, v in overrides.items() if k in {"request_id", "student_id", "status"}}
    )
    return MakeupRequestAdminView(
        **request.model_dump(exclude={"academy_id", "parent_id"}),
        student_full_name=overrides.get("student_full_name", "Alice"),
    )


def _absence_admin_view(**overrides) -> AbsenceNoticeAdminView:
    return AbsenceNoticeAdminView(
        notice_id=overrides.get("notice_id", "n1"),
        student_id=overrides.get("student_id", "student-1"),
        occurrence_id=overrides.get("occurrence_id", "occ-1"),
        session_id=overrides.get("session_id", "session-1"),
        submitted_by=overrides.get("submitted_by", "parent-1"),
        submitted_at=overrides.get("submitted_at", datetime(2026, 7, 9, 8, 0, tzinfo=UTC)),
        notice_window_met=overrides.get("notice_window_met", True),
        student_full_name=overrides.get("student_full_name", "Alice"),
    )


class _AdminUseCases:
    def __init__(
        self,
        *,
        makeups_result: list[MakeupRequestAdminView] | None = None,
        absences_result: list[AbsenceNoticeAdminView] | None = None,
        approve_result: MakeupRequest | None = None,
        approve_error: Exception | None = None,
        deny_result: MakeupRequest | None = None,
        deny_error: Exception | None = None,
    ) -> None:
        self._makeups_result = (
            makeups_result if makeups_result is not None else [_makeup_admin_view()]
        )
        self._absences_result = (
            absences_result if absences_result is not None else [_absence_admin_view()]
        )
        self._approve_result = approve_result or _makeup_request(status="approved")
        self._approve_error = approve_error
        self._deny_result = deny_result or _makeup_request(status="denied")
        self._deny_error = deny_error
        self.list_makeups_calls: list[str | None] = []
        self.approve_commands: list[ApproveMakeupRequestCommand] = []
        self.deny_commands: list[DenyMakeupRequestCommand] = []

    class _ListMakeups:
        def __init__(self, outer: _AdminUseCases) -> None:
            self._outer = outer

        async def execute(self, status: str | None = None) -> list[MakeupRequestAdminView]:
            self._outer.list_makeups_calls.append(status)
            return self._outer._makeups_result

    class _ListAbsences:
        def __init__(self, outer: _AdminUseCases) -> None:
            self._outer = outer

        async def execute(self) -> list[AbsenceNoticeAdminView]:
            return self._outer._absences_result

    class _Approve:
        def __init__(self, outer: _AdminUseCases) -> None:
            self._outer = outer

        async def execute(self, cmd: ApproveMakeupRequestCommand) -> MakeupRequest:
            self._outer.approve_commands.append(cmd)
            if self._outer._approve_error is not None:
                raise self._outer._approve_error
            return self._outer._approve_result

    class _Deny:
        def __init__(self, outer: _AdminUseCases) -> None:
            self._outer = outer

        async def execute(self, cmd: DenyMakeupRequestCommand) -> MakeupRequest:
            self._outer.deny_commands.append(cmd)
            if self._outer._deny_error is not None:
                raise self._outer._deny_error
            return self._outer._deny_result

    @property
    def list_makeup_requests_for_admin(self):
        return self._ListMakeups(self)

    @property
    def list_absences_for_admin(self):
        return self._ListAbsences(self)

    @property
    def approve_makeup_request(self):
        return self._Approve(self)

    @property
    def deny_makeup_request(self):
        return self._Deny(self)


@contextmanager
def _make_client(
    role: str = "admin",
    use_cases: _AdminUseCases | None = None,
) -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_admin_use_cases] = lambda: use_cases or _AdminUseCases()
    with TestClient(app) as client:
        yield client


# --- GET /admin/self-service/makeups -----------------------------------------


def test_list_makeups_returns_enriched_rows() -> None:
    use_cases = _AdminUseCases(
        makeups_result=[_makeup_admin_view(request_id="req-1", student_full_name="Alice")]
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.get("/api/v2/admin/self-service/makeups")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["makeups"]) == 1
    assert body["makeups"][0]["request_id"] == "req-1"
    assert body["makeups"][0]["student_full_name"] == "Alice"
    assert use_cases.list_makeups_calls == [None]


def test_list_makeups_passes_status_filter() -> None:
    use_cases = _AdminUseCases()
    with _make_client(use_cases=use_cases) as client:
        response = client.get("/api/v2/admin/self-service/makeups", params={"status": "pending"})

    assert response.status_code == 200, response.text
    assert use_cases.list_makeups_calls == ["pending"]


# --- GET /admin/self-service/absences ----------------------------------------


def test_list_absences_returns_enriched_rows() -> None:
    use_cases = _AdminUseCases(
        absences_result=[_absence_admin_view(notice_id="n1", student_full_name="Bob")]
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.get("/api/v2/admin/self-service/absences")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["absences"]) == 1
    assert body["absences"][0]["notice_id"] == "n1"
    assert body["absences"][0]["student_full_name"] == "Bob"


# --- POST .../approve ---------------------------------------------------------


def test_approve_makeup_request_returns_updated_request() -> None:
    use_cases = _AdminUseCases(
        approve_result=_makeup_request(request_id="req-1", status="approved")
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/admin/self-service/makeups/req-1/approve",
            json={"target_occurrence_id": "occ-target"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    [cmd] = use_cases.approve_commands
    assert cmd.request_id == "req-1"
    assert cmd.actor_id == "admin-1"
    assert cmd.target_occurrence_id == "occ-target"


def test_approve_makeup_request_expired_window_returns_409() -> None:
    use_cases = _AdminUseCases(
        approve_error=MakeupWindowExpired("window closed", occurrence_id="occ-missed")
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/admin/self-service/makeups/req-1/approve",
            json={"target_occurrence_id": "occ-target"},
        )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "Enrollment.MakeupWindowExpired"


def test_approve_makeup_request_capacity_full_returns_409() -> None:
    use_cases = _AdminUseCases(
        approve_error=OccurrenceFull("no capacity", occurrence_id="occ-target")
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/admin/self-service/makeups/req-1/approve",
            json={"target_occurrence_id": "occ-target"},
        )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "Enrollment.OccurrenceFull"


def test_approve_makeup_request_non_pending_returns_409() -> None:
    use_cases = _AdminUseCases(
        approve_error=MakeupRequestNotPending("already decided", request_id="req-1")
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/admin/self-service/makeups/req-1/approve",
            json={"target_occurrence_id": "occ-target"},
        )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "Enrollment.MakeupRequestNotPending"


# --- POST .../deny -------------------------------------------------------------


def test_deny_makeup_request_returns_updated_request() -> None:
    use_cases = _AdminUseCases(deny_result=_makeup_request(request_id="req-1", status="denied"))
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/admin/self-service/makeups/req-1/deny",
            json={"reason": "no capacity"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "denied"
    [cmd] = use_cases.deny_commands
    assert cmd.request_id == "req-1"
    assert cmd.actor_id == "admin-1"
    assert cmd.reason == "no capacity"


def test_deny_makeup_request_non_pending_returns_409() -> None:
    use_cases = _AdminUseCases(
        deny_error=MakeupRequestNotPending("already decided", request_id="req-1")
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/admin/self-service/makeups/req-1/deny",
            json={"reason": "too late"},
        )

    assert response.status_code == 409, response.text


# --- wrong persona -> 404 ------------------------------------------------------


def test_wrong_persona_cannot_list_makeups() -> None:
    with _make_client("parent") as client:
        response = client.get("/api/v2/admin/self-service/makeups")

    assert response.status_code == 404


def test_wrong_persona_cannot_list_absences() -> None:
    with _make_client("coach") as client:
        response = client.get("/api/v2/admin/self-service/absences")

    assert response.status_code == 404


def test_wrong_persona_cannot_approve_makeup_request() -> None:
    with _make_client("parent") as client:
        response = client.post(
            "/api/v2/admin/self-service/makeups/req-1/approve",
            json={"target_occurrence_id": "occ-target"},
        )

    assert response.status_code == 404


def test_wrong_persona_cannot_deny_makeup_request() -> None:
    with _make_client("coach") as client:
        response = client.post(
            "/api/v2/admin/self-service/makeups/req-1/deny",
            json={"reason": "x"},
        )

    assert response.status_code == 404
