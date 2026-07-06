"""Interface tests for parent self-cancel enrollment routes (R4)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.application.use_cases.self_cancel import (
    PreviewSelfCancelView,
    SelfCancelEnrollmentCommand,
    SelfCancelEnrollmentResult,
)
from backend.v2.contexts.enrollment.domain.errors import EnrollmentNotFound
from backend.v2.contexts.enrollment.domain.self_service import EnrollmentNotCancellable
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


def _preview_view(
    *,
    allowed: bool = True,
    notice_met: bool = True,
    fee_cents: int = 0,
    effective_timing: str = "end_of_period",
    blocked_reason: str | None = None,
) -> PreviewSelfCancelView:
    return PreviewSelfCancelView(
        allowed=allowed,
        notice_met=notice_met,
        fee_cents=fee_cents,
        effective_timing=effective_timing,
        policy={
            "academy_id": "acad",
            "absence_notice_min_hours": 2,
            "makeup_expiry_days": 30,
            "makeup_requires_notice": True,
            "cancellation_minimum_notice_days": 7,
            "cancellation_fee_cents": 2500,
            "cancellation_effective_timing": effective_timing,
            "fee_cents": fee_cents,
            "notice_met": notice_met,
        },
        blocked_reason=blocked_reason,
    )


def _cancel_result(
    *,
    enrollment_id: str = "enr-1",
    status: str = "cancelled",
    fee_cents: int = 0,
    notice_met: bool = True,
    effective_timing: str = "immediate",
    cancelled_at: datetime | None = None,
) -> SelfCancelEnrollmentResult:
    return SelfCancelEnrollmentResult(
        enrollment_id=enrollment_id,
        status=status,
        fee_cents=fee_cents,
        notice_met=notice_met,
        effective_timing=effective_timing,
        cancelled_at=cancelled_at or datetime(2026, 7, 6, 12, 0, tzinfo=UTC),
    )


class _ParentUseCases:
    def __init__(
        self,
        *,
        preview_result: PreviewSelfCancelView | None = None,
        preview_error: Exception | None = None,
        cancel_result: SelfCancelEnrollmentResult | None = None,
        cancel_error: Exception | None = None,
    ) -> None:
        self._preview_result = preview_result or _preview_view()
        self._preview_error = preview_error
        self._cancel_result = cancel_result or _cancel_result()
        self._cancel_error = cancel_error
        self.preview_calls: list[dict[str, str]] = []
        self.cancel_commands: list[SelfCancelEnrollmentCommand] = []

    class _Preview:
        def __init__(self, outer: _ParentUseCases) -> None:
            self._outer = outer

        async def execute(self, *, enrollment_id: str, parent_id: str) -> PreviewSelfCancelView:
            self._outer.preview_calls.append(
                {"enrollment_id": enrollment_id, "parent_id": parent_id}
            )
            if self._outer._preview_error is not None:
                raise self._outer._preview_error
            return self._outer._preview_result

    class _Cancel:
        def __init__(self, outer: _ParentUseCases) -> None:
            self._outer = outer

        async def execute(self, cmd: SelfCancelEnrollmentCommand) -> SelfCancelEnrollmentResult:
            self._outer.cancel_commands.append(cmd)
            if self._outer._cancel_error is not None:
                raise self._outer._cancel_error
            return self._outer._cancel_result

    @property
    def preview_self_cancel(self):
        return self._Preview(self)

    @property
    def self_cancel_enrollment(self):
        return self._Cancel(self)


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


def test_get_cancellation_preview_returns_terms() -> None:
    use_cases = _ParentUseCases(
        preview_result=_preview_view(allowed=True, notice_met=False, fee_cents=2500)
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.get("/api/v2/parent/enrollments/enr-1/cancellation-preview")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["allowed"] is True
    assert body["notice_met"] is False
    assert body["fee_cents"] == 2500
    assert body["blocked_reason"] is None
    assert body["policy"]["cancellation_minimum_notice_days"] == 7
    [call] = use_cases.preview_calls
    assert call == {"enrollment_id": "enr-1", "parent_id": "parent-1"}


def test_get_cancellation_preview_not_allowed_when_not_active() -> None:
    use_cases = _ParentUseCases(
        preview_result=_preview_view(allowed=False, blocked_reason="enrollment is not active")
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.get("/api/v2/parent/enrollments/enr-1/cancellation-preview")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["allowed"] is False
    assert body["blocked_reason"] == "enrollment is not active"


def test_get_cancellation_preview_for_other_parent_is_404() -> None:
    use_cases = _ParentUseCases(
        preview_error=EnrollmentNotFound("enrollment missing", enrollment_id="enr-1")
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.get("/api/v2/parent/enrollments/enr-1/cancellation-preview")

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "Enrollment.NotFound"


def test_post_self_cancel_returns_200_with_result_fields() -> None:
    use_cases = _ParentUseCases(
        cancel_result=_cancel_result(
            enrollment_id="enr-1",
            status="cancelled",
            fee_cents=0,
            effective_timing="immediate",
            cancelled_at=datetime(2026, 7, 6, 12, 0, tzinfo=UTC),
        )
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/parent/enrollments/enr-1/self-cancel",
            json={"reason": "moving away"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "enrollment_id": "enr-1",
        "status": "cancelled",
        "fee_cents": 0,
        "effective_timing": "immediate",
        "cancelled_at": "2026-07-06T12:00:00Z",
    }
    [cmd] = use_cases.cancel_commands
    assert cmd.enrollment_id == "enr-1"
    assert cmd.parent_id == "parent-1"
    assert cmd.reason == "moving away"


def test_post_self_cancel_non_active_returns_409() -> None:
    use_cases = _ParentUseCases(
        cancel_error=EnrollmentNotCancellable("not active", enrollment_id="enr-1")
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/parent/enrollments/enr-1/self-cancel",
            json={"reason": "r"},
        )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "Enrollment.NotCancellable"


def test_post_self_cancel_wrong_parent_returns_404() -> None:
    use_cases = _ParentUseCases(
        cancel_error=EnrollmentNotFound("enrollment missing", enrollment_id="enr-1")
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/parent/enrollments/enr-1/self-cancel",
            json={"reason": "r"},
        )

    assert response.status_code == 404, response.text


def test_wrong_persona_cannot_preview_cancellation() -> None:
    with _make_client("admin") as client:
        response = client.get("/api/v2/parent/enrollments/enr-1/cancellation-preview")

    assert response.status_code == 404


def test_wrong_persona_cannot_self_cancel() -> None:
    with _make_client("coach") as client:
        response = client.post(
            "/api/v2/parent/enrollments/enr-1/self-cancel",
            json={"reason": "r"},
        )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Admin audit list route
# ---------------------------------------------------------------------------

from backend.v2.contexts.enrollment.application.use_cases.self_cancel import (
    SelfCancellationAdminView,
)
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router


def _admin_claims(role: str = "admin") -> AuthClaims:
    return AuthClaims(
        user_id="admin-1",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


def _cancellation_row(
    *,
    enrollment_id: str = "enr-1",
    student_full_name: str | None = "Kid One",
    session_title: str | None = "Beginner Tennis",
) -> SelfCancellationAdminView:
    return SelfCancellationAdminView(
        enrollment_id=enrollment_id,
        student_id="student-1",
        session_id="session-1",
        cancellation_reason="moving away",
        cancellation_policy_snapshot={"fee_cents": 0, "notice_met": True},
        cancelled_at=datetime(2026, 7, 6, 12, 0, tzinfo=UTC),
        student_full_name=student_full_name,
        session_title=session_title,
    )


class _AdminUseCases:
    def __init__(self, *, rows: list[SelfCancellationAdminView] | None = None) -> None:
        self._rows = rows if rows is not None else [_cancellation_row()]

    class _List:
        def __init__(self, outer: _AdminUseCases) -> None:
            self._outer = outer

        async def execute(self) -> list[SelfCancellationAdminView]:
            return self._outer._rows

    @property
    def list_self_cancellations_for_admin(self):
        return self._List(self)


@contextmanager
def _make_admin_client(
    role: str = "admin",
    use_cases: _AdminUseCases | None = None,
) -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _admin_claims(role)
    app.dependency_overrides[get_admin_use_cases] = lambda: use_cases or _AdminUseCases()
    with TestClient(app) as client:
        yield client


def test_admin_list_self_cancellations_returns_rows() -> None:
    use_cases = _AdminUseCases(rows=[_cancellation_row()])
    with _make_admin_client(use_cases=use_cases) as client:
        response = client.get("/api/v2/admin/self-service/cancellations")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["cancellations"]) == 1
    row = body["cancellations"][0]
    assert row["enrollment_id"] == "enr-1"
    assert row["student_full_name"] == "Kid One"
    assert row["session_title"] == "Beginner Tennis"


def test_wrong_persona_cannot_list_admin_self_cancellations() -> None:
    with _make_admin_client("parent") as client:
        response = client.get("/api/v2/admin/self-service/cancellations")

    assert response.status_code == 404
