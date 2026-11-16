"""Staff cancel one approved website guest booking (L9): 204, and the family
gets the existing date-cancelled email for the booked date."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.domain.self_service import (
    TrialBookingNotCancellable,
    TrialRequest,
)
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

STARTS = datetime(2026, 12, 5, 15, 0, tzinfo=UTC)


def _booking() -> TrialRequest:
    return TrialRequest(
        request_id="tr-1",
        academy_id="acad",
        contact_id="contact-1",
        student_ref="prospective",
        requested_session_id="sess-1",
        preferred_start="2026-12-05",
        preferred_end="2026-12-05",
        status="approved",
        assigned_occurrence_id="occ-1",
        created_at=datetime(2026, 11, 20, tzinfo=UTC),
        guest_starts_at=STARTS,
    )


class _Cancel:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[str] = []

    async def execute(self, request_id: str) -> TrialRequest:
        self.calls.append(request_id)
        if self.error is not None:
            raise self.error
        return _booking()


class _UseCases:
    def __init__(self, cancel: _Cancel) -> None:
        self.cancel_guest_trial_booking = cancel


class _Emails:
    def __init__(self) -> None:
        self.cancelled: list[dict[str, Any]] = []

    async def trial_date_cancelled(self, **kwargs: Any) -> None:
        self.cancelled.append(kwargs)


def _client(cancel: _Cancel, emails: _Emails, role: str = "admin") -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.state.trial_emails = emails
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="admin-1",
        email="admin@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_admin_use_cases] = lambda: _UseCases(cancel)
    return TestClient(app)


URL = "/api/v2/admin/self-service/trials/tr-1/cancel-booking"


def test_cancel_booking_returns_204_and_emails_the_booked_date() -> None:
    cancel, emails = _Cancel(), _Emails()
    with _client(cancel, emails) as client:
        response = client.post(URL)

    assert response.status_code == 204, response.text
    assert cancel.calls == ["tr-1"]
    [sent] = emails.cancelled
    assert sent["start_at"] == STARTS
    assert [t.request_id for t in sent["trials"]] == ["tr-1"]


def test_cancel_booking_not_cancellable_is_409_and_sends_nothing() -> None:
    cancel = _Cancel(TrialBookingNotCancellable("no", request_id="tr-1"))
    emails = _Emails()
    with _client(cancel, emails) as client:
        response = client.post(URL)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "Enrollment.TrialBookingNotCancellable"
    assert emails.cancelled == []


def test_cancel_booking_requires_admin() -> None:
    cancel, emails = _Cancel(), _Emails()
    with _client(cancel, emails, role="coach") as client:
        response = client.post(URL)

    assert response.status_code == 404  # admin routes hide from other personas
    assert cancel.calls == []
