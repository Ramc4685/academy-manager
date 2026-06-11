# Session Skill Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-session students × skills board for admin and coach with one-tap status updates and quick pass, per `docs/superpowers/specs/2026-06-09-session-skill-board-design.md`.

**Architecture:** One shared application query (`GetSkillBoard`) in the `student_progress` context, exposed through two persona-shaped BFF routes (admin + coach). Zero new mutation endpoints — the board reuses existing status/test/level-up endpoints. Frontend is one shared presentation-only component with persona API adapters; coach surface is mobile-first (bottom-sheet editor, by-skill drill mode).

**Tech Stack:** FastAPI + Motor (v2 DDD layout), Pydantic frozen models, pytest fake-repo interface tests, Next.js App Router + React Query + Tailwind, Playwright.

**Branch/worktree:** create `feat/session-skill-board` off `main` (use superpowers:using-git-worktrees). Backend venv stays at `backend/.venv` (shared, not per-worktree).

**Verification baseline (run before Task 1):**
```bash
cd backend && source .venv/bin/activate && pytest v2/tests -q && ruff check v2 && lint-imports --config pyproject.toml
```
Expected: all pass (baseline ~919+ passing).

---

## Conventions the engineer must follow

- All domain/read models: `model_config = {"frozen": True}` Pydantic.
- Application layer imports ports (Protocols) only — never `infrastructure/`.
- Interface (BFF) layer imports use cases + commands only — never repos, never Mongo.
- Repos extend `TenantScopedRepository` (`backend/v2/shared/tenancy.py`); `_find_many`/`_find_one` auto-inject `academy_id`. Never hand-write `academy_id` filters.
- Interface tests use the standalone-FastAPI-app + fake-repo pattern from `backend/v2/tests/interface/test_coach_skill_routes.py` (no Mongo, no real auth).
- Commit after every green task. Run `ruff format v2` before each backend commit.

---

### Task 1: `GetSkillBoard` read models + use case (TDD)

**Files:**
- Modify: `backend/v2/contexts/student_progress/domain/models.py` (append read models at end)
- Modify: `backend/v2/contexts/student_progress/application/ports.py` (add one Protocol method)
- Create: `backend/v2/contexts/student_progress/application/use_cases/get_skill_board.py`
- Test: `backend/v2/tests/contexts/student_progress/test_skill_board.py`

- [ ] **Step 1: Write the failing test**

Create `backend/v2/tests/contexts/student_progress/test_skill_board.py`:

```python
"""Use-case tests for GetSkillBoard (fake repos, no Mongo)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.v2.contexts.student_progress.application.use_cases.get_skill_board import (
    GetSkillBoard,
    SkillBoardRequest,
)
from backend.v2.contexts.student_progress.domain.models import (
    SkillBoardStudentRef,
    StudentLevelProgress,
    StudentSkillProgress,
)

NOW = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)
PROGRAM_ID = "prog-001"
LEVEL_1 = "level-001"
LEVEL_2 = "level-002"


def _level_progress(student_id: str, level_id: str) -> StudentLevelProgress:
    return StudentLevelProgress(
        progress_id=f"lp-{student_id}",
        academy_id="test-academy",
        student_id=student_id,
        program_id=PROGRAM_ID,
        level_id=level_id,
        status="active",
        started_at=NOW,
        created_at=NOW,
    )


def _skill_progress(
    student_id: str, skill_id: str, level_id: str, status: str
) -> StudentSkillProgress:
    return StudentSkillProgress(
        skill_progress_id=f"sp-{student_id}-{skill_id}",
        academy_id="test-academy",
        student_id=student_id,
        skill_id=skill_id,
        level_id=level_id,
        program_id=PROGRAM_ID,
        status=status,  # type: ignore[arg-type]
        last_updated_at=NOW,
        last_updated_by="coach-001",
    )


class _FakeLevelProgressRepo:
    def __init__(self, rows: list[StudentLevelProgress]) -> None:
        self._rows = rows

    async def get_active(self, student_id: str, program_id: str) -> StudentLevelProgress | None:
        for row in self._rows:
            if row.student_id == student_id and row.program_id == program_id:
                return row
        return None


class _FakeSkillProgressRepo:
    def __init__(self, rows: list[StudentSkillProgress]) -> None:
        self._rows = rows

    async def list_for_students(
        self, student_ids: list[str], level_id: str
    ) -> list[StudentSkillProgress]:
        return [
            row
            for row in self._rows
            if row.student_id in student_ids and row.level_id == level_id
        ]


class _FakeRecommendationRepo:
    def __init__(self, by_student: dict[str, object] | None = None) -> None:
        self._by_student = by_student or {}

    async def get_active_for_student(self, student_id: str, program_id: str) -> object | None:
        return self._by_student.get(student_id)


class _FakeSkillLookup:
    """Levels and skills keyed by level_id."""

    def __init__(self) -> None:
        self._levels = {
            LEVEL_1: SimpleNamespace(level_id=LEVEL_1, name="Grip and Control", sequence=1),
            LEVEL_2: SimpleNamespace(level_id=LEVEL_2, name="Net Play", sequence=2),
        }
        self._skills = {
            LEVEL_1: [
                SimpleNamespace(
                    skill_id="skill-a", name="Forehand grip", sequence=1, is_required=True
                ),
                SimpleNamespace(
                    skill_id="skill-b", name="Backhand grip", sequence=2, is_required=True
                ),
                SimpleNamespace(
                    skill_id="skill-c", name="Low serve", sequence=3, is_required=False
                ),
            ],
            LEVEL_2: [
                SimpleNamespace(skill_id="skill-d", name="Net shot", sequence=1, is_required=True),
            ],
        }

    async def get_level(self, level_id: str) -> object | None:
        return self._levels.get(level_id)

    async def list_skills_for_level(self, level_id: str) -> list[object]:
        return self._skills.get(level_id, [])


def _use_case(
    level_rows: list[StudentLevelProgress],
    skill_rows: list[StudentSkillProgress],
    recs: dict[str, object] | None = None,
) -> GetSkillBoard:
    return GetSkillBoard(
        level_progress=_FakeLevelProgressRepo(level_rows),
        skill_progress=_FakeSkillProgressRepo(skill_rows),
        recommendations=_FakeRecommendationRepo(recs),
        skill_lookup=_FakeSkillLookup(),
    )


def _request(*refs: tuple[str, str]) -> SkillBoardRequest:
    return SkillBoardRequest(
        students=tuple(SkillBoardStudentRef(student_id=s, student_name=n) for s, n in refs),
        program_id=PROGRAM_ID,
        program_name="Skill Pathway",
    )


@pytest.mark.asyncio
async def test_groups_students_by_level_with_statuses() -> None:
    use_case = _use_case(
        [_level_progress("stu-1", LEVEL_1), _level_progress("stu-2", LEVEL_1)],
        [
            _skill_progress("stu-1", "skill-a", LEVEL_1, "PASSED"),
            _skill_progress("stu-1", "skill-b", LEVEL_1, "PRACTICING"),
            _skill_progress("stu-2", "skill-a", LEVEL_1, "TEST_READY"),
        ],
    )
    board = await use_case.execute(_request(("stu-1", "Netra"), ("stu-2", "Jaya")))

    assert board.program_id == PROGRAM_ID
    assert len(board.groups) == 1
    group = board.groups[0]
    assert group.level_id == LEVEL_1
    assert group.level_name == "Grip and Control"
    assert [s.skill_id for s in group.skills] == ["skill-a", "skill-b", "skill-c"]

    row1 = next(r for r in group.students if r.student_id == "stu-1")
    assert row1.statuses["skill-a"].status == "PASSED"
    assert row1.statuses["skill-b"].status == "PRACTICING"
    assert row1.statuses["skill-c"].status == "NOT_STARTED"
    assert row1.required_passed == 1
    assert row1.required_total == 2
    assert row1.total_passed == 1
    assert row1.total_count == 3


@pytest.mark.asyncio
async def test_mixed_levels_produce_multiple_groups_sorted_by_sequence() -> None:
    use_case = _use_case(
        [_level_progress("stu-1", LEVEL_2), _level_progress("stu-2", LEVEL_1)],
        [],
    )
    board = await use_case.execute(_request(("stu-1", "Netra"), ("stu-2", "Jaya")))

    assert [g.level_id for g in board.groups] == [LEVEL_1, LEVEL_2]
    assert [g.sequence for g in board.groups] == [1, 2]


@pytest.mark.asyncio
async def test_unplaced_students_listed_separately() -> None:
    use_case = _use_case([_level_progress("stu-1", LEVEL_1)], [])
    board = await use_case.execute(_request(("stu-1", "Netra"), ("stu-3", "Aryan")))

    assert len(board.groups) == 1
    assert [u.student_id for u in board.unplaced] == ["stu-3"]
    assert board.unplaced[0].student_name == "Aryan"


@pytest.mark.asyncio
async def test_level_up_status_included_per_student() -> None:
    rec = SimpleNamespace(status="RECOMMENDED")
    use_case = _use_case(
        [_level_progress("stu-1", LEVEL_1)],
        [],
        recs={"stu-1": rec},
    )
    board = await use_case.execute(_request(("stu-1", "Netra")))
    assert board.groups[0].students[0].level_up_status == "RECOMMENDED"


@pytest.mark.asyncio
async def test_empty_roster_returns_empty_board() -> None:
    use_case = _use_case([], [])
    board = await use_case.execute(_request())
    assert board.groups == []
    assert board.unplaced == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && source .venv/bin/activate
pytest v2/tests/contexts/student_progress/test_skill_board.py -q
```
Expected: FAIL — `ModuleNotFoundError: ... get_skill_board`.

