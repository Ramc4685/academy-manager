"""Interface tests for coach skill/progress routes.

Uses a standalone mini FastAPI app with fake in-memory repos.
No Mongo, no real auth.

Routes covered:
- GET  /api/v2/coach/students/{id}/passport          → 200
- POST /api/v2/coach/students/{id}/skills/{skillId}/status → 200
- POST /api/v2/coach/students/{id}/skills/{skillId}/test   → 201
  - if passes threshold, skill_status == "PASSED"
- POST /api/v2/coach/students/{id}/level-up               → 201
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.domain.models import RosterEntry
from backend.v2.contexts.student_progress.application.errors import StudentNotPlaced
from backend.v2.contexts.student_progress.application.use_cases.get_progress_summary import (
    ProgressSummaryRequest,
)
from backend.v2.contexts.student_progress.application.use_cases.get_skill_board import (
    GetSkillBoard,
)
from backend.v2.contexts.student_progress.application.use_cases.get_student_progress import (
    GetStudentPassport,
)
from backend.v2.contexts.student_progress.application.use_cases.recommend_level_up import (
    RecommendLevelUp,
    RecommendLevelUpCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.record_test_attempt import (
    RecordTestAttempt,
    RecordTestAttemptCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.update_skill_status import (
    UpdateSkillStatus,
    UpdateSkillStatusCommand,
)
from backend.v2.contexts.student_progress.domain.models import (
    LevelUpRecommendation,
    StudentLevelProgress,
    StudentProgressOverview,
    StudentSkillProgress,
    TestAttempt,
)
from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import tenant_scope

# ---------------------------------------------------------------------------
# Fake repos
# ---------------------------------------------------------------------------

ACADEMY_ID = "test-academy"
STUDENT_ID = "student-001"
PROGRAM_ID = "prog-001"
LEVEL_ID = "level-001"
SKILL_ID = "skill-001"
SKILL_ID_2 = "skill-002"
COACH_ID = "coach-001"
SESSION_ID = "session-001"


class _FakeLevelProgressRepo:
    def __init__(self) -> None:
        self._store: dict[str, StudentLevelProgress] = {}

    async def save(self, progress: StudentLevelProgress) -> None:
        self._store[progress.progress_id] = progress

    async def get_active(self, student_id: str, program_id: str) -> StudentLevelProgress | None:
        for p in self._store.values():
            if p.student_id == student_id and p.program_id == program_id and p.status == "active":
                return p
        return None

    async def get_by_id(self, progress_id: str) -> StudentLevelProgress | None:
        return self._store.get(progress_id)

    async def complete(self, progress_id: str, completed_at: object) -> None:
        p = self._store.get(progress_id)
        if p:
            self._store[progress_id] = p.model_copy(
                update={"status": "completed", "completed_at": completed_at}
            )

    async def list_for_student(self, student_id: str) -> list[StudentLevelProgress]:
        return [p for p in self._store.values() if p.student_id == student_id]


class _FakeSkillProgressRepo:
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], StudentSkillProgress] = {}

    async def save(self, skill_progress: StudentSkillProgress) -> None:
        self._store[(skill_progress.student_id, skill_progress.skill_id)] = skill_progress

    async def upsert(self, skill_progress: StudentSkillProgress) -> StudentSkillProgress:
        self._store[(skill_progress.student_id, skill_progress.skill_id)] = skill_progress
        return skill_progress

    async def get(self, student_id: str, skill_id: str) -> StudentSkillProgress | None:
        return self._store.get((student_id, skill_id))

    async def list_for_student_level(
        self, student_id: str, level_id: str
    ) -> list[StudentSkillProgress]:
        return [
            sp
            for sp in self._store.values()
            if sp.student_id == student_id and sp.level_id == level_id
        ]

    async def list_passed_for_student_level(
        self, student_id: str, level_id: str
    ) -> list[StudentSkillProgress]:
        return [
            sp
            for sp in self._store.values()
            if sp.student_id == student_id and sp.level_id == level_id and sp.status == "PASSED"
        ]


class _FakeTestAttemptRepo:
    def __init__(self) -> None:
        self._store: list[TestAttempt] = []

    async def save(self, attempt: TestAttempt) -> None:
        self._store.append(attempt)

    async def list_for_student_skill(self, student_id: str, skill_id: str) -> list[TestAttempt]:
        return [a for a in self._store if a.student_id == student_id and a.skill_id == skill_id]

    async def count_for_student_skill(self, student_id: str, skill_id: str) -> int:
        return len(await self.list_for_student_skill(student_id, skill_id))


class _FakeLevelUpRepo:
    def __init__(self) -> None:
        self._store: dict[str, LevelUpRecommendation] = {}

    async def save(self, rec: LevelUpRecommendation) -> None:
        self._store[rec.rec_id] = rec

    async def update_status(
        self,
        rec_id: str,
        status: str,
        reviewed_by: str | None,
        reviewed_at: object | None,
        rejection_reason: str | None,
        *,
        expected_status: str,
    ) -> bool:
        r = self._store.get(rec_id)
        if r is None or r.status != expected_status:
            return False
        self._store[rec_id] = r.model_copy(
            update={
                "status": status,
                "reviewed_by": reviewed_by,
                "reviewed_at": reviewed_at,
                "rejection_reason": rejection_reason,
            }
        )
        return True

    async def get(self, rec_id: str) -> LevelUpRecommendation | None:
        return self._store.get(rec_id)

    async def get_active_for_student(
        self, student_id: str, program_id: str
    ) -> LevelUpRecommendation | None:
        for r in self._store.values():
            if (
                r.student_id == student_id
                and r.program_id == program_id
                and r.status in ("RECOMMENDED", "APPROVED")
            ):
                return r
        return None

    async def list_pending(self) -> list[LevelUpRecommendation]:
        return [r for r in self._store.values() if r.status == "RECOMMENDED"]


class _FakeSkillLookup:
    """Returns minimal Skill-like objects for the use cases."""

    def __init__(self, skills: list[object], levels: list[object]) -> None:
        self._skills = {s.skill_id: s for s in skills}
        self._levels = {lv.level_id: lv for lv in levels}

    async def get_skill(self, skill_id: str) -> object | None:
        return self._skills.get(skill_id)

    async def get_level(self, level_id: str) -> object | None:
        return self._levels.get(level_id)

    async def list_skills_for_level(self, level_id: str) -> list[object]:
        return [s for s in self._skills.values() if s.level_id == level_id]

    async def get_next_level(self, program_id: str, current_sequence: int) -> object | None:
        for lv in self._levels.values():
            if lv.program_id == program_id and lv.sequence == current_sequence + 1:
                return lv
        return None


# ---------------------------------------------------------------------------
# Minimal skill/level stub objects
# ---------------------------------------------------------------------------


class _SkillStub:
    def __init__(
        self,
        skill_id: str,
        level_id: str,
        *,
        is_required: bool = True,
        pass_threshold_pct: float = 70.0,
        coach_override_allowed: bool = False,
    ) -> None:
        self.skill_id = skill_id
        self.level_id = level_id
        self.name = f"Skill {skill_id}"
        self.description = "A test skill"
        self.sequence = 1
        self.is_required = is_required
        self.pass_threshold_pct = pass_threshold_pct
        self.coach_override_allowed = coach_override_allowed


class _LevelStub:
    def __init__(self, level_id: str, program_id: str, sequence: int = 1) -> None:
        self.level_id = level_id
        self.program_id = program_id
        self.sequence = sequence
        self.name = f"Level {sequence}"


# ---------------------------------------------------------------------------
# App factory — seeds an active level for STUDENT_ID
# ---------------------------------------------------------------------------


def _build_coach_app() -> FastAPI:
    level_progress_repo = _FakeLevelProgressRepo()
    skill_progress_repo = _FakeSkillProgressRepo()
    test_attempt_repo = _FakeTestAttemptRepo()
    level_up_repo = _FakeLevelUpRepo()

    skill_stubs = [
        _SkillStub(SKILL_ID, LEVEL_ID),
        _SkillStub(SKILL_ID_2, LEVEL_ID),
    ]
    level_stubs = [
        _LevelStub(LEVEL_ID, PROGRAM_ID, sequence=1),
        _LevelStub("level-002", PROGRAM_ID, sequence=2),
    ]
    skill_lookup = _FakeSkillLookup(skill_stubs, level_stubs)

    # Seed active level for STUDENT_ID
    import asyncio

    now = datetime.now(UTC)
    active_level = StudentLevelProgress(
        progress_id=str(new_ulid()),
        academy_id=ACADEMY_ID,
        student_id=STUDENT_ID,
        program_id=PROGRAM_ID,
        level_id=LEVEL_ID,
        status="active",
        started_at=now,
        completed_at=None,
        created_at=now,
    )
    asyncio.get_event_loop().run_until_complete(level_progress_repo.save(active_level))

    # Use cases
    get_passport = GetStudentPassport(
        level_progress=level_progress_repo,
        skill_progress=skill_progress_repo,
        skill_lookup=skill_lookup,
        test_attempts=test_attempt_repo,
    )
    update_status = UpdateSkillStatus(
        level_progress=level_progress_repo,
        skill_progress=skill_progress_repo,
    )
    record_test_uc = RecordTestAttempt(
        level_progress=level_progress_repo,
        skill_progress=skill_progress_repo,
        test_attempts=test_attempt_repo,
        skill_lookup=skill_lookup,
    )
    recommend_level_up = RecommendLevelUp(
        level_progress=level_progress_repo,
        skill_progress=skill_progress_repo,
        recommendations=level_up_repo,
        skill_lookup=skill_lookup,
    )

    app = FastAPI()

    @app.middleware("http")
    async def _tenant_ctx(request: Request, call_next):
        with tenant_scope(ACADEMY_ID):
            return await call_next(request)

    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id=COACH_ID,
        email="coach@example.com",
        academy_id=ACADEMY_ID,
        roles=("coach",),
    )

    @app.get("/api/v2/coach/students/{student_id}/passport")
    async def passport(student_id: str, program_id: str = PROGRAM_ID) -> dict:
        entries = await get_passport.execute(student_id, program_id)
        return {"passport": [e.model_dump(mode="json") for e in entries]}

    @app.post("/api/v2/coach/students/{student_id}/skills/{skill_id}/status")
    async def set_status(student_id: str, skill_id: str, body: dict) -> dict:
        cmd = UpdateSkillStatusCommand(
            student_id=student_id,
            skill_id=skill_id,
            level_id=body.get("level_id", LEVEL_ID),
            program_id=body.get("program_id", PROGRAM_ID),
            new_status=body["new_status"],
            updated_by=COACH_ID,
        )
        result = await update_status.execute(cmd)
        return result.model_dump(mode="json")

    @app.post("/api/v2/coach/students/{student_id}/skills/{skill_id}/test", status_code=201)
    async def record_test(student_id: str, skill_id: str, body: dict) -> dict:
        cmd = RecordTestAttemptCommand(
            student_id=student_id,
            skill_id=skill_id,
            level_id=body.get("level_id", LEVEL_ID),
            program_id=body.get("program_id", PROGRAM_ID),
            coach_id=COACH_ID,
            attempts_count=body["attempts_count"],
            success_count=body["success_count"],
        )
        result = await record_test_uc.execute(cmd)
        return result.model_dump(mode="json")

    @app.post("/api/v2/coach/students/{student_id}/level-up", status_code=201)
    async def level_up(student_id: str, body: dict) -> dict:
        cmd = RecommendLevelUpCommand(
            student_id=student_id,
            program_id=body.get("program_id", PROGRAM_ID),
            recommended_by=COACH_ID,
        )
        rec = await recommend_level_up.execute(cmd)
        return rec.model_dump(mode="json")

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_passport_returns_200():
    app = _build_coach_app()
    client = TestClient(app)
    r = client.get(f"/api/v2/coach/students/{STUDENT_ID}/passport")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "passport" in body
    # Two skills seeded for the level
    assert len(body["passport"]) == 2


def test_get_passport_student_with_no_active_level_returns_empty():
    app = _build_coach_app()
    client = TestClient(app)
    r = client.get("/api/v2/coach/students/unknown-student/passport")
    assert r.status_code == 200, r.text
    assert r.json()["passport"] == []


def test_set_skill_status_returns_200():
    app = _build_coach_app()
    client = TestClient(app)
    r = client.post(
        f"/api/v2/coach/students/{STUDENT_ID}/skills/{SKILL_ID}/status",
        json={
            "new_status": "PRACTICING",
            "level_id": LEVEL_ID,
            "program_id": PROGRAM_ID,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "PRACTICING"
    assert body["student_id"] == STUDENT_ID
    assert body["skill_id"] == SKILL_ID


def test_record_test_passing_score_sets_passed_status():
    app = _build_coach_app()
    client = TestClient(app)
    # 8/10 = 80% → above 70% threshold → PASSED
    r = client.post(
        f"/api/v2/coach/students/{STUDENT_ID}/skills/{SKILL_ID}/test",
        json={
            "attempts_count": 10,
            "success_count": 8,
            "level_id": LEVEL_ID,
            "program_id": PROGRAM_ID,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["passed"] is True
    assert body["skill_status"] == "PASSED"


def test_record_test_failing_score_sets_needs_review():
    app = _build_coach_app()
    client = TestClient(app)
    # 5/10 = 50% → below 70% threshold → NEEDS_REVIEW
    r = client.post(
        f"/api/v2/coach/students/{STUDENT_ID}/skills/{SKILL_ID}/test",
        json={
            "attempts_count": 10,
            "success_count": 5,
            "level_id": LEVEL_ID,
            "program_id": PROGRAM_ID,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["passed"] is False
    assert body["skill_status"] == "NEEDS_REVIEW"


def test_record_test_level_completed_when_all_skills_pass():
    app = _build_coach_app()
    client = TestClient(app)
    # Pass both required skills
    for skill_id in (SKILL_ID, SKILL_ID_2):
        client.post(
            f"/api/v2/coach/students/{STUDENT_ID}/skills/{skill_id}/test",
            json={
                "attempts_count": 10,
                "success_count": 8,
                "level_id": LEVEL_ID,
                "program_id": PROGRAM_ID,
            },
        )
    # Second skill pass should trigger level_completed=True
    r = client.post(
        f"/api/v2/coach/students/{STUDENT_ID}/skills/{SKILL_ID_2}/test",
        json={
            "attempts_count": 10,
            "success_count": 8,
            "level_id": LEVEL_ID,
            "program_id": PROGRAM_ID,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["level_completed"] is True


def test_recommend_level_up_returns_201():
    app = _build_coach_app()
    client = TestClient(app)
    # First pass all required skills
    for skill_id in (SKILL_ID, SKILL_ID_2):
        client.post(
            f"/api/v2/coach/students/{STUDENT_ID}/skills/{skill_id}/test",
            json={
                "attempts_count": 10,
                "success_count": 8,
                "level_id": LEVEL_ID,
                "program_id": PROGRAM_ID,
            },
        )
    r = client.post(
        f"/api/v2/coach/students/{STUDENT_ID}/level-up",
        json={"program_id": PROGRAM_ID},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["student_id"] == STUDENT_ID
    assert body["status"] == "RECOMMENDED"


# ---------------------------------------------------------------------------
# Real-router authorization coverage
# ---------------------------------------------------------------------------


class _Dumpable:
    def __init__(self, **values: object) -> None:
        self._values = values

    def model_dump(self, *args: object, **kwargs: object) -> dict[str, object]:
        return self._values


class _SpyUseCase:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0
        self.args: tuple[object, ...] = ()
        self.kwargs: dict[str, object] = {}

    async def execute(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        self.args = args
        self.kwargs = kwargs
        return self.result


class _PassportByStudentUseCase:
    def __init__(self, results: dict[str, object]) -> None:
        self.results = results
        self.calls = 0

    async def execute(self, command: object) -> object:
        self.calls += 1
        student_id = command.student_id  # type: ignore[attr-defined]
        result = self.results[student_id]
        if isinstance(result, Exception):
            raise result
        return result


class _AssignedSessions:
    def __init__(self, assigned_session_ids: set[str]) -> None:
        self._assigned_session_ids = assigned_session_ids
        self.calls: list[tuple[str, str]] = []

    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool:
        self.calls.append((coach_id, session_id))
        return coach_id == COACH_ID and session_id in self._assigned_session_ids


def _real_router_claims() -> AuthClaims:
    return AuthClaims(
        user_id=COACH_ID,
        email="coach@example.com",
        academy_id=ACADEMY_ID,
        roles=("coach",),
    )


def _build_real_router_app(
    *,
    student_session_ids: list[str],
    assigned_session_ids: set[str],
) -> tuple[FastAPI, SimpleNamespace]:
    today_session = SimpleNamespace(
        session_id=SESSION_ID,
        occurrence_id="occurrence-001",
        roster_session_id=SESSION_ID,
        title="Friday Training",
        location="Court 1",
        timezone="America/Chicago",
        start_at=datetime(2026, 6, 19, 14, 0, tzinfo=UTC),
        end_at=datetime(2026, 6, 19, 15, 0, tzinfo=UTC),
    )
    assigned_sessions = _AssignedSessions(assigned_session_ids)
    spies = SimpleNamespace(
        assigned_sessions=assigned_sessions,
        list_today=_SpyUseCase([today_session]),
        get_passport=_SpyUseCase([_Dumpable(skill_id=SKILL_ID)]),
        update_skill_status=_SpyUseCase(_Dumpable(student_id=STUDENT_ID, skill_id=SKILL_ID)),
        record_test_attempt=_SpyUseCase(_Dumpable(student_id=STUDENT_ID, skill_id=SKILL_ID)),
        recommend_level_up=_SpyUseCase(_Dumpable(student_id=STUDENT_ID)),
        create_skill_note=_SpyUseCase(_Dumpable(student_id=STUDENT_ID, skill_id=SKILL_ID)),
        list_skill_notes=_SpyUseCase([_Dumpable(student_id=STUDENT_ID, skill_id=SKILL_ID)]),
        get_progress_summary=_SpyUseCase(
            StudentProgressOverview(
                student_id=STUDENT_ID,
                student_name="Student One",
                program_id=PROGRAM_ID,
                program_name="Badminton Skill Pathway",
                next_action="continue_practice",
            )
        ),
        get_program=_SpyUseCase(_Dumpable(program_id=PROGRAM_ID, name="Badminton Skill Pathway")),
        resolve_default_program=_SpyUseCase(
            _Dumpable(program_id=PROGRAM_ID, name="Badminton Skill Pathway")
        ),
    )
    student_progress = SimpleNamespace(
        get_passport=spies.get_passport,
        update_skill_status=spies.update_skill_status,
        record_test_attempt=spies.record_test_attempt,
        recommend_level_up=spies.recommend_level_up,
        get_progress_summary=spies.get_progress_summary,
    )
    curriculum = SimpleNamespace(
        get_program=spies.get_program,
        resolve_default_program=spies.resolve_default_program,
    )

    get_roster = _SpyUseCase(
        [
            RosterEntry(
                enrollment_id="enrollment-001",
                student_id=STUDENT_ID,
                full_name="Student One",
                status="active",
            )
        ]
    )
    spies.get_roster = get_roster

    async def active_session_enrollments_for_student(student_id: str) -> list[SimpleNamespace]:
        if student_id != STUDENT_ID:
            return []
        return [SimpleNamespace(session_id=session_id) for session_id in student_session_ids]

    use_cases = CoachUseCases(
        list_today=spies.list_today,  # type: ignore[arg-type]
        get_roster=get_roster,  # type: ignore[arg-type]
        mark_attendance=AsyncMock(),  # type: ignore[arg-type]
        bulk_mark_attendance=AsyncMock(),  # type: ignore[arg-type]
        get_dashboard_metrics=AsyncMock(),  # type: ignore[arg-type]
        create_lesson_plan=AsyncMock(),  # type: ignore[arg-type]
        list_lesson_plans=AsyncMock(),  # type: ignore[arg-type]
        create_progress_note=AsyncMock(),  # type: ignore[arg-type]
        list_progress_notes=AsyncMock(),  # type: ignore[arg-type]
        assigned_sessions=assigned_sessions,  # type: ignore[arg-type]
        add_student_to_roster=AsyncMock(),  # type: ignore[arg-type]
        remove_student_from_roster=AsyncMock(),  # type: ignore[arg-type]
        create_feedback=AsyncMock(),  # type: ignore[arg-type]
        list_feedback=AsyncMock(),  # type: ignore[arg-type]
        list_billing_enrollments=AsyncMock(),  # type: ignore[arg-type]
        preview_student_session_type_move=AsyncMock(),  # type: ignore[arg-type]
        move_student_session_type=AsyncMock(),  # type: ignore[arg-type]
        list_session_types=AsyncMock(),  # type: ignore[arg-type]
        get_billing_enrollment=AsyncMock(),
        get_active_session_enrollments_for_student=active_session_enrollments_for_student,
        list_all_sessions=AsyncMock(),
        get_profile=AsyncMock(),
        update_profile=AsyncMock(),
        student_progress=student_progress,  # type: ignore[arg-type]
        create_skill_note=spies.create_skill_note,
        list_skill_notes=spies.list_skill_notes,
    )
    use_cases.curriculum = curriculum

    app = FastAPI()
    app.include_router(coach_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = _real_router_claims
    app.dependency_overrides[get_coach_use_cases] = lambda: use_cases
    return app, spies


def _assert_no_skill_spies_called(spies: SimpleNamespace) -> None:
    assert spies.get_passport.calls == 0
    assert spies.update_skill_status.calls == 0
    assert spies.record_test_attempt.calls == 0
    assert spies.recommend_level_up.calls == 0
    assert spies.create_skill_note.calls == 0
    assert spies.list_skill_notes.calls == 0
    assert spies.get_progress_summary.calls == 0


_SKILL_ENDPOINTS = [
    (
        "GET",
        f"/api/v2/coach/students/{STUDENT_ID}/passport?program_id={PROGRAM_ID}",
        None,
    ),
    (
        "POST",
        f"/api/v2/coach/students/{STUDENT_ID}/skills/{SKILL_ID}/status",
        {"level_id": LEVEL_ID, "program_id": PROGRAM_ID, "status": "PRACTICING"},
    ),
    (
        "POST",
        f"/api/v2/coach/students/{STUDENT_ID}/skills/{SKILL_ID}/test",
        {
            "level_id": LEVEL_ID,
            "program_id": PROGRAM_ID,
            "attempts_count": 3,
            "success_count": 2,
        },
    ),
    (
        "POST",
        f"/api/v2/coach/students/{STUDENT_ID}/level-up",
        {"program_id": PROGRAM_ID},
    ),
    (
        "POST",
        f"/api/v2/coach/students/{STUDENT_ID}/skill-notes",
        {"skill_id": SKILL_ID, "body": "ready for review"},
    ),
    (
        "GET",
        f"/api/v2/coach/students/{STUDENT_ID}/skill-notes?skill_id={SKILL_ID}",
        None,
    ),
]


_ASSIGNED_SKILL_ENDPOINTS = [
    (
        "GET",
        f"/api/v2/coach/students/{STUDENT_ID}/passport?program_id={PROGRAM_ID}",
        None,
        200,
        "get_passport",
        {"passport": [{"skill_id": SKILL_ID}]},
    ),
    (
        "POST",
        f"/api/v2/coach/students/{STUDENT_ID}/skills/{SKILL_ID}/status",
        {"level_id": LEVEL_ID, "program_id": PROGRAM_ID, "status": "PRACTICING"},
        200,
        "update_skill_status",
        {"student_id": STUDENT_ID, "skill_id": SKILL_ID},
    ),
    (
        "POST",
        f"/api/v2/coach/students/{STUDENT_ID}/skills/{SKILL_ID}/test",
        {
            "level_id": LEVEL_ID,
            "program_id": PROGRAM_ID,
            "attempts_count": 3,
            "success_count": 2,
        },
        201,
        "record_test_attempt",
        {"student_id": STUDENT_ID, "skill_id": SKILL_ID},
    ),
    (
        "POST",
        f"/api/v2/coach/students/{STUDENT_ID}/level-up",
        {"program_id": PROGRAM_ID},
        201,
        "recommend_level_up",
        {"student_id": STUDENT_ID},
    ),
    (
        "POST",
        f"/api/v2/coach/students/{STUDENT_ID}/skill-notes",
        {"skill_id": SKILL_ID, "body": "ready for review"},
        201,
        "create_skill_note",
        {"student_id": STUDENT_ID, "skill_id": SKILL_ID},
    ),
    (
        "GET",
        f"/api/v2/coach/students/{STUDENT_ID}/skill-notes?skill_id={SKILL_ID}",
        None,
        200,
        "list_skill_notes",
        {"notes": [{"student_id": STUDENT_ID, "skill_id": SKILL_ID}]},
    ),
]


@pytest.mark.parametrize(
    ("method", "path", "json_body", "expected_status", "spy_name", "expected_json"),
    _ASSIGNED_SKILL_ENDPOINTS,
)
def test_real_skill_router_allows_assigned_coach_to_access_student_skill_routes(
    method: str,
    path: str,
    json_body: dict[str, object] | None,
    expected_status: int,
    spy_name: str,
    expected_json: dict[str, object],
) -> None:
    app, spies = _build_real_router_app(
        student_session_ids=[SESSION_ID],
        assigned_session_ids={SESSION_ID},
    )
    client = TestClient(app)

    response = client.request(method, path, json=json_body)

    assert response.status_code == expected_status, response.text
    assert response.json() == expected_json
    assert getattr(spies, spy_name).calls == 1
    assert spies.assigned_sessions.calls == [(COACH_ID, SESSION_ID)]


@pytest.mark.parametrize(("method", "path", "json_body"), _SKILL_ENDPOINTS)
def test_real_skill_router_returns_404_when_coach_is_not_assigned_to_student(
    method: str,
    path: str,
    json_body: dict[str, object] | None,
) -> None:
    app, spies = _build_real_router_app(
        student_session_ids=[SESSION_ID],
        assigned_session_ids=set(),
    )
    client = TestClient(app)

    response = client.request(method, path, json=json_body)

    assert response.status_code == 404, response.text
    _assert_no_skill_spies_called(spies)


def test_real_skill_router_returns_404_when_student_has_no_active_session_enrollments() -> None:
    app, spies = _build_real_router_app(
        student_session_ids=[],
        assigned_session_ids={SESSION_ID},
    )
    client = TestClient(app)

    response = client.get(f"/api/v2/coach/students/{STUDENT_ID}/passport?program_id={PROGRAM_ID}")

    assert response.status_code == 404, response.text
    _assert_no_skill_spies_called(spies)


def test_real_skill_router_returns_404_when_test_session_is_not_enrolled_for_student() -> None:
    app, spies = _build_real_router_app(
        student_session_ids=[SESSION_ID],
        assigned_session_ids={SESSION_ID, "other-session"},
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v2/coach/students/{STUDENT_ID}/skills/{SKILL_ID}/test",
        json={
            "level_id": LEVEL_ID,
            "program_id": PROGRAM_ID,
            "session_id": "other-session",
            "attempts_count": 3,
            "success_count": 2,
        },
    )

    assert response.status_code == 404, response.text
    _assert_no_skill_spies_called(spies)


def test_real_skill_note_create_passes_command_and_academy_id_for_assigned_coach() -> None:
    app, spies = _build_real_router_app(
        student_session_ids=[SESSION_ID],
        assigned_session_ids={SESSION_ID},
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v2/coach/students/{STUDENT_ID}/skill-notes",
        json={"skill_id": SKILL_ID, "body": "ready for review"},
    )

    assert response.status_code == 201, response.text
    assert spies.create_skill_note.calls == 1
    assert len(spies.create_skill_note.args) == 1
    assert spies.create_skill_note.args[0].student_id == STUDENT_ID
    assert spies.create_skill_note.args[0].skill_id == SKILL_ID
    assert spies.create_skill_note.args[0].coach_id == COACH_ID
    assert spies.create_skill_note.args[0].session_id == SESSION_ID
    assert spies.create_skill_note.kwargs == {"academy_id": ACADEMY_ID}


def test_real_skill_router_session_students_progress_returns_rows_for_assigned_coach() -> None:
    app, spies = _build_real_router_app(
        student_session_ids=[SESSION_ID],
        assigned_session_ids={SESSION_ID},
    )
    client = TestClient(app)

    response = client.get(
        f"/api/v2/coach/sessions/{SESSION_ID}/students-progress",
        params={"program_id": PROGRAM_ID},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["student_id"] == STUDENT_ID
    assert row["student_name"] == "Student One"
    assert row["program_id"] == PROGRAM_ID
    assert row["program_name"] == "Badminton Skill Pathway"
    assert row["next_action"] == "continue_practice"
    assert row["required_skill_count"] == 0
    assert row["certificate_count"] == 0
    assert spies.assigned_sessions.calls == [(COACH_ID, SESSION_ID)]
    assert spies.get_program.calls == 1
    assert spies.get_progress_summary.calls == 1
    assert spies.get_progress_summary.args == (
        ProgressSummaryRequest(
            student_id=STUDENT_ID,
            student_name="Student One",
            program_id=PROGRAM_ID,
            program_name="Badminton Skill Pathway",
        ),
    )


def test_real_skill_router_session_students_progress_without_program_uses_default_program() -> None:
    app, spies = _build_real_router_app(
        student_session_ids=[SESSION_ID],
        assigned_session_ids={SESSION_ID},
    )
    client = TestClient(app)

    response = client.get(f"/api/v2/coach/sessions/{SESSION_ID}/students-progress")

    assert response.status_code == 200, response.text
    assert len(response.json()["rows"]) == 1
    assert spies.resolve_default_program.calls == 1
    assert spies.get_program.calls == 1
    assert spies.get_progress_summary.args == (
        ProgressSummaryRequest(
            student_id=STUDENT_ID,
            student_name="Student One",
            program_id=PROGRAM_ID,
            program_name="Badminton Skill Pathway",
        ),
    )


def test_real_skill_router_session_students_progress_unassigned_returns_404_before_roster() -> None:
    app, spies = _build_real_router_app(
        student_session_ids=[SESSION_ID],
        assigned_session_ids=set(),
    )
    client = TestClient(app)

    response = client.get(
        f"/api/v2/coach/sessions/{SESSION_ID}/students-progress",
        params={"program_id": PROGRAM_ID},
    )

    assert response.status_code == 404, response.text
    assert spies.assigned_sessions.calls == [(COACH_ID, SESSION_ID)]
    assert spies.get_program.calls == 0
    assert spies.get_progress_summary.calls == 0


# ---------------------------------------------------------------------------
# Task 3: session skill-board route
# ---------------------------------------------------------------------------


class _FakeLevelProgressRepoBoard:
    """Minimal fake for GetSkillBoard — supports get_active only."""

    def __init__(self, rows: list[StudentLevelProgress]) -> None:
        self._rows = rows

    async def get_active(self, student_id: str, program_id: str) -> StudentLevelProgress | None:
        for row in self._rows:
            if row.student_id == student_id and row.program_id == program_id:
                return row
        return None


class _FakeSkillProgressRepoBoard:
    """Fake skill-progress repo with list_for_students for GetSkillBoard."""

    async def list_for_students(self, student_ids: list[str], level_id: str) -> list[object]:
        return []


class _FakeRecommendationRepoBoard:
    async def get_active_for_student(self, student_id: str, program_id: str) -> object | None:
        return None


class _FakeSkillLookupBoard:
    def __init__(self) -> None:
        self._levels = {
            LEVEL_ID: SimpleNamespace(level_id=LEVEL_ID, name="Level 1", sequence=1),
        }
        self._skills = {
            LEVEL_ID: [
                SimpleNamespace(skill_id=SKILL_ID, name="Skill 001", sequence=1, is_required=True),
            ],
        }

    async def get_level(self, level_id: str) -> object | None:
        return self._levels.get(level_id)

    async def list_skills_for_level(self, level_id: str) -> list[object]:
        return self._skills.get(level_id, [])


def _build_real_router_app_with_board(
    *,
    assigned: bool,
    coach_persona: bool = True,
) -> FastAPI:
    """Build a real-router app wired with GetSkillBoard for skill-board tests."""
    assigned_sessions = _AssignedSessions({SESSION_ID} if assigned else set())

    now = datetime.now(UTC)
    active_level = StudentLevelProgress(
        progress_id="lp-board-001",
        academy_id=ACADEMY_ID,
        student_id=STUDENT_ID,
        program_id=PROGRAM_ID,
        level_id=LEVEL_ID,
        status="active",
        started_at=now,
        created_at=now,
    )
    level_progress_repo = _FakeLevelProgressRepoBoard([active_level])
    skill_progress_repo = _FakeSkillProgressRepoBoard()
    recommendation_repo = _FakeRecommendationRepoBoard()
    skill_lookup = _FakeSkillLookupBoard()

    get_skill_board = GetSkillBoard(
        level_progress=level_progress_repo,  # type: ignore[arg-type]
        skill_progress=skill_progress_repo,  # type: ignore[arg-type]
        recommendations=recommendation_repo,  # type: ignore[arg-type]
        skill_lookup=skill_lookup,  # type: ignore[arg-type]
    )

    student_progress = SimpleNamespace(
        get_passport=_SpyUseCase([_Dumpable(skill_id=SKILL_ID)]),
        update_skill_status=_SpyUseCase(_Dumpable(student_id=STUDENT_ID, skill_id=SKILL_ID)),
        record_test_attempt=_SpyUseCase(_Dumpable(student_id=STUDENT_ID, skill_id=SKILL_ID)),
        recommend_level_up=_SpyUseCase(_Dumpable(student_id=STUDENT_ID)),
        get_progress_summary=_SpyUseCase(
            StudentProgressOverview(
                student_id=STUDENT_ID,
                student_name="Student One",
                program_id=PROGRAM_ID,
                program_name="Badminton Skill Pathway",
                next_action="continue_practice",
            )
        ),
        get_skill_board=get_skill_board,
    )
    curriculum = SimpleNamespace(
        get_program=_SpyUseCase(_Dumpable(program_id=PROGRAM_ID, name="Badminton Skill Pathway")),
        resolve_default_program=_SpyUseCase(
            _Dumpable(program_id=PROGRAM_ID, name="Badminton Skill Pathway")
        ),
    )

    get_roster = _SpyUseCase(
        [
            RosterEntry(
                enrollment_id="enrollment-001",
                student_id=STUDENT_ID,
                full_name="Student One",
                status="active",
            )
        ]
    )

    async def active_session_enrollments_for_student(student_id: str) -> list[SimpleNamespace]:
        if student_id != STUDENT_ID:
            return []
        return [SimpleNamespace(session_id=SESSION_ID)]

    use_cases = CoachUseCases(
        list_today=AsyncMock(),  # type: ignore[arg-type]
        get_roster=get_roster,  # type: ignore[arg-type]
        mark_attendance=AsyncMock(),  # type: ignore[arg-type]
        bulk_mark_attendance=AsyncMock(),  # type: ignore[arg-type]
        get_dashboard_metrics=AsyncMock(),  # type: ignore[arg-type]
        create_lesson_plan=AsyncMock(),  # type: ignore[arg-type]
        list_lesson_plans=AsyncMock(),  # type: ignore[arg-type]
        create_progress_note=AsyncMock(),  # type: ignore[arg-type]
        list_progress_notes=AsyncMock(),  # type: ignore[arg-type]
        assigned_sessions=assigned_sessions,  # type: ignore[arg-type]
        add_student_to_roster=AsyncMock(),  # type: ignore[arg-type]
        remove_student_from_roster=AsyncMock(),  # type: ignore[arg-type]
        create_feedback=AsyncMock(),  # type: ignore[arg-type]
        list_feedback=AsyncMock(),  # type: ignore[arg-type]
        list_billing_enrollments=AsyncMock(),  # type: ignore[arg-type]
        preview_student_session_type_move=AsyncMock(),  # type: ignore[arg-type]
        move_student_session_type=AsyncMock(),  # type: ignore[arg-type]
        list_session_types=AsyncMock(),  # type: ignore[arg-type]
        get_billing_enrollment=AsyncMock(),
        get_active_session_enrollments_for_student=active_session_enrollments_for_student,
        list_all_sessions=AsyncMock(),
        get_profile=AsyncMock(),
        update_profile=AsyncMock(),
        student_progress=student_progress,  # type: ignore[arg-type]
        create_skill_note=_SpyUseCase(_Dumpable(student_id=STUDENT_ID, skill_id=SKILL_ID)),
        list_skill_notes=_SpyUseCase([_Dumpable(student_id=STUDENT_ID, skill_id=SKILL_ID)]),
    )
    use_cases.curriculum = curriculum  # type: ignore[assignment]

    app = FastAPI()
    app.include_router(coach_router, prefix="/api/v2")

    if coach_persona:
        app.dependency_overrides[get_auth_claims] = _real_router_claims
    else:
        # Wrong persona: parent
        app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
            user_id="parent-001",
            email="parent@example.com",
            academy_id=ACADEMY_ID,
            roles=("parent",),
        )

    app.dependency_overrides[get_coach_use_cases] = lambda: use_cases

    @app.middleware("http")
    async def _tenant_ctx(request: Request, call_next):
        with tenant_scope(ACADEMY_ID):
            return await call_next(request)

    return app


@pytest.fixture()
def client() -> TestClient:
    app = _build_real_router_app_with_board(assigned=True)
    return TestClient(app)


@pytest.fixture()
def client_unassigned() -> TestClient:
    app = _build_real_router_app_with_board(assigned=False)
    return TestClient(app)


@pytest.fixture()
def client_parent_persona() -> TestClient:
    app = _build_real_router_app_with_board(assigned=True, coach_persona=False)
    return TestClient(app)


def test_session_skill_board_returns_groups(client: TestClient) -> None:
    response = client.get(
        f"/api/v2/coach/sessions/{SESSION_ID}/skill-board?program_id={PROGRAM_ID}"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["program_id"] == PROGRAM_ID
    assert isinstance(body["groups"], list)
    assert isinstance(body["unplaced"], list)
    group = body["groups"][0]
    assert {"level_id", "level_name", "sequence", "skills", "students"} <= set(group)
    student = group["students"][0]
    assert {"student_id", "student_name", "statuses", "required_passed"} <= set(student)


def test_session_skill_board_unassigned_coach_404(client_unassigned: TestClient) -> None:
    response = client_unassigned.get(f"/api/v2/coach/sessions/{SESSION_ID}/skill-board")
    assert response.status_code == 404


def test_session_skill_board_wrong_persona_rejected(client_parent_persona: TestClient) -> None:
    response = client_parent_persona.get(f"/api/v2/coach/sessions/{SESSION_ID}/skill-board")
    assert response.status_code in (401, 403, 404)


def test_real_skill_router_day_hub_returns_date_summary_and_grouped_skill_focus() -> None:
    app, spies = _build_real_router_app(
        student_session_ids=[SESSION_ID],
        assigned_session_ids={SESSION_ID},
    )
    spies.get_passport.result = [
        _Dumpable(
            skill_id=SKILL_ID,
            skill_name="Backhand clear",
            skill_description="Clear from back court",
            status="LEARNING",
            program_id=PROGRAM_ID,
            level_id=LEVEL_ID,
        )
    ]
    client = TestClient(app)

    response = client.get("/api/v2/coach/day-hub", params={"date": "2026-06-19"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["date"] == "2026-06-19"
    assert body["summary"] == {
        "session_count": 1,
        "student_count": 1,
        "attendance_state": "not_started",
        "skill_focus_count": 1,
        "parent_message_count": 0,
        "absence_notice_count": 0,
    }
    assert "expected_cut_cents" not in str(body)
    session = body["sessions"][0]
    assert session["occurrence_id"] == "occurrence-001"
    assert session["skill_groups"] == [
        {
            "skill_id": SKILL_ID,
            "skill_name": "Backhand clear",
            "student_ids": [STUDENT_ID],
            "student_names": ["Student One"],
            "status": "LEARNING",
        }
    ]
    assert session["students"][0]["top_gaps"][0]["skill_name"] == "Backhand clear"


def test_real_skill_router_day_hub_keeps_unplaced_student_from_breaking_date() -> None:
    app, spies = _build_real_router_app(
        student_session_ids=[SESSION_ID],
        assigned_session_ids={SESSION_ID},
    )
    unplaced_student_id = "student-without-level"
    spies.get_roster.result = [
        RosterEntry(
            enrollment_id="enrollment-001",
            student_id=STUDENT_ID,
            full_name="Student One",
            status="active",
        ),
        RosterEntry(
            enrollment_id="enrollment-002",
            student_id=unplaced_student_id,
            full_name="Student Without Level",
            status="active",
        ),
    ]
    spies.get_passport = _PassportByStudentUseCase(
        {
            STUDENT_ID: [
                _Dumpable(
                    skill_id=SKILL_ID,
                    skill_name="Backhand clear",
                    status="LEARNING",
                    program_id=PROGRAM_ID,
                    level_id=LEVEL_ID,
                )
            ],
            unplaced_student_id: StudentNotPlaced(
                student_id=unplaced_student_id,
                program_id=PROGRAM_ID,
            ),
        }
    )
    app.dependency_overrides[
        get_coach_use_cases
    ]().student_progress.get_passport = spies.get_passport
    client = TestClient(app)

    response = client.get("/api/v2/coach/day-hub", params={"date": "2026-06-25"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["student_count"] == 2
    assert body["summary"]["skill_focus_count"] == 1
    students = body["sessions"][0]["students"]
    assert students[1] == {
        "student_id": unplaced_student_id,
        "full_name": "Student Without Level",
        "enrollment_status": "active",
        "skills": [],
        "top_gaps": [],
    }


def test_real_skill_router_session_skills_returns_by_skill_and_by_student_read_model() -> None:
    app, spies = _build_real_router_app(
        student_session_ids=[SESSION_ID],
        assigned_session_ids={SESSION_ID},
    )
    spies.get_passport.result = [
        _Dumpable(
            skill_id=SKILL_ID,
            skill_name="Backhand clear",
            status="LEARNING",
            program_id=PROGRAM_ID,
            level_id=LEVEL_ID,
        ),
        _Dumpable(
            skill_id=SKILL_ID_2,
            skill_name="Serve consistency",
            status="PASSED",
            program_id=PROGRAM_ID,
            level_id=LEVEL_ID,
        ),
    ]
    client = TestClient(app)

    response = client.get(
        f"/api/v2/coach/sessions/{SESSION_ID}/skills",
        params={"date": "2026-06-19"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == SESSION_ID
    assert body["occurrence_id"] == "occurrence-001"
    assert body["date"] == "2026-06-19"
    assert body["roster"] == [
        {
            "student_id": STUDENT_ID,
            "full_name": "Student One",
            "enrollment_status": "active",
        }
    ]
    assert [group["skill_name"] for group in body["skill_groups"]] == ["Backhand clear"]
    assert [skill["skill_name"] for skill in body["students"][0]["skills"]] == [
        "Backhand clear",
        "Serve consistency",
    ]


def test_real_skill_router_session_skills_unassigned_returns_404_before_roster() -> None:
    app, spies = _build_real_router_app(
        student_session_ids=[SESSION_ID],
        assigned_session_ids=set(),
    )
    client = TestClient(app)

    response = client.get(
        f"/api/v2/coach/sessions/{SESSION_ID}/skills",
        params={"date": "2026-06-19"},
    )

    assert response.status_code == 404, response.text
    assert spies.assigned_sessions.calls == [(COACH_ID, SESSION_ID)]
    assert spies.get_passport.calls == 0


def test_real_skill_router_bulk_status_updates_selected_session_students_only() -> None:
    app, spies = _build_real_router_app(
        student_session_ids=[SESSION_ID],
        assigned_session_ids={SESSION_ID},
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v2/coach/sessions/{SESSION_ID}/skills/bulk-status",
        json={
            "skill_id": SKILL_ID,
            "program_id": PROGRAM_ID,
            "level_id": LEVEL_ID,
            "student_ids": [STUDENT_ID],
            "status": "PRACTICING",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"updated": 1, "student_ids": [STUDENT_ID]}
    assert spies.update_skill_status.calls == 1
    command = spies.update_skill_status.args[0]
    assert command.student_id == STUDENT_ID
    assert command.skill_id == SKILL_ID
    assert command.new_status == "PRACTICING"


def test_real_skill_router_bulk_status_rejects_student_outside_session() -> None:
    app, spies = _build_real_router_app(
        student_session_ids=[SESSION_ID],
        assigned_session_ids={SESSION_ID},
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v2/coach/sessions/{SESSION_ID}/skills/bulk-status",
        json={
            "skill_id": SKILL_ID,
            "program_id": PROGRAM_ID,
            "level_id": LEVEL_ID,
            "student_ids": ["other-student"],
            "status": "PRACTICING",
        },
    )

    assert response.status_code == 404, response.text
    assert spies.update_skill_status.calls == 0


def test_real_skill_router_rejects_success_count_above_attempts_count() -> None:
    """Issue #524: success_count > attempts_count must 422 before the use case runs."""
    app, spies = _build_real_router_app(
        student_session_ids=[SESSION_ID],
        assigned_session_ids={SESSION_ID},
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v2/coach/students/{STUDENT_ID}/skills/{SKILL_ID}/test",
        json={
            "level_id": LEVEL_ID,
            "program_id": PROGRAM_ID,
            "session_id": SESSION_ID,
            "attempts_count": 1,
            "success_count": 5,
        },
    )

    assert response.status_code == 422, response.text
    assert spies.record_test_attempt.calls == 0
