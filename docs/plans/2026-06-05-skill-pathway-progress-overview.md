# Skill Pathway Progress Overview Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a thin end-to-end Skill Pathway progress overview so admins, coaches, and parents can see each student's current level, skill completion, and next action from one shared backend summary.

**Architecture:** Add a shared student-progress summary query below the persona BFF layer, then expose persona-shaped routes for admin, coach, and parent. Keep business truth in backend use cases; frontend screens only format, filter, and link to existing detailed workflows. Normal level completion remains strict: required skills become `PASSED` through recorded tests, then coach recommendation and admin approval complete the level-up flow.

**Tech Stack:** FastAPI v2, Pydantic, Mongo/Motor repositories with mongomock contract tests, Next.js 15 App Router, React Query, Tailwind/design-system components.

---

## Ground Rules

- Work in a dedicated worktree, not the dirty main checkout.
- Before coding, read `AGENTS.md`, `README.md`, `DEPLOYMENT.md`, `test_result.md`, `docs/agent/backend-api-rules.md`, `docs/agent/frontend-rules.md`, `docs/agent/testing-verification.md`, the design spec, and this plan.
- Create a task ledger with `scripts/dev/test_result.py`.
- Use TDD for behavior changes.
- Commit each task atomically.
- Do not touch unrelated dirty files, especially `scripts/dev/seed_badminton_pathway.py` if it is still dirty in the main checkout.

## Task 0: Create Worktree And Baseline

**Files:**
- No production files.
- Create/update test ledger via CLI.

**Step 1: Create an isolated worktree**

Run from repo root:

```bash
git fetch
git worktree add .worktrees/skill-pathway-progress-overview -b feat/skill-pathway-progress-overview
```

Expected: new worktree on `feat/skill-pathway-progress-overview`.

**Step 2: Enter the worktree and inspect status**

```bash
cd .worktrees/skill-pathway-progress-overview
git status --short --branch
```

Expected: clean branch.

**Step 3: Create task ledger**

```bash
scripts/dev/test_result.py start "skill pathway progress overview" --problem "Verify shared progress summary and admin/coach/parent UI slice"
```

Expected: new active ledger under `docs/test-results/active/`.

**Step 4: Baseline backend gate**

Use the main checkout venv:

```bash
cd backend
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/pytest v2/tests -q
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff check v2
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff format --check v2
```

Expected: tests and ruff pass. If baseline fails, stop and record the failure in the ledger.

**Step 5: Commit only if the ledger was created**

```bash
git add docs/test-results/active/<created-ledger>.md test_result.md
git commit -m "Track skill pathway progress overview testing"
```

---

## Task 1: Shared Progress Summary Read Model

**Files:**
- Modify: `backend/v2/contexts/student_progress/domain/models.py`
- Create: `backend/v2/contexts/student_progress/application/use_cases/get_progress_summary.py`
- Modify: `backend/v2/composition/pathway.py`
- Test: `backend/v2/tests/contexts/student_progress/test_progress_summary.py`

**Step 1: Write failing tests**

Create `backend/v2/tests/contexts/student_progress/test_progress_summary.py`.

Cover these cases:

1. Student with no active level returns `next_action == "place_in_level"`.
2. Student in active level with some required skills passed returns mastery counts and `next_action == "record_tests"` when any required skill is `TEST_READY`.
3. Student with all required skills passed and no active recommendation returns `level_completion_status == "complete"` and `next_action == "recommend_level_up"`.
4. Student with active recommendation returns `next_action == "awaiting_admin_approval"`.
5. Student with certificate for the current level returns `certificate_count > 0` and `next_action == "certificate_issued"`.

Use in-memory fakes for:

```python
class _LevelProgressRepo:
    async def get_active(self, student_id: str, program_id: str): ...

class _SkillProgressRepo:
    async def list_for_student_level(self, student_id: str, level_id: str): ...

class _RecommendationRepo:
    async def get_active_for_student(self, student_id: str, program_id: str): ...

class _CertificateRepo:
    async def list_for_student(self, student_id: str): ...

class _SkillLookup:
    async def get_level(self, level_id: str): ...
    async def list_skills_for_level(self, level_id: str): ...
```

