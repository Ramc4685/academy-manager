"""Interface tests for the coach teaching-plan routes.

Real coach router + a real GenerateDailyTeachingPlan wired with in-memory
fakes. Covers response shape, auth (401 anon / 404 wrong persona / 404
unassigned session), empty day, no-pathway degradation, and 503 when the
teaching-plan composition is absent.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.v2.contexts.coaching.application.use_cases.generate_daily_teaching_plan import (
    GenerateDailyTeachingPlan,
)
from backend.v2.contexts.student_progress.application.use_cases.get_teaching_focus import (
    GetTeachingFocus,
)
from backend.v2.contexts.student_progress.domain.models import StudentLevelProgress
from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.tenancy import tenant_scope

ACADEMY_ID = "test-academy"
COACH_ID = "coach-001"
STUDENT_ID = "student-001"
PROGRAM_ID = "prog-001"
PROGRAM_NAME = "Badminton Skill Pathway"
LEVEL_1 = "level-001"
SESSION_ID = "session-001"
NOW = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeLevelProgressRepo:
    def __init__(self, rows: list[StudentLevelProgress]) -> None:
        self._rows = rows

    async def get_active(self, student_id: str, program_id: str) -> StudentLevelProgress | None:
        for row in self._rows:
            if row.student_id == student_id and row.program_id == program_id:
                return row
        return None


class _FakeSkillProgressRepo:
    async def list_for_students(self, student_ids: list[str], level_id: str) -> list[object]:
        return []


class _FakeSkillLookup:
    def __init__(self) -> None:
        self._levels = {
            LEVEL_1: SimpleNamespace(level_id=LEVEL_1, name="Grip and Control", sequence=1),
        }
        self._skills = {
            LEVEL_1: [
                SimpleNamespace(
                    skill_id="sk-a", name="Forehand grip", sequence=1, is_required=True
                ),
            ],
        }

    async def get_level(self, level_id: str) -> object | None:
        return self._levels.get(level_id)

    async def list_skills_for_level(self, level_id: str) -> list[object]:
        return self._skills.get(level_id, [])


class _FakeOccurrences:
    def __init__(self, occurrences: list[object]) -> None:
        self._occurrences = occurrences

    async def execute(self, coach_id: str, on_date: date) -> list[object]:
        return list(self._occurrences)


class _FakeRoster:
    async def execute(self, session_id: str) -> list[object]:
        return [SimpleNamespace(student_id=STUDENT_ID, full_name="Alice", status="active")]


class _FakeLessonCards:
    async def list_for_program(self, program_id: str) -> list[object]:
        return [
            SimpleNamespace(
                card_id="card-1",
                program_id=PROGRAM_ID,
                level_id=LEVEL_1,
                skill_ids=["sk-a"],
                lesson_number=1,
                title="Lesson 1",
                goal_summary="Grip",
                teaching_points=["Hold V"],
                equipment=["Racket"],
                activity_summary="Drill",
                safety_notes=["Spaced"],
                source="BWF_SHUTTLE_TIME",
                module_name="Starter Lessons",
                lesson_range="1-2",
                page_hint="p.9-15",
                resource_links=[
                    SimpleNamespace(kind="PDF_REFERENCE", title="Shuttle Time", url=None)
                ],
                display_order=1,
                is_active=True,
            )
        ]


class _FakeVideoRefs:
    async def list_for_level(self, level_id: str) -> list[object]:
        return [SimpleNamespace(skill_id=None, level_id=level_id, title="L1", url="https://yt/l")]

    async def list_for_skills(self, skill_ids: list[str]) -> list[object]:
        return [
            SimpleNamespace(skill_id=sid, level_id=LEVEL_1, title="drill", url=f"https://yt/{sid}")
            for sid in skill_ids
        ]


class _FakeCriteria:
    async def list_for_skill(self, skill_id: str) -> list[object]:
        return [SimpleNamespace(description="Relaxed wrist")]


class _AssignedSessions:
    def __init__(self, assigned: set[str]) -> None:
        self._assigned = assigned

    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool:
        return coach_id == COACH_ID and session_id in self._assigned


def _occurrence() -> SimpleNamespace:
    return SimpleNamespace(
        occurrence_id="occ-1",
        session_id=SESSION_ID,
        title="U11 Beginners",
        location="Court 2",
        start_at=NOW,
        end_at=NOW,
    )


def _make_plan_use_case(*, occurrences: list[object]) -> GenerateDailyTeachingPlan:
    teaching_focus = GetTeachingFocus(
        level_progress=_FakeLevelProgressRepo(
            [
                StudentLevelProgress(
                    progress_id="lp-1",
                    academy_id=ACADEMY_ID,
                    student_id=STUDENT_ID,
                    program_id=PROGRAM_ID,
                    level_id=LEVEL_1,
                    status="active",
                    started_at=NOW,
                    created_at=NOW,
                )
            ]
        ),
        skill_progress=_FakeSkillProgressRepo(),
        skill_lookup=_FakeSkillLookup(),
    )
    return GenerateDailyTeachingPlan(
        occurrences=_FakeOccurrences(occurrences),
        get_roster=_FakeRoster(),
        teaching_focus=teaching_focus,
        lesson_cards=_FakeLessonCards(),
        video_refs=_FakeVideoRefs(),
        criteria=_FakeCriteria(),
    )


def _curriculum(*, program_resolves: bool = True) -> SimpleNamespace:
    program = SimpleNamespace(program_id=PROGRAM_ID, name=PROGRAM_NAME)

    async def resolve_default() -> object:
        if not program_resolves:
            raise RuntimeError("no active program")
        return program

    async def get_program(program_id: str) -> object:
        return program

    return SimpleNamespace(
        resolve_default_program=SimpleNamespace(execute=resolve_default),
        get_program=SimpleNamespace(execute=get_program),
    )


def _coach_use_cases(
    *,
    occurrences: list[object],
    assigned: set[str],
    with_plan: bool = True,
    program_resolves: bool = True,
) -> CoachUseCases:
    use_cases = CoachUseCases(
        list_today=AsyncMock(),  # type: ignore[arg-type]
        get_roster=AsyncMock(),  # type: ignore[arg-type]
        mark_attendance=AsyncMock(),  # type: ignore[arg-type]
        bulk_mark_attendance=AsyncMock(),  # type: ignore[arg-type]
        get_dashboard_metrics=AsyncMock(),  # type: ignore[arg-type]
        create_lesson_plan=AsyncMock(),  # type: ignore[arg-type]
        list_lesson_plans=AsyncMock(),  # type: ignore[arg-type]
        create_progress_note=AsyncMock(),  # type: ignore[arg-type]
        list_progress_notes=AsyncMock(),  # type: ignore[arg-type]
        assigned_sessions=_AssignedSessions(assigned),  # type: ignore[arg-type]
        add_student_to_roster=AsyncMock(),  # type: ignore[arg-type]
        remove_student_from_roster=AsyncMock(),  # type: ignore[arg-type]
        create_feedback=AsyncMock(),  # type: ignore[arg-type]
        list_feedback=AsyncMock(),  # type: ignore[arg-type]
        list_billing_enrollments=AsyncMock(),  # type: ignore[arg-type]
        preview_student_session_type_move=AsyncMock(),  # type: ignore[arg-type]
        move_student_session_type=AsyncMock(),  # type: ignore[arg-type]
        list_session_types=AsyncMock(),  # type: ignore[arg-type]
        get_billing_enrollment=AsyncMock(),
        get_active_session_enrollments_for_student=AsyncMock(),
        list_all_sessions=AsyncMock(),
        get_profile=AsyncMock(),
        update_profile=AsyncMock(),
    )
    use_cases.curriculum = _curriculum(program_resolves=program_resolves)  # type: ignore[assignment]
    if with_plan:
        use_cases.generate_daily_teaching_plan = _make_plan_use_case(occurrences=occurrences)
    return use_cases


def _build_app(
    *,
    occurrences: list[object] | None = None,
    assigned: set[str] | None = None,
    persona: str = "coach",
    authenticated: bool = True,
    with_plan: bool = True,
    program_resolves: bool = True,
) -> FastAPI:
    use_cases = _coach_use_cases(
        occurrences=occurrences if occurrences is not None else [_occurrence()],
        assigned=assigned if assigned is not None else {SESSION_ID},
        with_plan=with_plan,
        program_resolves=program_resolves,
    )

    app = FastAPI()
    app.include_router(coach_router, prefix="/api/v2")

    if authenticated:
        app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
            user_id=COACH_ID,
            email="coach@example.com",
            academy_id=ACADEMY_ID,
            roles=(persona,),
        )
    app.dependency_overrides[get_coach_use_cases] = lambda: use_cases

    @app.middleware("http")
    async def _tenant_ctx(request: Request, call_next):
        with tenant_scope(ACADEMY_ID):
            return await call_next(request)

    return app


# ---------------------------------------------------------------------------
# /today/plan
# ---------------------------------------------------------------------------


def test_today_plan_returns_shape() -> None:
    client = TestClient(_build_app())
    resp = client.get(f"/api/v2/coach/today/plan?date=2026-06-11&program_id={PROGRAM_ID}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["date"] == "2026-06-11"
    assert body["pathway_configured"] is True
    assert body["program_id"] == PROGRAM_ID
    assert len(body["sessions"]) == 1
    session = body["sessions"][0]
    assert session["session_id"] == SESSION_ID
    group = session["groups"][0]
    assert {
        "level_id",
        "level_name",
        "level_sequence",
        "youtube_links",
        "lesson_card",
        "students",
    } <= set(group)
    assert group["lesson_card"]["lesson_number"] == 1
    student = group["students"][0]
    assert student["focus"] == "practice"
    assert student["next_skill"]["skill_id"] == "sk-a"
    assert student["next_skill"]["criteria"] == ["Relaxed wrist"]


def test_today_plan_anonymous_returns_401() -> None:
    client = TestClient(_build_app(authenticated=False))
    resp = client.get("/api/v2/coach/today/plan")
    assert resp.status_code == 401, resp.text


def test_today_plan_wrong_persona_returns_404() -> None:
    client = TestClient(_build_app(persona="parent"))
    resp = client.get("/api/v2/coach/today/plan")
    assert resp.status_code == 404, resp.text


def test_today_plan_empty_day_returns_no_sessions() -> None:
    client = TestClient(_build_app(occurrences=[]))
    resp = client.get(f"/api/v2/coach/today/plan?program_id={PROGRAM_ID}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["sessions"] == []


def test_today_plan_no_pathway_marks_unconfigured() -> None:
    client = TestClient(_build_app(program_resolves=False))
    resp = client.get("/api/v2/coach/today/plan")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pathway_configured"] is False
    # Roster student becomes unplaced when no program is configured.
    assert [u["student_id"] for u in body["sessions"][0]["unplaced"]] == [STUDENT_ID]


def test_today_plan_503_when_composition_missing() -> None:
    client = TestClient(_build_app(with_plan=False))
    resp = client.get("/api/v2/coach/today/plan")
    assert resp.status_code == 503, resp.text


# ---------------------------------------------------------------------------
# /sessions/{id}/teaching-plan
# ---------------------------------------------------------------------------


def test_session_teaching_plan_returns_groups() -> None:
    client = TestClient(_build_app())
    resp = client.get(f"/api/v2/coach/sessions/{SESSION_ID}/teaching-plan?program_id={PROGRAM_ID}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == SESSION_ID
    assert body["pathway_configured"] is True
    assert body["groups"][0]["students"][0]["next_skill"]["skill_id"] == "sk-a"


def test_session_teaching_plan_unassigned_returns_404() -> None:
    client = TestClient(_build_app(assigned=set()))
    resp = client.get(f"/api/v2/coach/sessions/{SESSION_ID}/teaching-plan")
    assert resp.status_code == 404, resp.text


def test_session_teaching_plan_wrong_persona_returns_404() -> None:
    client = TestClient(_build_app(persona="parent"))
    resp = client.get(f"/api/v2/coach/sessions/{SESSION_ID}/teaching-plan")
    assert resp.status_code == 404, resp.text


def test_session_teaching_plan_503_when_composition_missing() -> None:
    client = TestClient(_build_app(with_plan=False))
    resp = client.get(f"/api/v2/coach/sessions/{SESSION_ID}/teaching-plan")
    assert resp.status_code == 503, resp.text
