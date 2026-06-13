"""Interface tests for the admin student-progress / level-up / certificate flow.

A standalone mini FastAPI app mounts the real admin progress routes and wires
them to the real student_progress use cases backed by in-memory fakes. The
curriculum side is seeded with the real Badminton pathway and read through the
real ``CurriculumSkillLookupAdapter`` so the cross-context wiring is exercised.

Routes are driven over HTTP (admin persona). Coach recommendations are driven
through the same shared use-case instances, so the whole flow runs against one
consistent set of repositories.

Covered (happy path):
    place student -> skill progress created -> coach records passing tests ->
    required skills PASSED -> level completion detected -> coach recommends ->
    admin approves -> current level completed -> next level created ->
    certificate issued -> admin can retrieve the certificate.

Covered (rejection path):
    admin rejects -> student does not level up -> no certificate ->
    rejection reason saved.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.v2.contexts.curriculum.application.use_cases.manage_levels import ListLevels
from backend.v2.contexts.curriculum.application.use_cases.manage_program import (
    GetProgram,
    ResolveDefaultActiveProgram,
)
from backend.v2.contexts.curriculum.application.use_cases.seed_curriculum import (
    seed_badminton_pathway,
)
from backend.v2.contexts.curriculum.domain.models import (
    ExternalLessonReference,
    Level,
    Program,
    Skill,
    SkillCriterion,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    AdminStudentPage,
    AdminStudentSummary,
)
from backend.v2.contexts.student_progress.application.use_cases.get_certificates import (
    GetStudentCertificates,
)
from backend.v2.contexts.student_progress.application.use_cases.get_level_up_queue import (
    GetLevelUpQueue,
)
from backend.v2.contexts.student_progress.application.use_cases.get_passport import (
    GetStudentPassport,
)
from backend.v2.contexts.student_progress.application.use_cases.get_progress_summary import (
    GetProgressSummary,
)
from backend.v2.contexts.student_progress.application.use_cases.get_student_progress import (
    GetStudentProgress,
)
from backend.v2.contexts.student_progress.application.use_cases.place_student import (
    PlaceStudentInLevel,
)
from backend.v2.contexts.student_progress.application.use_cases.recommend_level_up import (
    RecommendLevelUp,
    RecommendLevelUpCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.record_test_attempt import (
    RecordTestAttempt,
    RecordTestAttemptCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.review_level_up import (
    ReviewLevelUpRecommendation,
)
from backend.v2.contexts.student_progress.application.use_cases.update_skill_status import (
    UpdateSkillStatus,
)
from backend.v2.contexts.student_progress.infrastructure.curriculum_lookup_adapter import (
    CurriculumSkillLookupAdapter,
)
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.progress_routes import router as progress_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy import tenant_scope

ACADEMY_ID = "test-academy"


def _run(coro):
    """Run a coroutine to completion on a private loop.

    We deliberately do NOT use ``asyncio.run`` here: it calls
    ``set_event_loop(None)`` on teardown, which corrupts the default event loop
    that sibling sync interface tests rely on (they use
    ``asyncio.get_event_loop().run_until_complete``). Running a fresh loop
    without ever touching the global current-loop keeps this test isolated.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Fake curriculum repos (only the methods the seed + adapter touch)
# ---------------------------------------------------------------------------


class _FakeProgramRepo:
    def __init__(self) -> None:
        self.saved: list[Program] = []

    async def save(self, program: Program) -> None:
        self.saved.append(program)

    async def get(self, program_id: str) -> Program | None:
        return next((p for p in self.saved if p.program_id == program_id), None)

    async def list_active(self) -> list[Program]:
        return [p for p in self.saved if p.is_active]


class _FakeLevelRepo:
    def __init__(self) -> None:
        self.saved: list[Level] = []

    async def save(self, level: Level) -> None:
        self.saved.append(level)

    async def get(self, level_id: str) -> Level | None:
        return next((lv for lv in self.saved if lv.level_id == level_id), None)

    async def list_for_program(self, program_id: str) -> list[Level]:
        return [lv for lv in self.saved if lv.program_id == program_id]