Expected assertion shape:

```python
result = await use_case.execute(
    ProgressSummaryRequest(
        student_id="student-1",
        student_name="Maya Raman",
        program_id="program-1",
        program_name="Junior Badminton",
    )
)

assert result.current_level_name == "Level 1"
assert result.required_skill_count == 3
assert result.required_skills_passed == 2
assert result.test_ready_count == 1
assert result.next_action == "record_tests"
```

**Step 2: Run tests and verify RED**

```bash
cd backend
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/pytest v2/tests/contexts/student_progress/test_progress_summary.py -q
```

Expected: fails because `get_progress_summary.py` and models do not exist.

**Step 3: Add domain/read models**

In `backend/v2/contexts/student_progress/domain/models.py`, add:

```python
ProgressNextAction = Literal[
    "place_in_level",
    "continue_practice",
    "record_tests",
    "recommend_level_up",
    "awaiting_admin_approval",
    "certificate_issued",
]

LevelCompletionStatus = Literal["not_started", "in_progress", "test_ready", "complete"]

class StudentProgressOverview(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    student_name: str
    program_id: str
    program_name: str
    current_level_id: str | None = None
    current_level_name: str | None = None
    current_level_sequence: int | None = None
    required_skill_count: int = 0
    required_skills_passed: int = 0
    total_skill_count: int = 0
    total_skills_passed: int = 0
    in_progress_count: int = 0
    not_started_count: int = 0
    test_ready_count: int = 0
    level_completion_status: LevelCompletionStatus = "not_started"
    level_up_status: LevelUpStatus | None = None
    certificate_count: int = 0
    next_action: ProgressNextAction = "place_in_level"
```

**Step 4: Implement use case**

Create `backend/v2/contexts/student_progress/application/use_cases/get_progress_summary.py`.

Implementation shape:

```python
from pydantic import BaseModel

class ProgressSummaryRequest(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    student_name: str
    program_id: str
    program_name: str

class GetProgressSummary:
    def __init__(self, *, level_progress, skill_progress, recommendations, certificates, skill_lookup) -> None:
        ...

    async def execute(self, request: ProgressSummaryRequest) -> StudentProgressOverview:
        active = await self._level_progress.get_active(request.student_id, request.program_id)
        certs = await self._certs.list_for_student(request.student_id)
        rec = await self._recommendations.get_active_for_student(request.student_id, request.program_id)
        if active is None:
            return StudentProgressOverview(
                student_id=request.student_id,
                student_name=request.student_name,
                program_id=request.program_id,
                program_name=request.program_name,
                certificate_count=len(certs),
                next_action="place_in_level",
            )

        level = await self._skill_lookup.get_level(active.level_id)
        skills = await self._skill_lookup.list_skills_for_level(active.level_id)
        progress = await self._skill_progress.list_for_student_level(request.student_id, active.level_id)
        progress_by_skill = {row.skill_id: row for row in progress}

        required_ids = {skill.skill_id for skill in skills if getattr(skill, "is_required", True)}
        total_count = len(skills)
        total_passed = 0
        required_passed = 0
        not_started = 0
        test_ready = 0
        in_progress = 0

        for skill in skills:
            status = getattr(progress_by_skill.get(skill.skill_id), "status", "NOT_STARTED")
            if status == "PASSED":
                total_passed += 1
                if skill.skill_id in required_ids:
                    required_passed += 1
            elif status == "NOT_STARTED":
                not_started += 1
            else:
                in_progress += 1
                if status == "TEST_READY":
                    test_ready += 1

        required_count = len(required_ids)
        complete = required_count > 0 and required_passed == required_count

        if any(c.level_id == active.level_id for c in certs):
            next_action = "certificate_issued"
        elif rec is not None:
            next_action = "awaiting_admin_approval"
        elif complete:
            next_action = "recommend_level_up"
        elif test_ready:
            next_action = "record_tests"
        else:
            next_action = "continue_practice"

        status = "complete" if complete else "test_ready" if test_ready else "in_progress"
        ...
```

