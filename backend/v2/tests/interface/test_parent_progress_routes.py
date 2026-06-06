"""Interface tests for parent skill-progress routes.

Uses a standalone mini FastAPI app with fake in-memory repos.
No Mongo, no real auth.

Routes covered:
- GET /api/v2/parent/students/{id}/skill-progress → 200 for own child
- GET /api/v2/parent/students/{id}/skill-progress → 403 for another parent's child
- GET /api/v2/parent/students/{id}/certificates   → 200
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from backend.v2.contexts.student_progress.application.use_cases.get_progress_summary import (
    ProgressSummaryRequest,
)
from backend.v2.contexts.student_progress.application.use_cases.get_student_progress import (
    GetStudentCertificates,
    GetStudentProgress,
)
from backend.v2.contexts.student_progress.domain.models import (
    LevelUpRecommendation,
    SkillCertificate,
    StudentLevelProgress,
    StudentSkillProgress,
)
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.progress_skill_routes import router as progress_skill_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.ids import new_ulid

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

ACADEMY_ID = "test-academy"
PARENT_ID = "parent-001"
OTHER_PARENT_ID = "parent-002"
OWN_STUDENT_ID = "student-owned-001"
OTHER_STUDENT_ID = "student-other-001"
PROGRAM_ID = "prog-001"
LEVEL_ID = "level-001"

# ---------------------------------------------------------------------------
# Fake repos
# ---------------------------------------------------------------------------


class _FakeOwnershipStore:
    """Maps student_id → parent_id for authorization checks."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    def parent_of(self, student_id: str) -> str | None:
        return self._mapping.get(student_id)


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
        pass

    async def list_for_student(self, student_id: str) -> list[StudentLevelProgress]:
        return [p for p in self._store.values() if p.student_id == student_id]


class _FakeSkillProgressRepo:
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], StudentSkillProgress] = {}

    async def save(self, sp: StudentSkillProgress) -> None:
        self._store[(sp.student_id, sp.skill_id)] = sp

    async def upsert(self, sp: StudentSkillProgress) -> StudentSkillProgress:
        self._store[(sp.student_id, sp.skill_id)] = sp
        return sp

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


class _FakeCertificateRepo:
    def __init__(self) -> None:
        self._store: list[SkillCertificate] = []

    async def save(self, cert: SkillCertificate) -> None:
        self._store.append(cert)

    async def list_for_student(self, student_id: str) -> list[SkillCertificate]:
        return [c for c in self._store if c.student_id == student_id]


class _FakeLevelUpRepo:
    async def save(self, rec: LevelUpRecommendation) -> None:
        pass

    async def update_status(self, *args: object, **kwargs: object) -> None:
        pass

    async def get(self, rec_id: str) -> LevelUpRecommendation | None:
        return None

    async def get_active_for_student(
        self, student_id: str, program_id: str
    ) -> LevelUpRecommendation | None:
        return None

    async def list_pending(self) -> list[LevelUpRecommendation]:
        return []


