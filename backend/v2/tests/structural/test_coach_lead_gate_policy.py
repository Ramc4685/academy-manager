"""Every coach BFF route is behind exactly one of the two coach guards.

``require_coach_surface`` admits coaches, supervisors AND assistant coaches;
``require_coach_lead_surface`` refuses a bare ``assistant_coach``. The set of
lead-only routes is the contract the frontend hides for assistants, so it is
pinned here in both directions: a new coach route must pick a guard, and a
route cannot silently move across the line.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.tests.structural.test_owner_gate_policy import _dependant_calls, _iter_routes

_PREFIX = "/api/v2/coach"

LEAD_ONLY_COACH_ROUTE_PATHS: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", f"{_PREFIX}/sessions/{{session_id}}/lesson-plans"),
        ("POST", f"{_PREFIX}/sessions/{{session_id}}/roster"),
        ("DELETE", f"{_PREFIX}/sessions/{{session_id}}/roster/{{student_id}}"),
        ("GET", f"{_PREFIX}/billing-enrollments"),
        ("GET", f"{_PREFIX}/billing-enrollments/{{enrollment_id}}/move/preview"),
        ("POST", f"{_PREFIX}/billing-enrollments/{{enrollment_id}}/move"),
        ("GET", f"{_PREFIX}/messages"),
        ("POST", f"{_PREFIX}/messages/{{message_id}}/read"),
        ("GET", f"{_PREFIX}/sessions/{{session_id}}/announcements"),
        ("POST", f"{_PREFIX}/sessions/{{session_id}}/announcements"),
        ("DELETE", f"{_PREFIX}/sessions/{{session_id}}/announcements/{{message_id}}"),
        ("POST", f"{_PREFIX}/sessions/{{session_id}}/feedback"),
        ("GET", f"{_PREFIX}/sessions/{{session_id}}/feedback"),
    }
)


def _guards(route: Any) -> set[str]:
    found: set[str] = set()
    for call in _dependant_calls(route.dependant):
        name = getattr(call, "__qualname__", "")
        if "require_coach_lead_surface" in name:
            found.add("lead")
        elif "require_coach_surface" in name:
            found.add("surface")
        elif "require_persona" in name or "require_owner" in name:
            found.add("other")
    return found


def _coach_routes() -> dict[tuple[str, str], Any]:
    app = FastAPI()
    app.include_router(coach_router, prefix="/api/v2")
    routes: dict[tuple[str, str], Any] = {}
    for path, route in _iter_routes(app.routes):
        if not path.startswith(_PREFIX) or not hasattr(route, "dependant"):
            continue
        for method in getattr(route, "methods", None) or ():
            if method != "HEAD":
                routes[(method, path)] = route
    return routes


def test_every_coach_route_has_exactly_one_coach_guard() -> None:
    bad = {key: sorted(_guards(route)) for key, route in _coach_routes().items()}
    bad = {key: guards for key, guards in bad.items() if guards not in (["lead"], ["surface"])}
    assert not bad, f"coach routes without exactly one coach guard: {bad}"


def test_lead_only_routes_are_exactly_the_declared_set() -> None:
    lead = {key for key, route in _coach_routes().items() if "lead" in _guards(route)}
    assert lead == set(LEAD_ONLY_COACH_ROUTE_PATHS)


def test_attendance_skills_and_notes_stay_open_to_assistants() -> None:
    registered = _coach_routes()
    for key in [
        ("POST", f"{_PREFIX}/attendance"),
        ("POST", f"{_PREFIX}/occurrences/{{occurrence_id}}/attendance/bulk"),
        ("PATCH", f"{_PREFIX}/occurrences/{{occurrence_id}}/attendance/{{student_id}}"),
        ("POST", f"{_PREFIX}/students/{{student_id}}/skills/{{skill_id}}/status"),
        ("POST", f"{_PREFIX}/sessions/{{session_id}}/progress-notes"),
        ("GET", f"{_PREFIX}/today"),
        ("GET", f"{_PREFIX}/sessions/{{session_id}}/roster"),
    ]:
        assert key in registered, key
        assert _guards(registered[key]) == {"surface"}, key