Return `StudentProgressOverview`.

**Step 5: Wire composition**

In `backend/v2/composition/pathway.py`:

- Import `GetProgressSummary`.
- Add `get_progress_summary: GetProgressSummary` to `StudentProgressComposition`.
- Instantiate it with the same repos already used by progress/passport.

**Step 6: Run focused tests**

```bash
cd backend
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/pytest v2/tests/contexts/student_progress/test_progress_summary.py -q
```

Expected: pass.

**Step 7: Run backend gate**

```bash
cd backend
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/pytest v2/tests -q
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff check v2
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff format --check v2
```

Expected: pass.

**Step 8: Commit**

```bash
git add backend/v2/contexts/student_progress/domain/models.py \
        backend/v2/contexts/student_progress/application/use_cases/get_progress_summary.py \
        backend/v2/composition/pathway.py \
        backend/v2/tests/contexts/student_progress/test_progress_summary.py
git commit -m "Add student progress overview summary"
```

---

## Task 2: Admin Progress Overview BFF Route

**Files:**
- Modify: `backend/v2/interfaces/admin/progress_routes.py`
- Test: `backend/v2/tests/interface/test_admin_progress_routes.py`

**Step 1: Write failing interface tests**

Add tests for:

1. `GET /api/v2/admin/pathway/progress?program_id=program-1` returns rows for active students.
2. Rows include `student_name`, `current_level_name`, required mastery counts, `next_action`.
3. Filter `next_action=recommend_level_up` returns only matching rows.
4. Missing/empty program returns `422` or existing validation behavior.

Use the existing fake admin fixture patterns in `backend/v2/tests/interface/conftest.py`.
If the shared fixture does not expose enough fake data, add a focused fake query object on
`AdminUseCases.student_progress.get_progress_summary`.

Expected test body shape:

```python
response = admin_client.get("/api/v2/admin/pathway/progress?program_id=program-1")
assert response.status_code == 200
body = response.json()
assert body["rows"][0]["student_name"] == "Maya Raman"
assert body["rows"][0]["next_action"] == "recommend_level_up"
```

**Step 2: Run tests and verify RED**

```bash
cd backend
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/pytest v2/tests/interface/test_admin_progress_routes.py -q
```

Expected: fails with 404 for missing route.

**Step 3: Implement route**

In `backend/v2/interfaces/admin/progress_routes.py`, add:

```python
@router.get("/pathway/progress")
async def get_pathway_progress_overview(
    program_id: str = Query(...),
    next_action: str | None = Query(default=None),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    rows = await use_cases.get_admin_student_progress_overview(
        program_id=program_id,
        next_action=next_action,
    )
    return {"rows": [row.model_dump() if hasattr(row, "model_dump") else row for row in rows]}
```

Add `get_admin_student_progress_overview` to admin composition as a thin interface query:

- List active/enrolled students for the academy/program where possible.
- Resolve student names through enrollment/admin directory data.
- Call `student_progress.get_progress_summary.execute(...)` per student.

Keep this first pass simple and deterministic. If the current data model cannot map program to all active students directly, list active students and summarize those with progress for `program_id`, plus students not placed as `place_in_level` only when they are in a relevant roster/enrollment surface.

**Step 4: Run focused tests**

```bash
cd backend
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/pytest v2/tests/interface/test_admin_progress_routes.py -q
```

Expected: pass.

**Step 5: Run backend gate**

```bash
cd backend
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/pytest v2/tests -q
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff check v2
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff format --check v2
```

Expected: pass.

**Step 6: Commit**

