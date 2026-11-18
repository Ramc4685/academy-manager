"""Class recap BFF routes: persona guards, claims -> actor mapping, the owner
handoff list, and the parent's own-child-only view (no report text, other
children 404)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.coaching.application.use_cases.class_recap import (
    ChildClassRecap,
    ClassRecapState,
    RecapRosterEntry,
    SkillOption,
)
from backend.v2.contexts.coaching.domain.class_recap import ChildPractice, ClassRecap, ClassReport
from backend.v2.contexts.coaching.domain.errors import RecapWriteForbidden
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

NOW = datetime(2026, 11, 18, 20, 0, tzinfo=UTC)
WHEN = "2026-11-18T20:00:00Z"
RECAP_ROUTE = "/api/v2/coach/occurrences/occ-1/class-recap"
REPORT_ROUTE = "/api/v2/coach/occurrences/occ-1/class-reports"
HANDOFF_ROUTE = "/api/v2/admin/class-reports/handoffs"
SECRET = "Sam was upset after his parents argued at pickup."

RECAP = ClassRecap(
    recap_id="rc-1",
    academy_id="acad",
    occurrence_id="occ-1",
    session_id="sess-1",
    class_starts_at=NOW,
    taught_skill_ids=("skill-l1", "skill-l3"),
    practice=(
        ChildPractice(student_id="maya", skill_ids=("skill-l1",)),
        ChildPractice(student_id="leo", skill_ids=("skill-l3",)),
    ),
    revision=3,
    updated_by="coach-1",
    updated_at=NOW,
)
REPORT = ClassReport(
    report_id="r-1",
    academy_id="acad",
    occurrence_id="occ-1",
    class_starts_at=NOW,
    author_id="coach-1",
    text=SECRET,
    submitted_at=NOW,
    outcome="sent_to_owner",
)
CHILD_ROW = ChildClassRecap(
    occurrence_id="occ-1",
    class_starts_at=NOW,
    taught_skills=["Forehand grip", "Jump smash"],
    practiced_skills=["Forehand grip"],
    passed_skills=["Forehand grip"],
)


class Spy:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[tuple[Any, ...]] = []

    async def execute(self, *args: Any) -> Any:
        self.calls.append(args)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class GetSpy(Spy):
    async def execute(self, *args: Any) -> Any:
        self.calls.append(args)
        return ClassRecapState(
            occurrence_id="occ-1",
            class_starts_at=NOW,
            can_edit=args[1].is_owner,
            recap=RECAP,
            roster=[RecapRosterEntry(student_id="maya", name="Maya Lopez", attendance="present")],
            skill_options=[SkillOption(skill_id="skill-l1", name="Forehand grip", level_name="L1")],
            skill_names={"skill-l1": "Forehand grip", "skill-l3": "Jump smash"},
            reports=[REPORT],
        )


def _client(roles: tuple[str, ...], user_id: str = "coach-1", **recap: Any) -> TestClient:
    composition = SimpleNamespace(
        get=GetSpy(None),
        save=recap.get("save", Spy(RECAP)),
        submit_report=recap.get("submit", Spy(REPORT)),
        resolve_report=Spy(REPORT),
        list_handoffs=Spy([REPORT]),
        list_for_child=Spy([CHILD_ROW]),
        ai_enabled=True,
    )

    async def children(parent_id: str) -> list[dict[str, str]]:
        return [{"student_id": "maya"}] if parent_id == "parent-1" else []

    parent_use_cases = object.__new__(ParentUseCases)
    parent_use_cases.list_children_for_parent = children
    app = FastAPI()
    register_exception_handlers(app)
    for router in (coach_router, parent_router, admin_router):
        app.include_router(router, prefix="/api/v2")
    app.state.class_recap = composition
    app.dependency_overrides[get_parent_use_cases] = lambda: parent_use_cases
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id=user_id,
        email="x@example.com",
        academy_id="acad",
        roles=roles,  # type: ignore[arg-type]
    )
    client = TestClient(app)
    client.composition = composition  # type: ignore[attr-defined]
    return client


def test_owner_reads_split_practice_and_reports() -> None:
    client = _client(("admin", "owner"), user_id="owner-1")
    body = client.get(RECAP_ROUTE).json()
    actor = client.composition.get.calls[0][1]  # type: ignore[attr-defined]
    assert (actor.is_owner, actor.is_supervisor, actor.is_assistant_only) == (True, True, False)
    assert body["can_edit"] is True and body["can_resolve"] is True and body["revision"] == 3
    assert body["practice"] == [
        {"student_id": "maya", "skill_ids": ["skill-l1"]},
        {"student_id": "leo", "skill_ids": ["skill-l3"]},
    ]
    assert [s["name"] for s in body["taught_skills"]] == ["Forehand grip", "Jump smash"]
    assert body["reports"][0]["is_mine"] is False and body["reports"][0]["text"] == SECRET


def test_assistant_maps_to_an_assistant_only_actor_and_cannot_resolve() -> None:
    client = _client(("assistant_coach",), user_id="assist-1")
    body = client.get(RECAP_ROUTE).json()
    actor = client.composition.get.calls[0][1]  # type: ignore[attr-defined]
    assert actor.is_assistant_only and not actor.is_owner
    assert body["can_edit"] is False and body["can_resolve"] is False


def test_save_passes_per_child_practice_and_the_class_date() -> None:
    client = _client(("coach",))
    response = client.put(
        RECAP_ROUTE,
        json={
            "class_starts_at": WHEN,
            "mutation_id": "m-1",
            "expected_revision": 2,
            "taught_skill_ids": ["skill-l1", "skill-l3"],
            "practice": [
                {"student_id": "maya", "skill_ids": ["skill-l1"]},
                {"student_id": "leo", "skill_ids": ["skill-l3"]},
            ],
        },
    )
    assert response.status_code == 200, response.text
    cmd, actor = client.composition.save.calls[0]  # type: ignore[attr-defined]
    assert (cmd.occurrence_id, cmd.expected_revision, cmd.source) == ("occ-1", 2, "direct")
    assert cmd.class_starts_at == NOW
    assert [(p.student_id, p.skill_ids) for p in cmd.practice] == [
        ("maya", ("skill-l1",)),
        ("leo", ("skill-l3",)),
    ]
    assert actor.user_id == "coach-1"


def test_save_requires_the_class_date_and_non_empty_child_rows() -> None:
    client = _client(("coach",))
    no_date = {"mutation_id": "m-1", "expected_revision": 0}
    assert client.put(RECAP_ROUTE, json=no_date).status_code == 422
    empty_row = {
        **no_date,
        "class_starts_at": WHEN,
        "practice": [{"student_id": "maya", "skill_ids": []}],
    }
    assert client.put(RECAP_ROUTE, json=empty_row).status_code == 422


def test_write_refusal_keeps_its_code() -> None:
    client = _client(("coach",), save=Spy(RecapWriteForbidden("no")))
    body = {"class_starts_at": WHEN, "mutation_id": "m-1", "expected_revision": 0}
    response = client.put(RECAP_ROUTE, json=body)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "Coaching.RecapWriteForbidden"


def test_report_is_bounded_text_and_ai_is_opt_in() -> None:
    client = _client(("coach",))
    base = {"class_starts_at": WHEN, "report_id": "r-1"}
    assert client.post(REPORT_ROUTE, json={**base, "text": ""}).status_code == 422
    assert client.post(REPORT_ROUTE, json={**base, "text": "x" * 2001}).status_code == 422
    ok = client.post(REPORT_ROUTE, json={**base, "text": "grips"})
    assert ok.status_code == 200 and ok.json()["outcome"] == "sent_to_owner"
    cmd, _ = client.composition.submit_report.calls[0]  # type: ignore[attr-defined]
    assert cmd.use_ai is False


def test_resolve_route_passes_the_owner_actor() -> None:
    client = _client(("owner",), user_id="owner-1")
    response = client.post(f"{REPORT_ROUTE}/r-1/resolve")
    assert response.status_code == 200
    occurrence_id, report_id, actor = client.composition.resolve_report.calls[0]  # type: ignore[attr-defined]
    assert (occurrence_id, report_id, actor.is_owner) == ("occ-1", "r-1", True)


def test_handoff_list_is_owner_only() -> None:
    owner = _client(("admin", "owner"), user_id="owner-1").get(HANDOFF_ROUTE)
    assert owner.status_code == 200
    assert owner.json()["reports"][0]["occurrence_id"] == "occ-1"
    for roles in (("admin",), ("coach",), ("parent",)):
        assert _client(roles).get(HANDOFF_ROUTE).status_code == 404


def test_parent_and_student_personas_cannot_reach_coach_routes() -> None:
    for roles in (("parent",), ("student",)):
        assert _client(roles).get(RECAP_ROUTE).status_code == 404


def test_parent_sees_only_own_child_view_without_report_text() -> None:
    client = _client(("parent",), user_id="parent-1")
    response = client.get("/api/v2/parent/students/maya/class-recaps")
    assert response.status_code == 200
    assert response.json() == {
        "recaps": [
            {
                "occurrence_id": "occ-1",
                "class_starts_at": WHEN,
                "taught_skills": ["Forehand grip", "Jump smash"],
                "practiced_skills": ["Forehand grip"],
                "passed_skills": ["Forehand grip"],
            }
        ]
    }
    assert SECRET not in response.text and "leo" not in response.text
    assert client.get("/api/v2/parent/students/leo/class-recaps").status_code == 404
    assert client.composition.list_for_child.calls == [("maya",)]  # type: ignore[attr-defined]


def test_coach_cannot_use_the_parent_route() -> None:
    assert _client(("coach",)).get("/api/v2/parent/students/maya/class-recaps").status_code == 404
