"""Interface tests for GET /parent/attendance and GET /parent/progress."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


def _claims(role: str = "parent", user_id: str = "parent-1") -> AuthClaims:
    return AuthClaims(
        user_id=user_id,
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


_NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)


def _attendance_row(*, idx: int, coach_name: str | None = None) -> dict:
    return {
        "attendance_id": f"att-{idx}",
        "student_id": "student-1",
        "student_name": "Alice Smith",
        "session_id": "sess-1",
        "session_title": "Morning Squad",
        "status": "present",
        "marked_at": _NOW,
        "coach_name": coach_name,
    }


def _progress_row(*, idx: int, coach_name: str | None = None) -> dict:
    return {
        "note_id": f"note-{idx}",
        "student_id": "student-1",
        "student_name": "Alice Smith",
        "session_id": "sess-1",
        "session_title": "Morning Squad",
        "coach_id": "coach-1" if coach_name else None,
        "coach_name": coach_name,
        "body": f"Great progress note {idx}",
        "created_at": _NOW,
    }


class _FakeParentUseCases:
    def __init__(
        self,
        attendance_rows: list[dict],
        progress_rows: list[dict],
        enrollment_rows: list[dict] | None = None,
    ) -> None:
        self._attendance = attendance_rows
        self._progress = progress_rows
        self._enrollments = enrollment_rows or []

    async def list_attendance_for_parent(
        self,
        parent_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        total = len(self._attendance)
        return self._attendance[offset : offset + limit], total

    async def list_progress_for_parent(
        self,
        parent_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        total = len(self._progress)
        return self._progress[offset : offset + limit], total

    async def list_enrollments_for_parent(self, parent_id: str) -> list[dict]:
        return list(self._enrollments)


def _seed_attendance(n: int = 3, coach_name: str | None = "Coach Bob") -> list[dict]:
    return [_attendance_row(idx=i, coach_name=coach_name) for i in range(1, n + 1)]


def _seed_progress(n: int = 3, coach_name: str | None = "Coach Bob") -> list[dict]:
    return [_progress_row(idx=i, coach_name=coach_name) for i in range(1, n + 1)]


@contextmanager
def _make_client(
    attendance: list[dict] | None = None,
    progress: list[dict] | None = None,
    enrollments: list[dict] | None = None,
    role: str = "parent",
    user_id: str = "parent-1",
) -> Iterator[TestClient]:
    if attendance is None:
        attendance = _seed_attendance()
    if progress is None:
        progress = _seed_progress()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role, user_id)
    app.dependency_overrides[get_parent_use_cases] = lambda: _FakeParentUseCases(
        attendance, progress, enrollments
    )
    with TestClient(app) as client:
        yield client


@contextmanager
def _anon_client() -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_parent_use_cases] = lambda: _FakeParentUseCases([], [])
    with TestClient(app) as client:
        yield client


# ---------------------------------------------------------------------------
# Attendance tests
# ---------------------------------------------------------------------------


def test_attendance_happy_path() -> None:
    with _make_client() as client:
        response = client.get("/api/v2/parent/attendance")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert len(body["records"]) == 3
    first = body["records"][0]
    assert first["attendance_id"] == "att-1"
    assert first["session_title"] == "Morning Squad"
    assert first["coach_name"] == "Coach Bob"


def test_attendance_coach_name_none_when_unknown() -> None:
    rows = _seed_attendance(n=2, coach_name=None)
    with _make_client(attendance=rows) as client:
        response = client.get("/api/v2/parent/attendance")

    assert response.status_code == 200
    body = response.json()
    for rec in body["records"]:
        assert rec["coach_name"] is None


def test_attendance_pagination_limit_offset() -> None:
    rows = [_attendance_row(idx=i) for i in range(1, 11)]
    with _make_client(attendance=rows) as client:
        response = client.get("/api/v2/parent/attendance?limit=3&offset=4")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 10
    assert body["limit"] == 3
    assert body["offset"] == 4
    assert len(body["records"]) == 3
    assert body["records"][0]["attendance_id"] == "att-5"


def test_attendance_total_correct_with_full_set() -> None:
    rows = [_attendance_row(idx=i) for i in range(1, 8)]
    with _make_client(attendance=rows) as client:
        response = client.get("/api/v2/parent/attendance?limit=5&offset=0")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 7
    assert len(body["records"]) == 5


def test_attendance_empty_returns_zero_total() -> None:
    with _make_client(attendance=[]) as client:
        response = client.get("/api/v2/parent/attendance")

    assert response.status_code == 200
    body = response.json()
    assert body["records"] == []
    assert body["total"] == 0


def test_attendance_wrong_persona_returns_404() -> None:
    with _make_client(role="coach") as client:
        response = client.get("/api/v2/parent/attendance")
    assert response.status_code == 404


def test_attendance_anonymous_returns_401() -> None:
    with _anon_client() as client:
        response = client.get("/api/v2/parent/attendance")
    assert response.status_code == 401


def test_enrollments_expose_app_owned_autopay_visibility_fields() -> None:
    enrollments = [
        {
            "enrollment_id": "enr-1",
            "student_id": "student-1",
            "student_name": "Alice Smith",
            "session_id": "sess-1",
            "session_title": "Morning Squad",
            "status": "active",
            "payment_mode": "monthly",
            "subscription_status": None,
            "autopay_enrollment_status": "active",
            "last_attempt_outcome": "declined",
            "last_attempt_at": _NOW,
            "last_failure_code": "insufficient_funds",
            "autopay_payment_method_type": "us_bank_account",
            "autopay_payment_method_label": "Stripe Test Bank",
            "autopay_payment_method_last4": "6789",
            "autopay_setup_status": "active",
        }
    ]
    with _make_client(enrollments=enrollments) as client:
        response = client.get("/api/v2/parent/enrollments")

    assert response.status_code == 200
    row = response.json()["enrollments"][0]
    assert row["autopay_enrollment_status"] == "active"
    assert row["last_attempt_outcome"] == "declined"
    assert row["last_attempt_at"] == "2026-05-31T12:00:00Z"
    assert row["last_failure_code"] == "insufficient_funds"
    assert row["autopay_payment_method_type"] == "us_bank_account"
    assert row["autopay_payment_method_label"] == "Stripe Test Bank"
    assert row["autopay_payment_method_last4"] == "6789"
    assert row["autopay_setup_status"] == "active"


# ---------------------------------------------------------------------------
# Progress tests
# ---------------------------------------------------------------------------


def test_progress_happy_path() -> None:
    with _make_client() as client:
        response = client.get("/api/v2/parent/progress")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert len(body["notes"]) == 3
    first = body["notes"][0]
    assert first["note_id"] == "note-1"
    assert first["session_title"] == "Morning Squad"
    assert first["coach_name"] == "Coach Bob"


def test_progress_coach_name_none_when_unknown() -> None:
    rows = _seed_progress(n=2, coach_name=None)
    with _make_client(progress=rows) as client:
        response = client.get("/api/v2/parent/progress")

    assert response.status_code == 200
    body = response.json()
    for note in body["notes"]:
        assert note["coach_name"] is None


def test_progress_pagination_limit_offset() -> None:
    rows = [_progress_row(idx=i) for i in range(1, 11)]
    with _make_client(progress=rows) as client:
        response = client.get("/api/v2/parent/progress?limit=3&offset=2")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 10
    assert body["limit"] == 3
    assert body["offset"] == 2
    assert len(body["notes"]) == 3
    assert body["notes"][0]["note_id"] == "note-3"


def test_progress_total_correct_with_full_set() -> None:
    rows = [_progress_row(idx=i) for i in range(1, 6)]
    with _make_client(progress=rows) as client:
        response = client.get("/api/v2/parent/progress?limit=2&offset=0")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["notes"]) == 2


def test_progress_empty_returns_zero_total() -> None:
    with _make_client(progress=[]) as client:
        response = client.get("/api/v2/parent/progress")

    assert response.status_code == 200
    body = response.json()
    assert body["notes"] == []
    assert body["total"] == 0


def test_progress_wrong_persona_returns_404() -> None:
    with _make_client(role="coach") as client:
        response = client.get("/api/v2/parent/progress")
    assert response.status_code == 404


def test_progress_anonymous_returns_401() -> None:
    with _anon_client() as client:
        response = client.get("/api/v2/parent/progress")
    assert response.status_code == 401