```bash
git add backend/v2/interfaces/admin/progress_routes.py \
        backend/v2/composition/admin.py \
        backend/v2/tests/interface/test_admin_progress_routes.py
git commit -m "Add admin skill progress overview route"
```

---

## Task 3: Coach Session Progress Route

**Files:**
- Modify: `backend/v2/interfaces/coach/skill_routes.py`
- Modify: `backend/v2/composition/coach.py`
- Test: `backend/v2/tests/interface/test_coach_skill_routes.py`

**Step 1: Write failing tests**

Add tests for:

1. Assigned coach can call `GET /api/v2/coach/sessions/{session_id}/students-progress?program_id=program-1`.
2. Response contains one row per roster student.
3. Unassigned coach receives 404, matching existing coach security behavior.

Expected assertion:

```python
response = coach_client.get("/api/v2/coach/sessions/sess-1/students-progress?program_id=program-1")
assert response.status_code == 200
assert response.json()["rows"][0]["student_id"] == "student-1"
```

**Step 2: Run tests and verify RED**

```bash
cd backend
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/pytest v2/tests/interface/test_coach_skill_routes.py -q
```

Expected: route missing or response not shaped.

**Step 3: Implement route**

In `backend/v2/interfaces/coach/skill_routes.py`, add:

```python
@router.get("/sessions/{session_id}/students-progress")
async def get_session_students_progress(
    session_id: str,
    program_id: str = Query(...),
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    if not await use_cases.assigned_sessions.is_coach_assigned(claims.user_id, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    rows = await use_cases.get_session_students_progress(
        session_id=session_id,
        program_id=program_id,
    )
    return {"rows": [row.model_dump() if hasattr(row, "model_dump") else row for row in rows]}
```

In `backend/v2/composition/coach.py`, implement `get_session_students_progress` by:

- Calling existing roster query for the session.
- Passing each roster student into `student_progress.get_progress_summary`.
- Returning summary rows.

Do not weaken the P0.1 coach assignment guard.

**Step 4: Run focused tests**

```bash
cd backend
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/pytest v2/tests/interface/test_coach_skill_routes.py -q
```

Expected: pass.

**Step 5: Run backend gate**

```bash
cd backend
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/pytest v2/tests -q
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff check v2
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff format --check v2
```

Expected: pass.

**Step 6: Commit**

```bash
git add backend/v2/interfaces/coach/skill_routes.py \
        backend/v2/composition/coach.py \
        backend/v2/tests/interface/test_coach_skill_routes.py
git commit -m "Add coach session skill progress summaries"
```

---

## Task 4: Parent Progress Summary Route

**Files:**
- Modify: `backend/v2/interfaces/parent/progress_skill_routes.py`
- Modify: `backend/v2/composition/parent.py`
- Test: `backend/v2/tests/interface/test_parent_progress_routes.py`

**Step 1: Write failing tests**

Add tests for:

1. Parent can call `GET /api/v2/parent/progress/summary?program_id=program-1`.
2. Response contains only owned children.
3. Non-owned students never appear.
4. Empty owned children returns `{"rows": []}`.

Expected assertion:

```python
response = parent_client.get("/api/v2/parent/progress/summary?program_id=program-1")
assert response.status_code == 200
ids = {row["student_id"] for row in response.json()["rows"]}
assert ids == {"owned-student-1"}
```

**Step 2: Run tests and verify RED**

```bash
cd backend
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/pytest v2/tests/interface/test_parent_progress_routes.py -q
```

Expected: route missing.

**Step 3: Implement route**

In `backend/v2/interfaces/parent/progress_skill_routes.py`, add:

```python
@router.get("/progress/summary")
async def get_parent_progress_summary(
    program_id: str = Query(...),
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> object:
    rows = await use_cases.get_parent_progress_summary(
        parent_id=claims.user_id,
        program_id=program_id,
    )
    return {"rows": [row.model_dump() if hasattr(row, "model_dump") else row for row in rows]}
```

In `backend/v2/composition/parent.py`, implement `get_parent_progress_summary` by:

- Calling existing `list_children_for_parent(parent_id)`.
- Calling `student_progress.get_progress_summary` for each child.
- Returning only owned children.

**Step 4: Run focused tests**

```bash
cd backend
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/pytest v2/tests/interface/test_parent_progress_routes.py -q
```

Expected: pass.

**Step 5: Run backend gate**

```bash
cd backend
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/pytest v2/tests -q
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff check v2
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff format --check v2
```

Expected: pass.

**Step 6: Commit**

```bash
git add backend/v2/interfaces/parent/progress_skill_routes.py \
        backend/v2/composition/parent.py \
        backend/v2/tests/interface/test_parent_progress_routes.py
git commit -m "Add parent skill progress summaries"
```

---

## Task 5: Frontend API Client Types

**Files:**
- Modify: `frontend/lib/api/curriculum.ts`
- Test: Typecheck via `pnpm typecheck`

**Step 1: Add client types**

In `frontend/lib/api/curriculum.ts`, add:

```ts
export type ProgressNextAction =
  | "place_in_level"
  | "continue_practice"
  | "record_tests"
  | "recommend_level_up"
  | "awaiting_admin_approval"
  | "certificate_issued";

export type LevelCompletionStatus =
  | "not_started"
  | "in_progress"
  | "test_ready"
  | "complete";

export interface StudentProgressOverview {
  student_id: string;
  student_name: string;
  program_id: string;
  program_name: string;
  current_level_id: string | null;
  current_level_name: string | null;
  current_level_sequence: number | null;
  required_skill_count: number;
  required_skills_passed: number;
  total_skill_count: number;
  total_skills_passed: number;
  in_progress_count: number;
  not_started_count: number;
  test_ready_count: number;
  level_completion_status: LevelCompletionStatus;
  level_up_status: string | null;
  certificate_count: number;
  next_action: ProgressNextAction;
}
```

Add API functions:

```ts
export function getAdminPathwayProgress(programId: string, nextAction?: ProgressNextAction) {
  const q = new URLSearchParams({ program_id: programId });
  if (nextAction) q.set("next_action", nextAction);
  return apiFetch<{ rows: StudentProgressOverview[] }>(`/admin/pathway/progress?${q}`, {
    method: "GET",
  }).then((d) => d.rows);
}

export function getCoachSessionStudentsProgress(sessionId: string, programId: string) {
  return apiFetch<{ rows: StudentProgressOverview[] }>(
    `/coach/sessions/${encodeURIComponent(sessionId)}/students-progress?program_id=${encodeURIComponent(programId)}`,
    { method: "GET" },
  ).then((d) => d.rows);
}

export function getParentProgressSummary(programId: string) {
  return apiFetch<{ rows: StudentProgressOverview[] }>(
    `/parent/progress/summary?program_id=${encodeURIComponent(programId)}`,
    { method: "GET" },
  ).then((d) => d.rows);
}
```

**Step 2: Run typecheck**

```bash
cd frontend
pnpm typecheck
```

Expected: pass.

**Step 3: Commit**

```bash
git add frontend/lib/api/curriculum.ts
git commit -m "Add progress overview API client"
```

---

## Task 6: Admin Overview UI

**Files:**
- Create: `frontend/app/(admin)/admin/pathway/progress/page.tsx`
- Modify if needed: admin navigation component containing Skill Pathway links.
- Test: `frontend` typecheck and lint.

**Step 1: Build page**

Create `frontend/app/(admin)/admin/pathway/progress/page.tsx`.

Requirements:

- Program selector using existing `listPrograms(getActiveAcademyId())`.
- Optional next-action filter.
- Summary tiles:
  - placed rows count
  - `recommend_level_up` count
  - `record_tests` count
  - `certificate_issued` count
- Table columns:
  - Student
  - Current level
  - Required mastery
  - Status
  - Next action
- Row link to `/admin/students/{student_id}/progress?program_id={program_id}`.