class _FakeSkillLookup:
    async def get_skill(self, skill_id: str) -> object | None:
        return None

    async def get_level(self, level_id: str) -> object | None:
        return None

    async def list_skills_for_level(self, level_id: str) -> list[object]:
        return []

    async def get_next_level(self, program_id: str, current_sequence: int) -> object | None:
        return None


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _build_parent_app(*, auth_parent_id: str = PARENT_ID) -> FastAPI:
    level_progress_repo = _FakeLevelProgressRepo()
    skill_progress_repo = _FakeSkillProgressRepo()
    cert_repo = _FakeCertificateRepo()
    level_up_repo = _FakeLevelUpRepo()
    skill_lookup = _FakeSkillLookup()

    # Ownership: OWN_STUDENT_ID belongs to PARENT_ID
    ownership = _FakeOwnershipStore({OWN_STUDENT_ID: PARENT_ID})

    # Seed active level for OWN_STUDENT_ID
    import asyncio

    now = datetime.now(UTC)
    active = StudentLevelProgress(
        progress_id=str(new_ulid()),
        academy_id=ACADEMY_ID,
        student_id=OWN_STUDENT_ID,
        program_id=PROGRAM_ID,
        level_id=LEVEL_ID,
        status="active",
        started_at=now,
        completed_at=None,
        created_at=now,
    )
    asyncio.get_event_loop().run_until_complete(level_progress_repo.save(active))

    # Seed a certificate for OWN_STUDENT_ID
    cert = SkillCertificate(
        cert_id=str(new_ulid()),
        academy_id=ACADEMY_ID,
        student_id=OWN_STUDENT_ID,
        program_id=PROGRAM_ID,
        level_id=LEVEL_ID,
        cert_number="TEST-CERT-001",
        student_name="Test Student",
        level_name="Grip and Control",
        program_name="Badminton Skill Pathway",
        completed_at=now,
        issued_by="admin-1",
        issued_at=now,
    )
    asyncio.get_event_loop().run_until_complete(cert_repo.save(cert))

    # Use cases
    get_progress = GetStudentProgress(
        level_progress=level_progress_repo,
        skill_progress=skill_progress_repo,
        recommendations=level_up_repo,
        certificates=cert_repo,
        skill_lookup=skill_lookup,
    )
    get_certs = GetStudentCertificates(certificates=cert_repo)

    app = FastAPI()
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id=auth_parent_id,
        email="parent@example.com",
        academy_id=ACADEMY_ID,
        roles=("parent",),
    )

    def _check_owns_student(student_id: str, parent_id: str) -> None:
        owner = ownership.parent_of(student_id)
        if owner != parent_id:
            raise HTTPException(status_code=403, detail="not your child")

    @app.get("/api/v2/parent/students/{student_id}/skill-progress")
    async def skill_progress(
        student_id: str,
        program_id: str = PROGRAM_ID,
        request: Request = None,  # type: ignore[assignment]
    ) -> dict:
        claims: AuthClaims = app.dependency_overrides[get_auth_claims]()
        _check_owns_student(student_id, claims.user_id)
        summary = await get_progress.execute(student_id, program_id)
        return summary.model_dump(mode="json")

    @app.get("/api/v2/parent/students/{student_id}/certificates")
    async def certificates(
        student_id: str,
        request: Request = None,  # type: ignore[assignment]
    ) -> dict:
        claims: AuthClaims = app.dependency_overrides[get_auth_claims]()
        _check_owns_student(student_id, claims.user_id)
        certs = await get_certs.execute(student_id)
        return {"certificates": [c.model_dump(mode="json") for c in certs]}

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_skill_progress_own_child_returns_200():
    app = _build_parent_app(auth_parent_id=PARENT_ID)
    client = TestClient(app)
    r = client.get(f"/api/v2/parent/students/{OWN_STUDENT_ID}/skill-progress")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["student_id"] == OWN_STUDENT_ID
    assert body["program_id"] == PROGRAM_ID


def test_skill_progress_other_childs_returns_403():
    # Other parent trying to view OWN_STUDENT_ID (belongs to PARENT_ID)
    app = _build_parent_app(auth_parent_id=OTHER_PARENT_ID)
    client = TestClient(app)
    r = client.get(f"/api/v2/parent/students/{OWN_STUDENT_ID}/skill-progress")
    assert r.status_code == 403, r.text


def test_skill_progress_unknown_student_returns_403():
    # Unknown student has no parent mapping → 403
    app = _build_parent_app(auth_parent_id=PARENT_ID)
    client = TestClient(app)
    r = client.get(f"/api/v2/parent/students/{OTHER_STUDENT_ID}/skill-progress")
    assert r.status_code == 403, r.text


def test_certificates_own_child_returns_200():
    app = _build_parent_app(auth_parent_id=PARENT_ID)
    client = TestClient(app)
    r = client.get(f"/api/v2/parent/students/{OWN_STUDENT_ID}/certificates")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "certificates" in body
    assert len(body["certificates"]) == 1
    assert body["certificates"][0]["cert_number"] == "TEST-CERT-001"


def test_certificates_other_childs_returns_403():
    app = _build_parent_app(auth_parent_id=OTHER_PARENT_ID)
    client = TestClient(app)
    r = client.get(f"/api/v2/parent/students/{OWN_STUDENT_ID}/certificates")
    assert r.status_code == 403, r.text


def test_skill_progress_summary_has_expected_fields():
    app = _build_parent_app(auth_parent_id=PARENT_ID)
    client = TestClient(app)
    r = client.get(f"/api/v2/parent/students/{OWN_STUDENT_ID}/skill-progress")
    assert r.status_code == 200, r.text
    body = r.json()
    for field in ("student_id", "program_id", "total_skills", "passed_skills", "certificates"):
        assert field in body, f"missing field: {field}"