- [ ] **Step 3: Add read models**

Append to `backend/v2/contexts/student_progress/domain/models.py` (after `SkillPassportEntry`):

```python
class SkillBoardStudentRef(BaseModel):
    """Minimal student identity passed into / out of the skill board query."""

    model_config = {"frozen": True}

    student_id: str
    student_name: str


class SkillBoardCell(BaseModel):
    """One student × skill cell."""

    model_config = {"frozen": True}

    status: SkillStatus = "NOT_STARTED"
    last_updated_at: datetime | None = None


class SkillBoardSkill(BaseModel):
    """Skill column metadata for one level group."""

    model_config = {"frozen": True}

    skill_id: str
    name: str
    sequence: int
    is_required: bool


class SkillBoardStudentRow(BaseModel):
    """One student row inside a level group."""

    model_config = {"frozen": True}

    student_id: str
    student_name: str
    statuses: dict[str, SkillBoardCell]
    required_passed: int
    required_total: int
    total_passed: int
    total_count: int
    level_up_status: LevelUpStatus | None = None


class SkillBoardLevelGroup(BaseModel):
    """All students currently in one level, with that level's skills."""

    model_config = {"frozen": True}

    level_id: str
    level_name: str
    sequence: int
    skills: list[SkillBoardSkill]
    students: list[SkillBoardStudentRow]


class SkillBoardResult(BaseModel):
    """Full session skill board."""

    model_config = {"frozen": True}

    program_id: str
    program_name: str
    groups: list[SkillBoardLevelGroup]
    unplaced: list[SkillBoardStudentRef]
```

- [ ] **Step 4: Add the batch port method**

In `backend/v2/contexts/student_progress/application/ports.py`, add to `StudentSkillProgressRepository`:

```python
    async def list_for_students(
        self, student_ids: list[str], level_id: str
    ) -> list[StudentSkillProgress]: ...
```

- [ ] **Step 5: Write the use case**

Create `backend/v2/contexts/student_progress/application/use_cases/get_skill_board.py`:

```python
"""Use case: build the session skill board (students × skills, grouped by level)."""

from __future__ import annotations

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    LevelUpRecommendationRepository,
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.models import (
    SkillBoardCell,
    SkillBoardLevelGroup,
    SkillBoardResult,
    SkillBoardSkill,
    SkillBoardStudentRef,
    SkillBoardStudentRow,
)


class SkillBoardRequest(BaseModel):
    model_config = {"frozen": True}

    students: tuple[SkillBoardStudentRef, ...]
    program_id: str
    program_name: str


class GetSkillBoard:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        recommendations: LevelUpRecommendationRepository,
        skill_lookup: SkillLookup,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._recommendations = recommendations
        self._skill_lookup = skill_lookup

    async def execute(self, request: SkillBoardRequest) -> SkillBoardResult:
        by_level: dict[str, list[SkillBoardStudentRef]] = {}
        unplaced: list[SkillBoardStudentRef] = []

        for ref in request.students:
            active = await self._level_progress.get_active(ref.student_id, request.program_id)
            if active is None:
                unplaced.append(ref)
            else:
                by_level.setdefault(active.level_id, []).append(ref)

        groups: list[SkillBoardLevelGroup] = []
        for level_id, refs in by_level.items():
            level = await self._skill_lookup.get_level(level_id)
            skills = await self._skill_lookup.list_skills_for_level(level_id)
            skill_cols = sorted(
                (
                    SkillBoardSkill(
                        skill_id=str(skill.skill_id),  # type: ignore[attr-defined]
                        name=str(getattr(skill, "name", "")),
                        sequence=int(getattr(skill, "sequence", 0)),
                        is_required=bool(getattr(skill, "is_required", True)),
                    )
                    for skill in skills
                ),
                key=lambda s: s.sequence,
            )

            progress_rows = await self._skill_progress.list_for_students(
                [ref.student_id for ref in refs], level_id
            )
            cells_by_student: dict[str, dict[str, SkillBoardCell]] = {}
            for row in progress_rows:
                cells_by_student.setdefault(row.student_id, {})[row.skill_id] = SkillBoardCell(
                    status=row.status,
                    last_updated_at=row.last_updated_at,
                )

            student_rows: list[SkillBoardStudentRow] = []
            for ref in refs:
                cells = cells_by_student.get(ref.student_id, {})
                statuses = {
                    col.skill_id: cells.get(col.skill_id, SkillBoardCell())
                    for col in skill_cols
                }
                required = [col for col in skill_cols if col.is_required]
                rec = await self._recommendations.get_active_for_student(
                    ref.student_id, request.program_id
                )
                student_rows.append(
                    SkillBoardStudentRow(
                        student_id=ref.student_id,
                        student_name=ref.student_name,
                        statuses=statuses,
                        required_passed=sum(
                            1 for col in required if statuses[col.skill_id].status == "PASSED"
                        ),
                        required_total=len(required),
                        total_passed=sum(
                            1 for col in skill_cols if statuses[col.skill_id].status == "PASSED"
                        ),
                        total_count=len(skill_cols),
                        level_up_status=getattr(rec, "status", None) if rec else None,
                    )
                )
            student_rows.sort(key=lambda r: r.student_name.lower())

            groups.append(
                SkillBoardLevelGroup(
                    level_id=level_id,
                    level_name=str(getattr(level, "name", level_id)),
                    sequence=int(getattr(level, "sequence", 0)),
                    skills=skill_cols,
                    students=student_rows,
                )
            )

        groups.sort(key=lambda g: g.sequence)
        return SkillBoardResult(
            program_id=request.program_id,
            program_name=request.program_name,
            groups=groups,
            unplaced=unplaced,
        )
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest v2/tests/contexts/student_progress/test_skill_board.py -q
```
Expected: 5 passed.

