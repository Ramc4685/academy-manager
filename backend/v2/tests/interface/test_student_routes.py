"""Interface tests for the student BFF (UIM12).

Covers: claims -> student_id resolution, the flag-off 404 (no
`app.state.student`), wrong-persona 404 in both directions (a parent token
cannot hit `/student/*` and a student token cannot hit `/parent/*`), and
that `/student/schedule` reuses `get_child_schedule` exactly the way the
parent route does.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.application.use_cases.get_child_schedule import (
    ChildScheduleEntry,
    StudentNotOwnedByParent,
)
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.interfaces.student.deps import ResolvedStudent, StudentUseCases
from backend.v2.interfaces.student.router import router as student_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

_RESOLVED = ResolvedStudent(
    student_id="student-1",
    parent_id="parent-1",
    academy_id="acad",
    full_name="Alex Chen",
)


def _claims(role: str, user_id: str = "user-1") -> AuthClaims:
    return AuthClaims(
        user_id=user_id,
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


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


class _FakeGetChildSchedule:
    """Stands in for the shared `GetChildSchedule` use case instance.

    Records the `parent_id` it was called with so tests can assert the
    student route passes the resolved student's own `parent_id` — the same
    ownership check the parent BFF relies on — rather than bypassing it.
    """

    def __init__(self, entries: list[ChildScheduleEntry], owned_parent_id: str) -> None:
        self._entries = entries
        self._owned_parent_id = owned_parent_id
        self.calls: list[dict[str, object]] = []

    async def __call__(
        self, *, parent_id: str, student_id: str, frm, to, limit: int, offset: int
    ) -> tuple[list[ChildScheduleEntry], int]:
        self.calls.append({"parent_id": parent_id, "student_id": student_id})
        if parent_id != self._owned_parent_id:
            raise StudentNotOwnedByParent("not owned")
        total = len(self._entries)
        return self._entries[offset : offset + limit], total


def _resolver(resolved: ResolvedStudent | None):
    async def _resolve(user_id: str) -> ResolvedStudent | None:
        return resolved

    return _resolve


def _use_cases(
    *,
    entries: list[ChildScheduleEntry] | None = None,
    resolved: ResolvedStudent | None = _RESOLVED,
) -> tuple[StudentUseCases, _FakeGetChildSchedule]:
    if entries is None:
        entries = [_entry("occ-1", 1), _entry("occ-2", 2)]
    schedule_fn = _FakeGetChildSchedule(entries, owned_parent_id=_RESOLVED.parent_id)

    async def get_academy_info(**_: object) -> dict[str, object]:
        return {"display_name": "Test Academy"}

    use_cases = StudentUseCases(
        resolve_student=_resolver(resolved),
        get_child_schedule=schedule_fn,
        student_progress=None,
        curriculum=None,
        get_academy_info=get_academy_info,
    )
    return use_cases, schedule_fn


@contextmanager
def _make_client(
    *,
    role: str = "student",
    user_id: str = "user-1",
    resolved: ResolvedStudent | None = _RESOLVED,
    entries: list[ChildScheduleEntry] | None = None,
    flag_on: bool = True,
    include_parent: bool = False,
) -> Iterator[tuple[TestClient, _FakeGetChildSchedule]]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(student_router, prefix="/api/v2")
    if include_parent:
        app.include_router(parent_router, prefix="/api/v2")
        app.dependency_overrides[get_parent_use_cases] = lambda: None
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role, user_id)

    use_cases, schedule_fn = _use_cases(entries=entries, resolved=resolved)
    if flag_on:
        app.state.student = use_cases
    # flag_on=False: app.state.student is left unset entirely, mirroring
    # main.py only wiring it when settings.enable_student_login is True.
    with TestClient(app) as client:
        yield client, schedule_fn


def test_student_schedule_resolves_student_id_from_claims_and_reuses_get_child_schedule() -> None:
    with _make_client() as (client, schedule_fn):
        response = client.get("/api/v2/student/schedule")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["entries"]) == 2
    # The claims-resolved student_id and parent_id are what get_child_schedule
    # is called with — never a client-supplied id (there is no student_id
    # param on this route at all).
    assert schedule_fn.calls == [{"parent_id": "parent-1", "student_id": "student-1"}]


def test_student_flag_off_returns_404() -> None:
    with _make_client(flag_on=False) as (client, _):
        response = client.get("/api/v2/student/schedule")
    assert response.status_code == 404


def test_wrong_persona_parent_cannot_hit_student_routes() -> None:
    with _make_client(role="parent") as (client, _):
        response = client.get("/api/v2/student/schedule")
    assert response.status_code == 404


def test_student_cannot_hit_parent_routes() -> None:
    with _make_client(role="student", include_parent=True) as (client, _):
        response = client.get("/api/v2/parent/children/student-1/schedule")
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("router_factory", "path"),
    [
        ("coach", "/api/v2/coach/today"),
        ("admin", "/api/v2/admin/students"),
    ],
)
def test_student_token_cannot_reach_other_persona_surfaces(router_factory, path) -> None:
    """A student token is the lowest-privilege persona in the system — it
    must not reach coach or admin routes any more than it reaches parent
    ones. 404 (not 403) per the security matrix."""
    if router_factory == "coach":
        from backend.v2.interfaces.coach.router import router as other_router
    else:
        from backend.v2.interfaces.admin.router import router as other_router

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(other_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims("student")
    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 404


def test_broken_link_returns_404_even_with_student_role() -> None:
    """A `student` membership with no (or a since-cleared) student_user_id
    link resolves to None — 404, not a 500 or someone else's data."""
    with _make_client(resolved=None) as (client, _):
        response = client.get("/api/v2/student/schedule")
    assert response.status_code == 404


def test_anonymous_returns_401() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(student_router, prefix="/api/v2")
    use_cases, _ = _use_cases()
    app.state.student = use_cases
    with TestClient(app) as client:
        response = client.get("/api/v2/student/schedule")
    assert response.status_code == 401


def test_student_me_returns_profile() -> None:
    with _make_client() as (client, _):
        response = client.get("/api/v2/student/me")
    assert response.status_code == 200
    body = response.json()
    assert body["student_id"] == "student-1"
    assert body["full_name"] == "Alex Chen"
    assert body["academy_name"] == "Test Academy"