class _Dumpable:
    def __init__(self, **values: object) -> None:
        self._values = values

    def model_dump(self, *args: object, **kwargs: object) -> dict[str, object]:
        return self._values


class _CallableSpy:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def __call__(self, *args: object, **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        return self.result


class _ExecuteSpy:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def execute(self, *args: object, **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        return self.result


def _parent_claims() -> AuthClaims:
    return AuthClaims(
        user_id=PARENT_ID,
        email="parent@example.com",
        academy_id=ACADEMY_ID,
        roles=("parent",),
    )


def _build_real_parent_progress_app(
    *,
    children: list[dict[str, object]],
    program: object | None = None,
) -> tuple[FastAPI, SimpleNamespace]:
    list_children = _CallableSpy(children)
    get_program = _ExecuteSpy(
        program
        if program is not None
        else _Dumpable(program_id=PROGRAM_ID, name="Badminton Skill Pathway")
    )
    get_progress_summary = _ExecuteSpy(
        _Dumpable(
            student_id=OWN_STUDENT_ID,
            student_name="Owned Student",
            program_id=PROGRAM_ID,
            program_name="Badminton Skill Pathway",
            next_action="continue_practice",
        )
    )
    use_cases = SimpleNamespace(
        list_children_for_parent=list_children,
        curriculum=SimpleNamespace(get_program=get_program),
        student_progress=SimpleNamespace(get_progress_summary=get_progress_summary),
    )

    app = FastAPI()
    app.include_router(progress_skill_router, prefix="/api/v2/parent")
    app.dependency_overrides[get_auth_claims] = _parent_claims
    app.dependency_overrides[get_parent_use_cases] = lambda: use_cases

    return app, SimpleNamespace(
        list_children=list_children,
        get_program=get_program,
        get_progress_summary=get_progress_summary,
    )


def test_parent_progress_summary_returns_owned_children_rows() -> None:
    app, spies = _build_real_parent_progress_app(
        children=[
            {
                "student_id": OWN_STUDENT_ID,
                "full_name": "Owned Student",
                "status": "active",
            }
        ]
    )
    client = TestClient(app)

    response = client.get(
        "/api/v2/parent/progress/summary",
        params={"program_id": PROGRAM_ID},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["student_id"] == OWN_STUDENT_ID
    assert row["student_name"] == "Owned Student"
    assert row["program_id"] == PROGRAM_ID
    assert row["program_name"] == "Badminton Skill Pathway"
    assert row["next_action"] == "continue_practice"
    assert spies.list_children.calls == [((PARENT_ID,), {})]
    assert spies.get_program.calls == [((PROGRAM_ID,), {})]
    assert spies.get_progress_summary.calls == [
        (
            (
                ProgressSummaryRequest(
                    student_id=OWN_STUDENT_ID,
                    student_name="Owned Student",
                    program_id=PROGRAM_ID,
                    program_name="Badminton Skill Pathway",
                ),
            ),
            {},
        )
    ]


def test_parent_progress_summary_no_children_returns_empty_rows() -> None:
    app, spies = _build_real_parent_progress_app(children=[])
    client = TestClient(app)

    response = client.get(
        "/api/v2/parent/progress/summary",
        params={"program_id": PROGRAM_ID},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"rows": []}
    assert spies.get_program.calls == []
    assert spies.get_progress_summary.calls == []


def test_parent_progress_summary_missing_program_id_returns_422() -> None:
    app, spies = _build_real_parent_progress_app(
        children=[
            {
                "student_id": OWN_STUDENT_ID,
                "full_name": "Owned Student",
                "status": "active",
            }
        ],
    )
    client = TestClient(app)

    response = client.get("/api/v2/parent/progress/summary")

    assert response.status_code == 422, response.text
    assert spies.list_children.calls == []
    assert spies.get_program.calls == []
    assert spies.get_progress_summary.calls == []


def test_parent_progress_summary_unknown_program_returns_404() -> None:
    app, spies = _build_real_parent_progress_app(
        children=[
            {
                "student_id": OWN_STUDENT_ID,
                "full_name": "Owned Student",
                "status": "active",
            }
        ],
    )
    spies.get_program.result = None
    client = TestClient(app)

    response = client.get(
        "/api/v2/parent/progress/summary",
        params={"program_id": "missing-program"},
    )

    assert response.status_code == 404, response.text
    assert spies.get_progress_summary.calls == []