- [ ] **Step 7: Format and commit**

```bash
ruff format v2 && ruff check v2
git add backend/v2/contexts/student_progress backend/v2/tests/contexts/student_progress/test_skill_board.py
git commit -m "feat(skill-board): GetSkillBoard read model and use case"
```

---

### Task 2: Mongo batch read + composition wiring

**Files:**
- Modify: `backend/v2/contexts/student_progress/infrastructure/mongo_skill_progress_repo.py`
- Modify: `backend/v2/composition/pathway.py`

- [ ] **Step 1: Implement the repo method**

In `mongo_skill_progress_repo.py`, after `list_for_student_level`:

```python
    async def list_for_students(
        self, student_ids: list[str], level_id: str
    ) -> list[StudentSkillProgress]:
        if not student_ids:
            return []
        cursor = self._find_many(
            {"student_id": {"$in": list(student_ids)}, "level_id": level_id},
            sort=[("student_id", 1), ("skill_id", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
```

Tenant note: `_find_many` injects `academy_id` from `TenantScopedRepository` — do not add it manually. No new index needed: the existing `student_skill_progress` indexes lead with `academy_id` and cover student/level lookups (migration `0121`).

- [ ] **Step 2: Wire into composition**

In `backend/v2/composition/pathway.py`:

Add import (alphabetical with other use-case imports):

```python
from backend.v2.contexts.student_progress.application.use_cases.get_skill_board import (
    GetSkillBoard,
)
```

Add field to `StudentProgressComposition` dataclass:

```python
    get_skill_board: GetSkillBoard
```

Add to the `StudentProgressComposition(...)` return in `compose_student_progress`:

```python
        get_skill_board=GetSkillBoard(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            recommendations=recommendation_repo,
            skill_lookup=skill_lookup,
        ),
```

- [ ] **Step 3: Verify nothing broke**

```bash
pytest v2/tests -q && ruff check v2 && lint-imports --config pyproject.toml
```
Expected: same pass count as baseline + 5 new; lint-imports green.

- [ ] **Step 4: Commit**

```bash
git add backend/v2/contexts/student_progress/infrastructure/mongo_skill_progress_repo.py backend/v2/composition/pathway.py
git commit -m "feat(skill-board): batch skill progress read and composition wiring"
```

---

### Task 3: Coach BFF route (TDD)

**Files:**
- Modify: `backend/v2/interfaces/coach/skill_routes.py`
- Test: `backend/v2/tests/interface/test_coach_skill_routes.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/v2/tests/interface/test_coach_skill_routes.py`. Reuse the module's existing fixtures/constants (`ACADEMY_ID`, `SESSION_ID`, `STUDENT_ID`, `PROGRAM_ID`, fake repos, app/client construction). Read the existing file first — its client fixture builds `CoachUseCases` with fakes. Extend that composition fake with a `get_skill_board` attribute built exactly like Task 2's wiring but from the file's fake repos:

```python
    get_skill_board=GetSkillBoard(
        level_progress=level_progress_repo,
        skill_progress=skill_progress_repo,
        recommendations=recommendation_repo,
        skill_lookup=skill_lookup,
    ),
```

(import `GetSkillBoard` from `backend.v2.contexts.student_progress.application.use_cases.get_skill_board`). The file's fake skill-progress repo needs a `list_for_students` method — same in-memory filter as Task 1's fake.

New tests:

```python
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
```

If `client_unassigned` / `client_parent_persona` fixtures don't exist in the file, build them the same way the existing `client` fixture overrides `get_auth_claims` — unassigned: `assigned_sessions.is_coach_assigned` returns `False`; wrong persona: claims with a non-coach persona (mirror however the file's existing auth-failure tests do it — follow the file, don't invent a new mechanism).

- [ ] **Step 2: Run to verify failure**

```bash
pytest v2/tests/interface/test_coach_skill_routes.py -q
```
Expected: new tests FAIL with 404 (route not registered).

- [ ] **Step 3: Add the route**

In `backend/v2/interfaces/coach/skill_routes.py` — add import. The file's convention is to import only from `application.use_cases.*` (never `domain.*`), and `SkillBoardStudentRef` is already imported into `get_skill_board.py`, so import both names from the use-case module:

```python
from backend.v2.contexts.student_progress.application.use_cases.get_skill_board import (
    SkillBoardRequest,
    SkillBoardStudentRef,
)
```

Append route after `get_session_students_progress`:

```python
@router.get("/sessions/{session_id}/skill-board")
async def get_session_skill_board(
    session_id: str,
    program_id: str | None = Query(None),
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    if not await use_cases.assigned_sessions.is_coach_assigned(claims.user_id, session_id):
        raise HTTPException(status_code=404, detail="session not found")

    resolved_program_id = await _resolve_program_id(use_cases, program_id)
    program_name = await _program_name(use_cases, resolved_program_id)
    roster = await use_cases.get_roster.execute(session_id)
    board = await use_cases.student_progress.get_skill_board.execute(
        SkillBoardRequest(
            students=tuple(
                SkillBoardStudentRef(student_id=entry.student_id, student_name=entry.full_name)
                for entry in roster
            ),
            program_id=resolved_program_id,
            program_name=program_name,
        )
    )
    return board.model_dump(mode="json")
```

- [ ] **Step 4: Run tests, format, commit**