class _FakeSkillRepo:
    def __init__(self) -> None:
        self.saved: list[Skill] = []

    async def save(self, skill: Skill) -> None:
        self.saved.append(skill)

    async def get(self, skill_id: str) -> Skill | None:
        return next((s for s in self.saved if s.skill_id == skill_id), None)

    async def list_for_level(self, level_id: str) -> list[Skill]:
        return sorted(
            (s for s in self.saved if s.level_id == level_id),
            key=lambda s: s.sequence,
        )


class _FakeCriterionRepo:
    def __init__(self) -> None:
        self.saved: list[SkillCriterion] = []

    async def save(self, criterion: SkillCriterion) -> None:
        self.saved.append(criterion)


class _FakeExternalRefRepo:
    def __init__(self) -> None:
        self.saved: list[ExternalLessonReference] = []

    async def save(self, ref: ExternalLessonReference) -> None:
        self.saved.append(ref)


# ---------------------------------------------------------------------------
# Fake student_progress repos
# ---------------------------------------------------------------------------


class _FakeLevelProgressRepo:
    def __init__(self) -> None:
        self.rows: list = []

    async def save(self, progress) -> None:
        self.rows.append(progress)

    async def get_active(self, student_id: str, program_id: str):
        actives = [
            p
            for p in self.rows
            if p.student_id == student_id and p.program_id == program_id and p.status == "active"
        ]
        return actives[-1] if actives else None

    async def get_by_id(self, progress_id: str):
        return next((p for p in self.rows if p.progress_id == progress_id), None)

    async def complete(self, progress_id: str, completed_at) -> None:
        self.rows = [
            p.model_copy(update={"status": "completed", "completed_at": completed_at})
            if p.progress_id == progress_id
            else p
            for p in self.rows
        ]

    async def list_for_student(self, student_id: str) -> list:
        return [p for p in self.rows if p.student_id == student_id]


class _FakeSkillProgressRepo:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], object] = {}

    async def save(self, sp) -> None:
        self.rows[(sp.student_id, sp.skill_id)] = sp

    async def upsert(self, sp):
        self.rows[(sp.student_id, sp.skill_id)] = sp
        return sp

    async def get(self, student_id: str, skill_id: str):
        return self.rows.get((student_id, skill_id))

    async def list_for_student_level(self, student_id: str, level_id: str) -> list:
        return [
            sp
            for sp in self.rows.values()
            if sp.student_id == student_id and sp.level_id == level_id
        ]

    async def list_passed_for_student_level(self, student_id: str, level_id: str) -> list:
        return [
            sp
            for sp in self.rows.values()
            if sp.student_id == student_id and sp.level_id == level_id and sp.status == "PASSED"
        ]


class _FakeTestAttemptRepo:
    def __init__(self) -> None:
        self.rows: list = []

    async def save(self, attempt) -> None:
        self.rows.append(attempt)

    async def list_for_student_skill(self, student_id: str, skill_id: str) -> list:
        return [a for a in self.rows if a.student_id == student_id and a.skill_id == skill_id]

    async def count_for_student_skill(self, student_id: str, skill_id: str) -> int:
        return len(await self.list_for_student_skill(student_id, skill_id))


class _FakeRecommendationRepo:
    def __init__(self) -> None:
        self.rows: dict[str, object] = {}

    async def save(self, rec) -> None:
        self.rows[rec.rec_id] = rec

    async def update_status(
        self, rec_id, status, reviewed_by, reviewed_at, rejection_reason
    ) -> None:
        rec = self.rows[rec_id]
        self.rows[rec_id] = rec.model_copy(
            update={
                "status": status,
                "reviewed_by": reviewed_by,
                "reviewed_at": reviewed_at,
                "rejection_reason": rejection_reason,
            }
        )

    async def get(self, rec_id: str):
        return self.rows.get(rec_id)

    async def get_active_for_student(self, student_id: str, program_id: str):
        return next(
            (
                r
                for r in self.rows.values()
                if r.student_id == student_id
                and r.program_id == program_id
                and r.status == "RECOMMENDED"
            ),
            None,
        )

    async def list_pending(self) -> list:
        return [r for r in self.rows.values() if r.status == "RECOMMENDED"]


