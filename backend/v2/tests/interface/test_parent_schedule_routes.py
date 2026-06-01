"""Interface tests for GET /parent/children/{student_id}/schedule."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.application.use_cases.get_child_schedule import (
    ChildScheduleEntry,
    StudentNotOwnedByParent,
)
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


_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _entry(oid: str, start_offset_hours: int = 0) -> ChildScheduleEntry:
    start = _NOW + timedelta(hours=start_offset_hours)
    return ChildScheduleEntry(
        occurrence_id=oid,
        session_id="sess-1",
        session_title="Morning Squad",
        start_at=start,
        end_at=start + timedelta(hours=1),
        status="scheduled",
        coach_name=None,
    )


class _FakeParentUseCases:
    def __init__(self, entries: list[ChildScheduleEntry], owned_ids: set[str]) -> None:
        self._entries = entries
        self._owned_ids = owned_ids

    async def get_child_schedule(
        self,
        *,
        parent_id: str,
        student_id: str,
        frm,
        to,
        limit: int,
        offset: int,
    ) -> tuple[list[ChildScheduleEntry], int]:
        if student_id not in self._owned_ids:
            raise StudentNotOwnedByParent("not owned")
        total = len(self._entries)
        sliced = self._entries[offset : offset + limit]
        return sliced, total


@contextmanager
def _make_client(
    entries: list[ChildScheduleEntry] | None = None,
    owned_ids: set[str] | None = None,
    role: str = "parent",
    user_id: str = "parent-1",
) -> Iterator[TestClient]:
    if entries is None:
        entries = [_entry("occ-1", 1), _entry("occ-2", 2), _entry("occ-3", 3)]
    if owned_ids is None:
        owned_ids = {"student-1"}
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role, user_id)
    app.dependency_overrides[get_parent_use_cases] = lambda: _FakeParentUseCases(entries, owned_ids)
    with TestClient(app) as client:
        yield client


@contextmanager
def _anon_client() -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_parent_use_cases] = lambda: _FakeParentUseCases([], set())
    with TestClient(app) as client:
        yield client


def test_happy_path_returns_schedule() -> None:
    with _make_client() as client:
        response = client.get("/api/v2/parent/children/student-1/schedule")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert len(body["entries"]) == 3
    first = body["entries"][0]
    assert first["occurrence_id"] == "occ-1"
    assert first["session_id"] == "sess-1"
    assert first["session_title"] == "Morning Squad"
    assert first["status"] == "scheduled"
    assert first["coach_name"] is None


def test_pagination_limit_and_offset() -> None:
    entries = [_entry(f"occ-{i}", i) for i in range(10)]
    with _make_client(entries=entries) as client:
        response = client.get("/api/v2/parent/children/student-1/schedule?limit=3&offset=4")

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 3
    assert body["offset"] == 4
    assert len(body["entries"]) == 3
    assert body["entries"][0]["occurrence_id"] == "occ-4"


def test_non_owned_student_returns_404() -> None:
    with _make_client(owned_ids={"student-1"}) as client:
        response = client.get("/api/v2/parent/children/other-student/schedule")

    assert response.status_code == 404


def test_wrong_persona_returns_404() -> None:
    with _make_client(role="coach") as client:
        response = client.get("/api/v2/parent/children/student-1/schedule")
    assert response.status_code == 404


def test_anonymous_returns_401() -> None:
    with _anon_client() as client:
        response = client.get("/api/v2/parent/children/student-1/schedule")
    assert response.status_code == 401


def test_empty_schedule_returns_empty_list() -> None:
    with _make_client(entries=[]) as client:
        response = client.get("/api/v2/parent/children/student-1/schedule")

    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == []
    assert body["total"] == 0


def test_date_range_query_params_accepted() -> None:
    """from/to params are forwarded without error."""
    with _make_client() as client:
        response = client.get(
            "/api/v2/parent/children/student-1/schedule?from=2026-07-01&to=2026-07-31"
        )
    assert response.status_code == 200