```bash
pytest v2/tests/interface/test_coach_skill_routes.py -q && ruff format v2 && ruff check v2
git add backend/v2/interfaces/coach/skill_routes.py backend/v2/tests/interface/test_coach_skill_routes.py
git commit -m "feat(skill-board): coach session skill-board route"
```

---

### Task 4: Admin BFF route (TDD)

**Files:**
- Modify: `backend/v2/interfaces/admin/progress_routes.py`
- Test: `backend/v2/tests/interface/test_admin_skill_board.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `backend/v2/tests/interface/test_admin_skill_board.py` following the standalone-app pattern of `backend/v2/tests/interface/test_admin_pathway.py` (read it first; reuse its claims-override and app construction). The `AdminUseCases` fake needs: `student_progress` composition (with `get_skill_board` built from the Task-1-style fakes), `curriculum` (for `_resolve_program_id` / `_admin_program_name`), and `list_admin_enrollments_for_session` returning:

```python
async def list_admin_enrollments_for_session(session_id: str) -> list[dict[str, object]]:
    return [
        {"student_id": "stu-1", "full_name": "Netra M"},
        {"student_id": "stu-2", "full_name": "Jaya J"},
    ]
```

Seed the fake level-progress repo so stu-1 is placed in LEVEL_1 and stu-2 is not placed.

Tests:

```python
def test_admin_session_skill_board_returns_groups(client: TestClient) -> None:
    response = client.get(
        f"/api/v2/admin/sessions/{SESSION_ID}/skill-board?program_id={PROGRAM_ID}"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["program_name"]
    assert body["groups"][0]["students"][0]["student_id"] == "stu-1"


def test_admin_session_skill_board_includes_unplaced(client: TestClient) -> None:
    response = client.get(
        f"/api/v2/admin/sessions/{SESSION_ID}/skill-board?program_id={PROGRAM_ID}"
    )
    body = response.json()
    assert [u["student_id"] for u in body["unplaced"]] == ["stu-2"]


def test_admin_session_skill_board_wrong_persona(client_coach_persona: TestClient) -> None:
    response = client_coach_persona.get(f"/api/v2/admin/sessions/{SESSION_ID}/skill-board")
    assert response.status_code in (401, 403, 404)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest v2/tests/interface/test_admin_skill_board.py -q
```
Expected: FAIL with 404 (route missing).

- [ ] **Step 3: Add the route**

In `backend/v2/interfaces/admin/progress_routes.py` — add import:

```python
from backend.v2.contexts.student_progress.application.use_cases.get_skill_board import (
    SkillBoardRequest,
    SkillBoardStudentRef,
)
```

Add route (near `get_pathway_progress_overview`, which starts at line ~284):

```python
@router.get("/sessions/{session_id}/skill-board")
async def get_session_skill_board(
    session_id: str,
    program_id: str | None = Query(None),
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")

    resolved_program_id = await _resolve_program_id(use_cases, program_id)
    program_name = await _admin_program_name(use_cases, resolved_program_id)
    rows = await use_cases.list_admin_enrollments_for_session(session_id)  # type: ignore[operator]
    refs = tuple(
        SkillBoardStudentRef(
            student_id=str(row.get("student_id") or ""),
            student_name=str(row.get("full_name") or row.get("student_name") or "(unknown)"),
        )
        for row in rows
        if row.get("student_id")
    )
    board = await use_cases.student_progress.get_skill_board.execute(
        SkillBoardRequest(
            students=refs,
            program_id=resolved_program_id,
            program_name=program_name,
        )
    )
    return board.model_dump(mode="json")
```

Match the exact dependency/auth pattern of the existing routes in that file (e.g. whether claims is named `claims` or `_claims`, and confirm `list_admin_enrollments_for_session` lives on `AdminUseCases` — it is called that way in `backend/v2/interfaces/admin/sessions_routes.py:268-285`; if it lives on a different dep object there, import and use the same dependency the sessions route uses).

- [ ] **Step 4: Run tests, full suite, commit**

```bash
pytest v2/tests/interface/test_admin_skill_board.py -q && pytest v2/tests -q
ruff format v2 && ruff check v2 && lint-imports --config pyproject.toml
git add backend/v2/interfaces/admin/progress_routes.py backend/v2/tests/interface/test_admin_skill_board.py
git commit -m "feat(skill-board): admin session skill-board route"
```

---

### Task 5: Frontend API client

**Files:**
- Modify: `frontend/lib/api/curriculum.ts` (append types + two fetchers)

- [ ] **Step 1: Add types and fetchers**

Append to `frontend/lib/api/curriculum.ts`:

```typescript
// ---------------------------------------------------------------------------
// Session skill board
// ---------------------------------------------------------------------------

export interface SkillBoardCell {
  status: SkillStatus;
  last_updated_at: string | null;
}

export interface SkillBoardSkill {
  skill_id: string;
  name: string;
  sequence: number;
  is_required: boolean;
}

export interface SkillBoardStudentRow {
  student_id: string;
  student_name: string;
  statuses: Record<string, SkillBoardCell>;
  required_passed: number;
  required_total: number;
  total_passed: number;
  total_count: number;
  level_up_status: string | null;
}

export interface SkillBoardLevelGroup {
  level_id: string;
  level_name: string;
  sequence: number;
  skills: SkillBoardSkill[];
  students: SkillBoardStudentRow[];
}

export interface SkillBoard {
  program_id: string;
  program_name: string;
  groups: SkillBoardLevelGroup[];
  unplaced: { student_id: string; student_name: string }[];
}

export function getAdminSessionSkillBoard(
  sessionId: string,
  programId?: string,
): Promise<SkillBoard> {
  const q = programId ? `?program_id=${encodeURIComponent(programId)}` : "";
  return apiFetch<SkillBoard>(
    `/admin/sessions/${encodeURIComponent(sessionId)}/skill-board${q}`,
  );
}

export function getCoachSessionSkillBoard(
  sessionId: string,
  programId?: string,
): Promise<SkillBoard> {
  const q = programId ? `?program_id=${encodeURIComponent(programId)}` : "";
  return apiFetch<SkillBoard>(
    `/coach/sessions/${encodeURIComponent(sessionId)}/skill-board${q}`,
  );
}
```

Match the surrounding file's `apiFetch` call style exactly — copy whatever `getCoachSessionStudentsProgress` (around line 355) does, including any second argument/options it passes.

- [ ] **Step 2: Typecheck and commit**

```bash
cd frontend && pnpm typecheck && pnpm lint
git add frontend/lib/api/curriculum.ts
git commit -m "feat(skill-board): typed skill-board fetchers"
```

---

### Task 6: Shared cell editor (bottom sheet / popover)

**Files:**
- Create: `frontend/components/pathway/skill-cell-editor.tsx`

Presentation-only: receives the selected cell context and callbacks; owns zero API calls.

- [ ] **Step 1: Create the component**

```tsx
"use client";

import { useState } from "react";
import { X } from "lucide-react";

import type { SkillBoardSkill, SkillStatus } from "@/lib/api/curriculum";

const SETTABLE_STATUSES: { value: SkillStatus; label: string }[] = [
  { value: "INTRODUCED", label: "Introduced" },
  { value: "LEARNING", label: "Learning" },
  { value: "PRACTICING", label: "Practicing" },
  { value: "TEST_READY", label: "Test ready" },
  { value: "NEEDS_REVIEW", label: "Needs review" },
];

export interface SkillCellTarget {
  studentId: string;
  studentName: string;
  skill: SkillBoardSkill;
  levelId: string;
  status: SkillStatus;
}

export function SkillCellEditor({
  target,
  isPending,
  error,
  onSetStatus,
  onQuickPass,
  onRecordTest,
  onClose,
}: {
  target: SkillCellTarget;
  isPending: boolean;
  error: string | null;
  onSetStatus: (status: SkillStatus) => void;
  onQuickPass: () => void;
  onRecordTest: (attempts: number, successes: number, notes: string) => void;
  onClose: () => void;
}) {
  const [showTestForm, setShowTestForm] = useState(false);
  const [attempts, setAttempts] = useState("1");
  const [successes, setSuccesses] = useState("1");
  const [notes, setNotes] = useState("");
  const passed = target.status === "PASSED";

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/30"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-label={`Update ${target.skill.name} for ${target.studentName}`}
        data-testid="skill-cell-editor"
        className="fixed inset-x-0 bottom-0 z-50 rounded-t-2xl border border-neutral-200 bg-white p-4 pb-[max(1rem,env(safe-area-inset-bottom))] shadow-xl sm:inset-x-auto sm:bottom-auto sm:left-1/2 sm:top-1/2 sm:w-[420px] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-2xl dark:border-neutral-800 dark:bg-neutral-900"
      >
        <div className="mb-3 flex items-start justify-between gap-2">
          <div>
            <p className="text-sm font-semibold text-rally-base">{target.studentName}</p>
            <p className="text-xs text-neutral-500">
              {target.skill.name}
              {target.skill.is_required ? " · required" : ""}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="flex h-11 w-11 items-center justify-center rounded-full text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>

        {passed ? (
          <p className="mb-3 rounded-md bg-green-50 p-3 text-sm text-green-700">
            Passed. Record another test to add history.
          </p>
        ) : (
          <div className="mb-3 flex flex-wrap gap-2">
            {SETTABLE_STATUSES.map((s) => (
              <button
                key={s.value}
                disabled={isPending}
                onClick={() => onSetStatus(s.value)}
                className={`min-h-[44px] rounded-full border px-4 text-xs font-medium transition-colors ${
                  target.status === s.value
                    ? "border-blue-600 bg-blue-50 text-blue-700"
                    : "border-neutral-300 text-neutral-600 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-300"
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          {!passed && (
            <button
              disabled={isPending}
              onClick={onQuickPass}
              data-testid="quick-pass"
              className="min-h-[44px] flex-1 rounded-lg bg-green-600 px-3 text-sm font-semibold text-white transition-all active:scale-95 disabled:opacity-50"
            >
              {isPending ? "Saving…" : "Quick pass (1/1 test)"}
            </button>
          )}
          <button
            disabled={isPending}
            onClick={() => setShowTestForm((v) => !v)}
            className="min-h-[44px] flex-1 rounded-lg border border-neutral-300 px-3 text-sm font-medium text-neutral-700 dark:border-neutral-700 dark:text-neutral-300"
          >
            {showTestForm ? "Cancel test" : "Record test…"}
          </button>
        </div>

        {showTestForm && (
          <div className="mt-3 rounded-lg bg-neutral-50 p-3 dark:bg-neutral-800">
            <div className="grid grid-cols-2 gap-2">
              <label className="block">
                <span className="mb-1 block text-[11px] font-medium text-neutral-500">
                  Attempts
                </span>
                <input
                  type="number"
                  min="1"
                  inputMode="numeric"
                  value={attempts}
                  onChange={(e) => setAttempts(e.target.value)}
                  className="min-h-[44px] w-full rounded-md border border-neutral-300 px-2 text-sm"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[11px] font-medium text-neutral-500">
                  Successes
                </span>
                <input
                  type="number"
                  min="0"
                  inputMode="numeric"
                  value={successes}
                  onChange={(e) => setSuccesses(e.target.value)}
                  className="min-h-[44px] w-full rounded-md border border-neutral-300 px-2 text-sm"
                />
              </label>
            </div>
            <label className="mt-2 block">
              <span className="mb-1 block text-[11px] font-medium text-neutral-500">
                Notes (optional)
              </span>
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                className="min-h-[44px] w-full rounded-md border border-neutral-300 px-2 text-sm"
              />
            </label>
            <button
              disabled={isPending}
              onClick={() =>
                onRecordTest(
                  parseInt(attempts, 10) || 1,
                  parseInt(successes, 10) || 0,
                  notes.trim(),
                )
              }
              className="mt-3 min-h-[44px] w-full rounded-lg bg-blue-600 text-sm font-semibold text-white active:scale-95 disabled:opacity-50"
            >
              Save test
            </button>
          </div>
        )}

        {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      </div>
    </>
  );
}
```

- [ ] **Step 2: Typecheck and commit**

```bash
pnpm typecheck && pnpm lint
git add frontend/components/pathway/skill-cell-editor.tsx
git commit -m "feat(skill-board): skill cell editor sheet"
```

---

### Task 7: Shared skill board component

**Files:**
- Create: `frontend/components/pathway/skill-board.tsx`

Presentation-only. Receives `SkillBoard` data plus an `actions` adapter (persona pages own the React Query mutations). Desktop (`md:`) renders the matrix; below `md` it renders by-student / by-skill modes.

- [ ] **Step 1: Create the component**

```tsx
"use client";

import { useState } from "react";

import type {
  SkillBoard,
  SkillBoardLevelGroup,
  SkillBoardSkill,
  SkillBoardStudentRow,
  SkillStatus,
} from "@/lib/api/curriculum";
import { SkillCellEditor, type SkillCellTarget } from "./skill-cell-editor";

export interface SkillBoardActions {
  setStatus: (args: {
    studentId: string;
    skillId: string;
    levelId: string;
    status: SkillStatus;
  }) => Promise<unknown>;
  quickPass: (args: {
    studentId: string;
    skillId: string;
    levelId: string;
  }) => Promise<unknown>;
  recordTest: (args: {
    studentId: string;
    skillId: string;
    levelId: string;
    attempts: number;
    successes: number;
    notes: string;
  }) => Promise<unknown>;
}

const STATUS_DOT: Record<SkillStatus, string> = {
  NOT_STARTED: "border-2 border-neutral-300 bg-transparent",
  INTRODUCED: "bg-neutral-400",
  LEARNING: "bg-amber-400",
  PRACTICING: "bg-amber-500",
  TEST_READY: "bg-blue-500",
  PASSED: "bg-green-500",
  NEEDS_REVIEW: "bg-red-500",
};

const STATUS_SHORT: Record<SkillStatus, string> = {
  NOT_STARTED: "Not started",
  INTRODUCED: "Introduced",
  LEARNING: "Learning",
  PRACTICING: "Practicing",
  TEST_READY: "Test ready",
  PASSED: "Passed",
  NEEDS_REVIEW: "Needs review",
};

export function SkillBoardView({
  board,
  actions,
  renderUnplacedAction,
}: {
  board: SkillBoard;
  actions: SkillBoardActions;
  renderUnplacedAction?: (student: {
    student_id: string;
    student_name: string;
  }) => React.ReactNode;
}) {
  const [target, setTarget] = useState<SkillCellTarget | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>) {
    setIsPending(true);
    setError(null);
    try {
      await fn();
      setTarget(null);
    } catch {
      setError("Update failed. Check connection and retry.");
    } finally {
      setIsPending(false);
    }
  }

  return (
    <div className="space-y-6" data-testid="skill-board">
      {board.groups.length === 0 && board.unplaced.length === 0 && (
        <p className="text-sm text-neutral-500">No students on this roster.</p>
      )}

      {board.groups.map((group) => (
        <LevelGroupSection
          key={group.level_id}
          group={group}
          onCellTap={(student, skill) =>
            setTarget({
              studentId: student.student_id,
              studentName: student.student_name,
              skill,
              levelId: group.level_id,
              status: student.statuses[skill.skill_id]?.status ?? "NOT_STARTED",
            })
          }
        />
      ))}

      {board.unplaced.length > 0 && (
        <div className="rounded-xl border border-dashed border-neutral-300 p-4 dark:border-neutral-700">
          <p className="mb-2 text-sm font-semibold text-neutral-600">Not placed in a level</p>
          <ul className="space-y-2">
            {board.unplaced.map((s) => (
              <li
                key={s.student_id}
                className="flex items-center justify-between gap-2 text-sm"
              >
                <span>{s.student_name}</span>
                {renderUnplacedAction?.(s)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {target && (
        <SkillCellEditor
          target={target}
          isPending={isPending}
          error={error}
          onClose={() => setTarget(null)}
          onSetStatus={(status) =>
            run(() =>
              actions.setStatus({
                studentId: target.studentId,
                skillId: target.skill.skill_id,
                levelId: target.levelId,
                status,
              }),
            )
          }
          onQuickPass={() =>
            run(() =>
              actions.quickPass({
                studentId: target.studentId,
                skillId: target.skill.skill_id,
                levelId: target.levelId,
              }),
            )
          }
          onRecordTest={(attempts, successes, notes) =>
            run(() =>
              actions.recordTest({
                studentId: target.studentId,
                skillId: target.skill.skill_id,
                levelId: target.levelId,
                attempts,
                successes,
                notes,
              }),
            )
          }
        />
      )}
    </div>
  );
}

function LevelGroupSection({
  group,
  onCellTap,
}: {
  group: SkillBoardLevelGroup;
  onCellTap: (student: SkillBoardStudentRow, skill: SkillBoardSkill) => void;
}) {
  const [mode, setMode] = useState<"by-student" | "by-skill">("by-student");
  const [skillId, setSkillId] = useState(group.skills[0]?.skill_id ?? "");
  const activeSkill =
    group.skills.find((s) => s.skill_id === skillId) ?? group.skills[0];

  return (
    <section data-testid={`skill-board-level-${group.sequence}`}>
      <h2 className="mb-2 text-sm font-semibold text-rally-base">
        Level {group.sequence} · {group.level_name}
      </h2>

      {/* Desktop matrix */}
      <div className="hidden overflow-x-auto rounded-xl border border-neutral-200 bg-white md:block dark:border-neutral-800 dark:bg-neutral-900">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-neutral-200 text-neutral-500 dark:border-neutral-800">
              <th className="px-3 py-2 text-left font-medium">Student</th>
              {group.skills.map((skill) => (
                <th key={skill.skill_id} className="px-1 py-2 text-center font-medium">
                  <span title={skill.name}>{skill.name}</span>
                  {skill.is_required && <span className="text-red-500"> *</span>}
                </th>
              ))}
              <th className="px-2 py-2 text-center font-medium">Done</th>
            </tr>
          </thead>
          <tbody>
            {group.students.map((student) => (
              <tr
                key={student.student_id}
                className="border-b border-neutral-100 last:border-0 dark:border-neutral-800"
              >
                <td className="px-3 py-2 font-medium">
                  {student.student_name}
                  {student.required_passed === student.required_total &&
                    student.required_total > 0 && (
                      <span className="ml-2 rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-semibold text-green-700">
                        Ready
                      </span>
                    )}
                </td>
                {group.skills.map((skill) => {
                  const status = student.statuses[skill.skill_id]?.status ?? "NOT_STARTED";
                  return (
                    <td key={skill.skill_id} className="px-1 py-1 text-center">
                      <button
                        aria-label={`${student.student_name} – ${skill.name}: ${STATUS_SHORT[status]}`}
                        onClick={() => onCellTap(student, skill)}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-md hover:bg-neutral-100 dark:hover:bg-neutral-800"
                      >
                        <span className={`h-3.5 w-3.5 rounded-full ${STATUS_DOT[status]}`} />
                      </button>
                    </td>
                  );
                })}
                <td className="px-2 py-2 text-center text-neutral-500">
                  {student.total_passed}/{student.total_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile modes */}
      <div className="md:hidden">
        <div className="mb-3 grid grid-cols-2 gap-1 rounded-lg bg-neutral-100 p-1 dark:bg-neutral-800">
          {(["by-student", "by-skill"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`min-h-[44px] rounded-md text-xs font-semibold ${
                mode === m
                  ? "bg-white text-rally-base shadow-sm dark:bg-neutral-700"
                  : "text-neutral-500"
              }`}
            >
              {m === "by-student" ? "By student" : "By skill"}
            </button>
          ))}
        </div>

        {mode === "by-student" ? (
          <ul className="space-y-2">
            {group.students.map((student) => (
              <li
                key={student.student_id}
                className="rounded-xl border border-neutral-200 bg-white p-3 dark:border-neutral-800 dark:bg-neutral-900"
              >
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-sm font-semibold">{student.student_name}</p>
                  <p className="text-xs text-neutral-500">
                    {student.total_passed}/{student.total_count} passed
                  </p>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {group.skills.map((skill) => {
                    const status = student.statuses[skill.skill_id]?.status ?? "NOT_STARTED";
                    return (
                      <button
                        key={skill.skill_id}
                        onClick={() => onCellTap(student, skill)}
                        className="flex min-h-[44px] items-center gap-1.5 rounded-full border border-neutral-200 px-3 text-[11px] font-medium dark:border-neutral-700"
                      >
                        <span className={`h-2.5 w-2.5 rounded-full ${STATUS_DOT[status]}`} />
                        {skill.name}
                      </button>
                    );
                  })}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div>
            <select
              value={activeSkill?.skill_id ?? ""}
              onChange={(e) => setSkillId(e.target.value)}
              aria-label="Skill to assess"
              className="mb-3 min-h-[44px] w-full rounded-lg border border-neutral-300 px-3 text-sm dark:border-neutral-700 dark:bg-neutral-900"
            >
              {group.skills.map((skill) => (
                <option key={skill.skill_id} value={skill.skill_id}>
                  {skill.sequence}. {skill.name}
                  {skill.is_required ? " (required)" : ""}
                </option>
              ))}
            </select>
            <ul className="space-y-2">
              {activeSkill &&
                group.students.map((student) => {
                  const status =
                    student.statuses[activeSkill.skill_id]?.status ?? "NOT_STARTED";
                  return (
                    <li key={student.student_id}>
                      <button
                        onClick={() => onCellTap(student, activeSkill)}
                        data-testid={`by-skill-student-${student.student_id}`}
                        className="flex min-h-[52px] w-full items-center justify-between rounded-xl border border-neutral-200 bg-white px-4 dark:border-neutral-800 dark:bg-neutral-900"
                      >
                        <span className="text-sm font-semibold">{student.student_name}</span>
                        <span className="flex items-center gap-2 text-xs text-neutral-500">
                          <span className={`h-3 w-3 rounded-full ${STATUS_DOT[status]}`} />
                          {STATUS_SHORT[status]}
                        </span>
                      </button>
                    </li>
                  );
                })}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Typecheck and commit**

```bash
pnpm typecheck && pnpm lint
git add frontend/components/pathway/skill-board.tsx
git commit -m "feat(skill-board): shared skill board component"
```

---

### Task 8: Coach page (mobile-first)

**Files:**
- Modify: `frontend/app/(coach)/coach/sessions/[id]/progress/page.tsx` (replace content)

- [ ] **Step 1: Replace the page**

```tsx
"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getCoachSessionSkillBoard,
  recordTestAttempt,
  updateSkillStatus,
  type SkillStatus,
} from "@/lib/api/curriculum";
import { SkillBoardView, type SkillBoardActions } from "@/components/pathway/skill-board";

export default function CoachSessionProgressPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const programId = searchParams.get("program_id") ?? "";
  const queryClient = useQueryClient();

  const boardKey = ["coach", "skill-board", sessionId, programId || "default"];
  const { data: board, isLoading, isError } = useQuery({
    queryKey: boardKey,
    queryFn: () => getCoachSessionSkillBoard(sessionId, programId || undefined),
    enabled: Boolean(sessionId),
  });

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: boardKey });

  const statusMutation = useMutation({
    mutationFn: (args: {
      studentId: string;
      skillId: string;
      levelId: string;
      status: SkillStatus;
    }) =>
      updateSkillStatus(args.studentId, args.skillId, {
        program_id: board?.program_id ?? "",
        level_id: args.levelId,
        status: args.status,
      }),
    onSettled: invalidate,
  });

  const testMutation = useMutation({
    mutationFn: (args: {
      studentId: string;
      skillId: string;
      levelId: string;
      attempts: number;
      successes: number;
      notes: string;
    }) =>
      recordTestAttempt(args.studentId, args.skillId, {
        program_id: board?.program_id ?? "",
        level_id: args.levelId,
        attempts_count: args.attempts,
        success_count: args.successes,
        notes: args.notes || undefined,
        session_id: sessionId,
      }),
    onSettled: invalidate,
  });

  const actions: SkillBoardActions = {
    setStatus: (args) => statusMutation.mutateAsync(args),
    quickPass: (args) =>
      testMutation.mutateAsync({ ...args, attempts: 1, successes: 1, notes: "Quick pass" }),
    recordTest: (args) => testMutation.mutateAsync(args),
  };

  return (
    <section data-testid="coach-session-progress" className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Session skill board</h1>
        <p className="text-sm text-neutral-500">{board?.program_name ?? ""}</p>
      </div>

      {isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load the skill board.
        </p>
      )}
      {isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-20 animate-pulse rounded-xl bg-neutral-100 dark:bg-neutral-800"
            />
          ))}
        </div>
      ) : board ? (
        <SkillBoardView board={board} actions={actions} />
      ) : null}
    </section>
  );
}
```

Before wiring, check the exact signatures of the coach `updateSkillStatus` / `recordTestAttempt` in `frontend/lib/api/curriculum.ts` — match body key names exactly (`session_id` is accepted by `RecordTestBody`, see `backend/v2/interfaces/coach/skill_routes.py:46-54`; if the frontend type doesn't yet include `session_id`, add it to that request type in the same commit).

- [ ] **Step 2: Typecheck, lint, commit**

```bash
pnpm typecheck && pnpm lint
git add "frontend/app/(coach)/coach/sessions/[id]/progress/page.tsx" frontend/lib/api/curriculum.ts
git commit -m "feat(skill-board): mobile-first coach session board"
```

---

### Task 9: Admin page + roster link

**Files:**
- Create: `frontend/app/(admin)/admin/sessions/[id]/skill-board/page.tsx`
- Modify: `frontend/app/(admin)/admin/sessions/[id]/page.tsx` (roster "x/y skills" text → link, around line 1080)

- [ ] **Step 1: Create the admin page**

```tsx
"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import {
  getAdminSessionSkillBoard,
  recordAdminTestAttempt,
  updateAdminSkillStatus,
  type SkillStatus,
} from "@/lib/api/curriculum";
import { SkillBoardView, type SkillBoardActions } from "@/components/pathway/skill-board";

export default function AdminSessionSkillBoardPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const programId = searchParams.get("program_id") ?? "";
  const queryClient = useQueryClient();

  const boardKey = ["admin", "skill-board", sessionId, programId || "default"];
  const { data: board, isLoading, isError } = useQuery({
    queryKey: boardKey,
    queryFn: () => getAdminSessionSkillBoard(sessionId, programId || undefined),
    enabled: Boolean(sessionId),
  });

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: boardKey });

  const statusMutation = useMutation({
    mutationFn: (args: {
      studentId: string;
      skillId: string;
      levelId: string;
      status: SkillStatus;
    }) =>
      updateAdminSkillStatus(args.studentId, args.skillId, {
        program_id: board?.program_id ?? "",
        level_id: args.levelId,
        status: args.status,
      }),
    onSettled: invalidate,
  });

  const testMutation = useMutation({
    mutationFn: (args: {
      studentId: string;
      skillId: string;
      levelId: string;
      attempts: number;
      successes: number;
      notes: string;
    }) =>
      recordAdminTestAttempt(args.studentId, args.skillId, {
        program_id: board?.program_id ?? "",
        level_id: args.levelId,
        attempts_count: args.attempts,
        success_count: args.successes,
        notes: args.notes || undefined,
      }),
    onSettled: invalidate,
  });

  const actions: SkillBoardActions = {
    setStatus: (args) => statusMutation.mutateAsync(args),
    quickPass: (args) =>
      testMutation.mutateAsync({ ...args, attempts: 1, successes: 1, notes: "Quick pass" }),
    recordTest: (args) => testMutation.mutateAsync(args),
  };

  return (
    <section data-testid="admin-session-skill-board" className="space-y-4">
      <Link
        href={`/admin/sessions/${sessionId}` as Parameters<typeof Link>[0]["href"]}
        className="inline-flex items-center gap-1.5 text-sm text-rally-muted hover:text-rally-ink"
      >
        <ArrowLeft className="size-4" aria-hidden="true" />
        <span>Back to session</span>
      </Link>
      <div>
        <h1 className="text-2xl font-semibold">Skill board</h1>
        <p className="text-sm text-neutral-500">{board?.program_name ?? ""}</p>
      </div>

      {isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load the skill board.
        </p>
      )}
      {isLoading ? (
        <div className="h-40 animate-pulse rounded-xl bg-neutral-100 dark:bg-neutral-800" />
      ) : board ? (
        <SkillBoardView
          board={board}
          actions={actions}
          renderUnplacedAction={(student) => (
            <Link
              href={
                `/admin/students/${student.student_id}/progress?return_to=${encodeURIComponent(
                  `/admin/sessions/${sessionId}/skill-board`,
                )}` as Parameters<typeof Link>[0]["href"]
              }
              className="rounded-md border border-neutral-300 px-3 py-1.5 text-xs font-medium hover:bg-neutral-50"
            >
              Place in level
            </Link>
          )}
        />
      ) : null}
    </section>
  );
}
```

- [ ] **Step 2: Link from the roster**

In `frontend/app/(admin)/admin/sessions/[id]/page.tsx`, find the roster cell that renders the skills count (search for `pathway_skills_completed`, around line 1080). Current shape:

```tsx
{e.pathway_level_name
  ? `${e.pathway_skills_completed ?? 0}/${e.pathway_skills_total ?? 0} skills`
  : /* existing fallback */}