Use existing `Card` and `Button` components. Keep styling dense and operational.

**Step 2: Empty and error states**

Handle:

- no academy id
- no programs
- no program selected
- loading rows
- API error
- zero rows

**Step 3: Run frontend checks**

```bash
cd frontend
pnpm typecheck
pnpm lint
```

Expected: pass.

**Step 4: Commit**

```bash
git add 'frontend/app/(admin)/admin/pathway/progress/page.tsx'
git commit -m "Add admin skill progress overview UI"
```

---

## Task 7: Coach Session Progress UI

**Files:**
- Modify: `frontend/app/(coach)/coach/sessions/[id]/progress/page.tsx`
- Test: frontend typecheck/lint.

**Step 1: Replace per-student progress composition**

Update the page to call:

```ts
getCoachSessionStudentsProgress(sessionId, programId)
```

instead of composing roster and per-student progress calls in the component.

**Step 2: Render action states**

For each row:

- show student name
- current level
- required mastery count
- test-ready count
- next action label
- link to existing passport:
  `/coach/students/{student_id}/passport?program_id={program_id}&from_session={session_id}`

Use coach-friendly labels:

- `record_tests` -> "Record tests"
- `recommend_level_up` -> "Recommend level-up"
- `continue_practice` -> "Continue practice"
- `awaiting_admin_approval` -> "Awaiting approval"

**Step 3: Run frontend checks**

```bash
cd frontend
pnpm typecheck
pnpm lint
```

Expected: pass.

**Step 4: Commit**

```bash
git add 'frontend/app/(coach)/coach/sessions/[id]/progress/page.tsx'
git commit -m "Use progress summaries in coach session view"
```

---

## Task 8: Parent Progress Summary UI

**Files:**
- Modify: `frontend/app/(parent)/parent/progress/page.tsx`
- Test: frontend typecheck/lint.

**Step 1: Add parent summary query**

Use:

```ts
getParentProgressSummary(programId)
```

after program selection.

**Step 2: Render summary cards**

For each owned child row:

- child name
- program name/current level
- required skills mastered
- friendly status label
- certificate count
- expansion/link to existing skill list

Friendly labels:

- `place_in_level` -> "Not started"
- `continue_practice` -> "Practicing"
- `record_tests` -> "Ready for assessment"
- `recommend_level_up` -> "Level complete"
- `awaiting_admin_approval` -> "Awaiting approval"
- `certificate_issued` -> "Certificate issued"

**Step 3: Keep existing skill list**

Do not remove the existing child passport list. Place the summary card above it or use it as the selected-child summary.

**Step 4: Run frontend checks**

```bash
cd frontend
pnpm typecheck
pnpm lint
```

Expected: pass.

**Step 5: Commit**

```bash
git add 'frontend/app/(parent)/parent/progress/page.tsx'
git commit -m "Add parent skill progress summaries"
```

---

## Task 9: Final Verification And Handoff

**Files:**
- Update/close task ledger.

**Step 1: Full backend gate**

```bash
cd backend
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/pytest v2/tests -q
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff check v2
/Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/ruff format --check v2
```

Expected: pass.

**Step 2: Frontend gate**

```bash
cd frontend
pnpm typecheck
pnpm lint
```

Expected: pass.

**Step 3: Optional local smoke**

If local services are needed:

```bash
scripts/local_test_stack.sh app
scripts/local_test_stack.sh smoke
```

Expected: backend health and frontend BFF proxy return `{"status":"ok"}`.

**Step 4: Record verification**

```bash
scripts/dev/test_result.py verify skill-pathway-progress-overview --message "<commands and results>"
scripts/dev/test_result.py close skill-pathway-progress-overview
```

**Step 5: Commit ledger close**

```bash
git add test_result.md docs/test-results/archive/<ledger>.md
git commit -m "Record skill progress overview verification"
```

**Step 6: Final status**

Report:

- commits created
- files changed
- backend verification
- frontend verification
- skipped checks
- any remaining risks