class _FakeCertificateRepo:
    def __init__(self) -> None:
        self.rows: list = []

    async def save(self, cert) -> None:
        self.rows.append(cert)

    async def list_for_student(self, student_id: str) -> list:
        return [c for c in self.rows if c.student_id == student_id]


class _FakeListAdminStudents:
    def __init__(self, students: list[AdminStudentSummary]) -> None:
        self.students = students
        self.pages: dict[str | None, tuple[list[AdminStudentSummary], str | None]] | None = None
        self.calls: list[dict[str, object]] = []

    async def execute(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> AdminStudentPage:
        self.calls.append({"search": search, "status": status, "limit": limit, "cursor": cursor})
        if self.pages is not None:
            students, next_cursor = self.pages[cursor]
            return AdminStudentPage(students=students, next_cursor=next_cursor)
        return AdminStudentPage(students=self.students, next_cursor=None)


# ---------------------------------------------------------------------------
# App / env assembly
# ---------------------------------------------------------------------------


def _admin_claims() -> AuthClaims:
    return AuthClaims(
        user_id="admin-1",
        email="admin@example.com",
        academy_id=ACADEMY_ID,
        roles=("admin",),
    )


def _build_app(use_cases, claims: AuthClaims) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.middleware("http")
    async def _tenant_ctx(request: Request, call_next):
        with tenant_scope(claims.academy_id):
            return await call_next(request)

    app.include_router(progress_router, prefix="/api/v2/admin")
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.dependency_overrides[get_admin_use_cases] = lambda: use_cases
    return app


def test_coach_engagement_stats_route_returns_counts_for_date_range() -> None:
    execute = AsyncMock(
        return_value=[
            {"coach_id": "coach-1", "outcomes_recorded": 4},
            {"coach_id": "coach-2", "outcomes_recorded": 2},
        ]
    )
    use_cases = SimpleNamespace(
        get_coach_engagement_stats=SimpleNamespace(execute=execute),
    )
    client = TestClient(_build_app(use_cases, _admin_claims()))

    response = client.get(
        "/api/v2/admin/progress/coach-engagement",
        params={"start_date": "2026-06-01", "end_date": "2026-06-13"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "rows": [
            {"coach_id": "coach-1", "outcomes_recorded": 4},
            {"coach_id": "coach-2", "outcomes_recorded": 2},
        ]
    }
    execute.assert_awaited_once()
    kwargs = execute.await_args.kwargs
    assert kwargs["start_date"].isoformat() == "2026-06-01"
    assert kwargs["end_date"].isoformat() == "2026-06-13"


def test_coach_engagement_stats_repo_ignores_not_started_placement_rows() -> None:
    from backend.v2.contexts.student_progress.infrastructure.mongo_skill_progress_repo import (
        _RECORDED_OUTCOME_STATUSES,
    )

    assert "NOT_STARTED" not in _RECORDED_OUTCOME_STATUSES
    assert {"INTRODUCED", "PRACTICING", "PASSED", "NEEDS_REVIEW"}.issubset(
        set(_RECORDED_OUTCOME_STATUSES)
    )


@pytest.fixture()
def env():
    # --- curriculum: seed the real badminton pathway into fakes ---
    programs = _FakeProgramRepo()
    levels = _FakeLevelRepo()
    skills = _FakeSkillRepo()
    criteria = _FakeCriterionRepo()
    refs = _FakeExternalRefRepo()
    program = _run(
        seed_badminton_pathway(
            academy_id=ACADEMY_ID,
            programs=programs,
            levels=levels,
            skills=skills,
            criteria=criteria,
            refs=refs,
            created_by="admin-1",
        )
    )
    level1 = next(lv for lv in levels.saved if lv.sequence == 1)
    level2 = next(lv for lv in levels.saved if lv.sequence == 2)
    level1_skills = _run(skills.list_for_level(level1.level_id))

    skill_lookup = CurriculumSkillLookupAdapter(skill_repo=skills, level_repo=levels)

    # --- student_progress: real use cases over fakes ---
    level_repo = _FakeLevelProgressRepo()
    skill_repo = _FakeSkillProgressRepo()
    attempt_repo = _FakeTestAttemptRepo()
    rec_repo = _FakeRecommendationRepo()
    cert_repo = _FakeCertificateRepo()

    student_progress = SimpleNamespace(
        place_student=PlaceStudentInLevel(
            level_progress=level_repo,
            skill_progress=skill_repo,
            skill_lookup=skill_lookup,
        ),
        update_skill_status=UpdateSkillStatus(
            level_progress=level_repo,
            skill_progress=skill_repo,
        ),
        record_test_attempt=RecordTestAttempt(
            level_progress=level_repo,
            skill_progress=skill_repo,
            test_attempts=attempt_repo,
            skill_lookup=skill_lookup,
        ),
        recommend_level_up=RecommendLevelUp(
            level_progress=level_repo,
            skill_progress=skill_repo,
            recommendations=rec_repo,
            skill_lookup=skill_lookup,
        ),
        review_level_up=ReviewLevelUpRecommendation(
            recommendations=rec_repo,
            level_progress=level_repo,
            skill_progress=skill_repo,
            certificates=cert_repo,
            skill_lookup=skill_lookup,
        ),
        get_student_progress=GetStudentProgress(
            level_progress=level_repo,
            skill_progress=skill_repo,
            recommendations=rec_repo,
            certificates=cert_repo,
            skill_lookup=skill_lookup,
        ),
        get_passport=GetStudentPassport(
            level_progress=level_repo,
            skill_progress=skill_repo,
            skill_lookup=skill_lookup,
            test_attempts=attempt_repo,
        ),
        get_progress_summary=GetProgressSummary(
            level_progress=level_repo,
            skill_progress=skill_repo,
            recommendations=rec_repo,
            certificates=cert_repo,
            skill_lookup=skill_lookup,
        ),
        get_level_up_queue=GetLevelUpQueue(
            level_progress=level_repo,
            skill_progress=skill_repo,
            recommendations=rec_repo,
            skill_lookup=skill_lookup,
        ),
        get_certificates=GetStudentCertificates(certificates=cert_repo),
    )
    # Curriculum + student-name lookups the approve route uses to populate
    # certificate display fields (P1.2). Backed by the same fake repos.
    curriculum = SimpleNamespace(
        get_program=GetProgram(programs=programs),
        resolve_default_program=ResolveDefaultActiveProgram(programs=programs),
        list_levels=ListLevels(levels=levels),
    )

    class _FakeGetAdminStudent:
        async def execute(self, student_id: str):
            return SimpleNamespace(student_id=student_id, full_name="Alice Flow")

    list_admin_students = _FakeListAdminStudents(
        [
            AdminStudentSummary(
                student_id="st-overview-active",
                full_name="Alice Flow",
                parent_id="parent-1",
                status="active",
            ),
            AdminStudentSummary(
                student_id="st-overview-unplaced",
                full_name="Bob New",
                parent_id="parent-2",
                status="active",
            ),
        ]
    )
    use_cases = SimpleNamespace(
        list_admin_students=list_admin_students,
        student_progress=student_progress,
        curriculum=curriculum,
        get_admin_student=_FakeGetAdminStudent(),
    )
    app = _build_app(use_cases, _admin_claims())

    return SimpleNamespace(
        client=TestClient(app),
        use_cases=use_cases,
        list_admin_students=list_admin_students,
        ns=student_progress,
        level_repo=level_repo,
        rec_repo=rec_repo,
        cert_repo=cert_repo,
        program_id=program.program_id,
        level1=level1,
        level2=level2,
        level1_skills=level1_skills,
    )


def _place(env, student_id: str):
    return env.client.post(
        f"/api/v2/admin/students/{student_id}/place-in-level",
        json={"program_id": env.program_id, "level_id": env.level1.level_id},
    )


def _get_progress(env, student_id: str):
    return env.client.get(
        f"/api/v2/admin/students/{student_id}/progress",
        params={"program_id": env.program_id},
    )


def _get_default_progress(env, student_id: str):
    return env.client.get(f"/api/v2/admin/students/{student_id}/progress")


def _pass_all_level1_skills(env, student_id: str, coach_id: str = "coach-1") -> list:
    results = []
    for skill in env.level1_skills:
        with tenant_scope(ACADEMY_ID):
            result = _run(
                env.ns.record_test_attempt.execute(
                    RecordTestAttemptCommand(
                        student_id=student_id,
                        skill_id=skill.skill_id,
                        level_id=env.level1.level_id,
                        program_id=env.program_id,
                        coach_id=coach_id,
                        attempts_count=10,
                        success_count=10,
                    )
                )
            )
        results.append(result)
    return results


def _recommend(env, student_id: str, coach_id: str = "coach-1"):
    with tenant_scope(ACADEMY_ID):
        return _run(
            env.ns.recommend_level_up.execute(
                RecommendLevelUpCommand(
                    student_id=student_id,
                    program_id=env.program_id,
                    recommended_by=coach_id,
                )
            )
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_full_levelup_and_certificate_flow(env):
    student_id = "st-flow-1"

    # 2. Admin places student into Level 1.
    placed = _place(env, student_id)
    assert placed.status_code == 201, placed.text
    assert placed.json()["level_id"] == env.level1.level_id

    # 3. Student skill progress records are created (all NOT_STARTED).
    prog = _get_progress(env, student_id)
    assert prog.status_code == 200, prog.text
    body = prog.json()
    assert body["current_level_id"] == env.level1.level_id
    assert body["total_skills"] == len(env.level1_skills)
    assert body["not_started_skills"] == len(env.level1_skills)
    assert body["passed_skills"] == 0

    # 4-6. Coach records passing tests -> required skills PASSED -> level done.
    results = _pass_all_level1_skills(env, student_id)
    assert all(r.passed for r in results)
    assert results[-1].level_completed is True
    body2 = _get_progress(env, student_id).json()
    assert body2["passed_skills"] == len(env.level1_skills)

    # 7. Coach recommends level-up.
    rec = _recommend(env, student_id)
    assert rec.status == "RECOMMENDED"
    assert rec.from_level_id == env.level1.level_id
    assert rec.to_level_id == env.level2.level_id

    # Recommendation appears in the admin level-up queue.
    queue = env.client.get("/api/v2/admin/level-up-queue").json()["queue"]
    assert any(item["rec_id"] == rec.rec_id for item in queue)

    # 8. Admin approves level-up.
    approve = env.client.post(f"/api/v2/admin/level-up/{rec.rec_id}/approve")
    assert approve.status_code == 200, approve.text
    approved = approve.json()
    assert approved["status"] == "APPROVED"
    assert approved["cert_id"]

    # 9 & 10. Current level completed, next level progress created & active.
    body3 = _get_progress(env, student_id).json()
    assert body3["current_level_id"] == env.level2.level_id
    assert body3["current_level_sequence"] == 2
    all_progress = _run(env.level_repo.list_for_student(student_id))
    status_by_level = {p.level_id: p.status for p in all_progress}
    assert status_by_level[env.level1.level_id] == "completed"
    assert status_by_level[env.level2.level_id] == "active"

    # 11 & 12. Certificate issued and retrievable by admin.
    certs = env.client.get(f"/api/v2/admin/students/{student_id}/certificates").json()[
        "certificates"
    ]
    assert len(certs) == 1
    cert = certs[0]
    assert cert["cert_id"] == approved["cert_id"]
    assert cert["level_id"] == env.level1.level_id  # cert is for the completed level
    assert cert["cert_number"]
    # P1.2: display fields are populated from the directory/curriculum lookups,
    # not left blank.
    assert cert["student_name"] == "Alice Flow"
    assert cert["level_name"] == env.level1.name
    assert cert["program_name"] == "Badminton Skill Pathway"

    # Queue is empty once the recommendation has been decided.
    assert env.client.get("/api/v2/admin/level-up-queue").json()["queue"] == []


def test_place_student_resolves_default_program_when_only_one_active_program(env):
    student_id = "st-default-program"

    placed = env.client.post(
        f"/api/v2/admin/students/{student_id}/place-in-level",
        json={"level_id": env.level1.level_id},
    )

    assert placed.status_code == 201, placed.text
    body = placed.json()
    assert body["program_id"] == env.program_id
    assert body["level_id"] == env.level1.level_id


def test_pathway_placement_route_places_student_with_default_program(env):
    student_id = "st-pathway-route"

    placed = env.client.post(
        f"/api/v2/admin/students/{student_id}/pathway-placement",
        json={"level_id": env.level1.level_id},
    )

    assert placed.status_code == 201, placed.text
    assert placed.json()["program_id"] == env.program_id
    assert placed.json()["level_id"] == env.level1.level_id


def test_get_student_progress_resolves_default_program_when_omitted(env):
    student_id = "st-default-progress"
    assert _place(env, student_id).status_code == 201

    response = _get_default_progress(env, student_id)

    assert response.status_code == 200, response.text
    assert response.json()["program_id"] == env.program_id
    assert response.json()["current_level_id"] == env.level1.level_id


def test_admin_can_update_skill_status_and_record_test(env):
    student_id = "st-admin-skill-update"
    skill = env.level1_skills[0]
    assert _place(env, student_id).status_code == 201

    passport = env.client.get(
        f"/api/v2/admin/students/{student_id}/passport",
        params={"program_id": env.program_id},
    )

    assert passport.status_code == 200, passport.text
    body = passport.json()
    assert len(body["passport"]) == len(env.level1_skills)
    assert body["passport"][0]["status"] == "NOT_STARTED"

    status_response = env.client.post(
        f"/api/v2/admin/students/{student_id}/skills/{skill.skill_id}/status",
        json={
            "program_id": env.program_id,
            "level_id": env.level1.level_id,
            "status": "PRACTICING",
        },
    )

    assert status_response.status_code == 200, status_response.text
    assert status_response.json()["status"] == "PRACTICING"

    test_response = env.client.post(
        f"/api/v2/admin/students/{student_id}/skills/{skill.skill_id}/test",
        json={
            "program_id": env.program_id,
            "level_id": env.level1.level_id,
            "attempts_count": 5,
            "success_count": 5,
            "notes": "Admin observed clean repeat attempts",
        },
    )

    assert test_response.status_code == 201, test_response.text
    assert test_response.json()["passed"] is True
    assert test_response.json()["skill_status"] == "PASSED"

    updated_passport = env.client.get(
        f"/api/v2/admin/students/{student_id}/passport",
        params={"program_id": env.program_id},
    ).json()["passport"]
    updated_skill = next(entry for entry in updated_passport if entry["skill_id"] == skill.skill_id)
    assert updated_skill["status"] == "PASSED"
    assert updated_skill["test_attempt_count"] == 1
    assert updated_skill["last_test_passed"] is True


def test_repeated_same_level_placement_returns_existing_active_placement(env):
    student_id = "st-repeat-placement"

    first = _place(env, student_id)
    second = _place(env, student_id)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["progress_id"] == first.json()["progress_id"]
    active_rows = [
        row
        for row in env.level_repo.rows
        if row.student_id == student_id
        and row.program_id == env.program_id
        and row.status == "active"
    ]
    assert len(active_rows) == 1


# ---------------------------------------------------------------------------
# Rejection path
# ---------------------------------------------------------------------------


def test_reject_levelup_blocks_progression_and_saves_reason(env):
    student_id = "st-reject-1"
    reason = "Serve consistency not yet at standard"

    assert _place(env, student_id).status_code == 201
    _pass_all_level1_skills(env, student_id)
    rec = _recommend(env, student_id)

    reject = env.client.post(
        f"/api/v2/admin/level-up/{rec.rec_id}/reject",
        json={"rejection_reason": reason},
    )
    assert reject.status_code == 200, reject.text
    rejected = reject.json()
    assert rejected["status"] == "REJECTED"
    # No certificate is issued on rejection.
    assert rejected["cert_id"] is None

    # Student does NOT level up — still on Level 1.
    body = _get_progress(env, student_id).json()
    assert body["current_level_id"] == env.level1.level_id
    assert body["current_level_sequence"] == 1

    # No certificate exists.
    certs = env.client.get(f"/api/v2/admin/students/{student_id}/certificates").json()[
        "certificates"
    ]
    assert certs == []

    # Rejection reason is persisted on the recommendation.
    saved = _run(env.rec_repo.get(rec.rec_id))
    assert saved.status == "REJECTED"
    assert saved.rejection_reason == reason


def test_pathway_progress_summary_returns_rows_for_active_students(env):
    assert _place(env, "st-overview-active").status_code == 201

    response = env.client.get(
        "/api/v2/admin/pathway/progress",
        params={"program_id": env.program_id},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["student_id"] for row in body["rows"]] == [
        "st-overview-active",
        "st-overview-unplaced",
    ]
    assert body["rows"][0]["student_name"] == "Alice Flow"
    assert body["rows"][0]["program_name"] == "Badminton Skill Pathway"
    assert body["rows"][0]["next_action"] == "continue_practice"
    assert body["rows"][1]["student_name"] == "Bob New"
    assert body["rows"][1]["next_action"] == "place_in_level"
    assert env.list_admin_students.calls == [
        {"search": None, "status": "active", "limit": 200, "cursor": None}
    ]


def test_pathway_progress_summary_reads_all_admin_student_pages(env):
    students = env.list_admin_students.students
    env.list_admin_students.pages = {
        None: ([students[0]], "page-2"),
        "page-2": ([students[1]], None),
    }
    assert _place(env, "st-overview-active").status_code == 201

    response = env.client.get(
        "/api/v2/admin/pathway/progress",
        params={"program_id": env.program_id},
    )

    assert response.status_code == 200, response.text
    assert [row["student_id"] for row in response.json()["rows"]] == [
        "st-overview-active",
        "st-overview-unplaced",
    ]
    assert env.list_admin_students.calls == [
        {"search": None, "status": "active", "limit": 200, "cursor": None},
        {"search": None, "status": "active", "limit": 200, "cursor": "page-2"},
    ]


def test_pathway_progress_summary_filters_by_next_action_after_summaries(env):
    assert _place(env, "st-overview-active").status_code == 201

    response = env.client.get(
        "/api/v2/admin/pathway/progress",
        params={"program_id": env.program_id, "next_action": "place_in_level"},
    )

    assert response.status_code == 200, response.text
    assert [row["student_id"] for row in response.json()["rows"]] == ["st-overview-unplaced"]


def test_pathway_progress_summary_unknown_program_returns_404(env):
    response = env.client.get(
        "/api/v2/admin/pathway/progress",
        params={"program_id": "missing-program"},
    )

    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# Persona enforcement
# ---------------------------------------------------------------------------


def test_non_admin_persona_gets_404(env):
    coach_app = _build_app(
        env.use_cases,
        AuthClaims(
            user_id="coach-1",
            email="coach@example.com",
            academy_id=ACADEMY_ID,
            roles=("coach",),
        ),
    )
    coach_client = TestClient(coach_app)
    r = coach_client.get(
        "/api/v2/admin/students/st-x/progress",
        params={"program_id": env.program_id},
    )
    assert r.status_code == 404, r.text