```

Wrap the count in a `Link` to the board, passing `pathway_program_id` when present:

```tsx
{e.pathway_level_name ? (
  <Link
    href={
      `/admin/sessions/${sessionId}/skill-board${
        e.pathway_program_id
          ? `?program_id=${encodeURIComponent(e.pathway_program_id)}`
          : ""
      }` as Parameters<typeof Link>[0]["href"]
    }
    className="text-xs text-blue-600 underline-offset-2 hover:underline"
  >
    {e.pathway_skills_completed ?? 0}/{e.pathway_skills_total ?? 0} skills
  </Link>
) : (
  /* keep the existing non-placed fallback exactly as it is */
)}
```

Adapt variable names to what that file actually has in scope (the row variable is `e`; confirm how the page references the session id — it may be `id` from `useParams` or a prop on the roster component; if the roster table is a child component without the session id, pass it down as a new prop). Keep every other roster behavior untouched.

- [ ] **Step 3: Typecheck, lint, commit**

```bash
pnpm typecheck && pnpm lint
git add "frontend/app/(admin)/admin/sessions/[id]/skill-board/page.tsx" "frontend/app/(admin)/admin/sessions/[id]/page.tsx"
git commit -m "feat(skill-board): admin session skill board page and roster link"
```

---

### Task 10: Playwright mobile smoke + final verification

**Files:**
- Create: `frontend/e2e/specs/skill-board.spec.ts`
- Create: `docs/test-results/active/2026-06-09-session-skill-board.md` (task ledger)

- [ ] **Step 1: Write the smoke spec**

Read an existing spec in `frontend/e2e/specs/` first (e.g. `google-signin-mode.spec.ts`) for the project's auth/setup helpers. The smoke (mobile viewport):

```typescript
import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 390, height: 844 } });

test.describe("coach skill board (mobile)", () => {
  test("by-skill mode renders and opens the cell editor", async ({ page }) => {
    // Requires a seeded local stack (seed_badminton_pathway + a session with
    // a placed roster) and the project's coach auth helper.
    await page.goto("/coach/sessions/SESSION_ID_FROM_SEED/progress");
    await expect(page.getByTestId("skill-board")).toBeVisible();

    await page.getByRole("button", { name: "By skill" }).click();
    await page.getByTestId(/by-skill-student-/).first().click();
    await expect(page.getByTestId("skill-cell-editor")).toBeVisible();
    await expect(page.getByTestId("quick-pass")).toBeVisible();
  });
});
```

If the e2e suite has no seeded-auth path for coach pages, mark the spec `test.skip` with a comment pointing at the seeding requirement and note it in the ledger — do not fake auth inside the spec.

- [ ] **Step 2: Full verification (record results in the ledger)**

```bash
cd backend && source .venv/bin/activate
pytest v2/tests -q                      # expected: baseline + new tests, 0 new failures
ruff check v2 && ruff format --check v2
lint-imports --config pyproject.toml
cd ../frontend
pnpm typecheck && pnpm lint
```

Create `docs/test-results/active/2026-06-09-session-skill-board.md` recording each command + result (follow the format of existing ledgers in that directory, e.g. the entries in `docs/test-results/active/`).

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/specs/skill-board.spec.ts docs/test-results/active/2026-06-09-session-skill-board.md
git commit -m "test(skill-board): mobile smoke spec and verification ledger"
```

---

## Spec coverage checklist (self-review)

- Shared `GetSkillBoard` application query, persona routes admin + coach — Tasks 1–4
- Batch port method, tenant-scoped via `TenantScopedRepository`, zero new mutations — Tasks 1–2
- Mixed-level grouping, unplaced students — Task 1 tests
- Coach auth (assigned-to-session), wrong-persona non-leak — Tasks 3–4 tests
- Quick pass = existing test endpoint, 1/1, "Quick pass" note, session-attributed — Tasks 8–9
- Mobile-first: 44px targets, bottom sheet, by-skill drill mode, no hover dependency — Tasks 6–7
- Admin sub-route + roster link, place-in-level path for unplaced — Task 9
- Level-up "Ready" badge — Task 7
- lint-imports / ruff / typecheck / ledger — Tasks 2, 4, 10

**Intentional small deviations from spec:**

1. The spec's coach editor mentions an inline skill-note field; defer it — coach skill notes remain available on the passport page (existing endpoint untouched). Add later if coaches ask.
2. The spec mentions a row-level "Recommend level up" button on the coach board; the "Ready" badge ships now and the recommend action stays on the passport (one tap away). If Task 8 finishes early, add a row button calling `recommendLevelUp(studentId, board.program_id)` from `frontend/lib/api/curriculum.ts`.
3. Optimistic UI is implemented as pending-state + invalidate-on-settle (mutateAsync with disabled controls), not cache-patching — simpler, still never blocks the coach, and rollback is automatic because the cache is only updated from server truth.
