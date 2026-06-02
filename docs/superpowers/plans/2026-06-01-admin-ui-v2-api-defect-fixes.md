# Admin UI + v2 API Defect Fixes

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 isolated defects — missing admin nav entries, sessions not visible, student profile missing billing context, parent catalog missing recurring sessions — as separate, independently-reviewable git commits.

**Architecture:** Issues B, C, and D are already coded in the working tree but uncommitted. Each task verifies tests pass, then stages only its own files and commits. Issue A is new code. Each commit is self-contained: one defect, one commit, one test run.

**Tech Stack:** FastAPI v2 BFF, Motor/PyMongo, Next.js 15 App Router, React Query, pytest, pnpm.

---

## Commit map (execute in order)

| Commit | Issue | Scope |
|--------|-------|-------|
| 1 | A — Nav fix | `screen-meta.ts` only |
| 2 | B+D — Sessions + parent catalog | `mongo_session_repo.py`, `admin.py`, `mongo_session_writer.py`, 2 test files |
| 3 | C — Student profile enrichment | `admin_directory.py`, `mongo_student_repo.py`, `views.py`, test files |
| 4 | Docs/process | `AGENTS.md`, `docs/agent/*`, `test_result.md`, scripts, new plan files |

---

## Issue A — Admin nav: Coaches & Parents pages unreachable

**Root cause:** Pages `/admin/coaches` and `/admin/parents` were created in commit `2196eb4` but `ADMIN_NAV` and `SCREEN_META` in `screen-meta.ts` were never updated. The sidebar still has one combined entry pointing to `/admin/users`.

---

### Task 1: Add Coaches and Parents to admin sidebar

**Files:**
- Modify: `frontend/components/admin/screen-meta.ts`

- [ ] **Step 1: Open the file and locate the combined entry**

  File: `frontend/components/admin/screen-meta.ts`, line 50.
  Current:
  ```ts
  { href: "/admin/users", label: "Coaches & Parents", icon: "user", match: startsWith("/admin/users") },
  ```

- [ ] **Step 2: Replace with two separate entries**

  Replace the single line with:
  ```ts
  { href: "/admin/coaches", label: "Coaches", icon: "whistle", match: startsWith("/admin/coaches") },
  { href: "/admin/parents", label: "Parents", icon: "user", match: startsWith("/admin/parents") },
  ```
  Keep `/admin/users` accessible (detail rows link there) but remove it from `ADMIN_NAV`.

- [ ] **Step 3: Add SCREEN_META entries**

  In the `SCREEN_META` object (around line 104), add after the `/admin/users` entry:
  ```ts
  "/admin/coaches": { title: "Coaches", subtitle: "Coach directory", breadcrumbs: ["Admin", "Coaches"] },
  "/admin/parents": { title: "Parents", subtitle: "Parent directory", breadcrumbs: ["Admin", "Parents"] },
  ```

- [ ] **Step 4: Verify TypeScript compiles**

  ```bash
  cd frontend && pnpm typecheck
  ```
  Expected: no errors.

- [ ] **Step 5: Commit**

  ```bash
  git add frontend/components/admin/screen-meta.ts
  git commit -m "fix(nav): add Coaches and Parents as separate admin sidebar entries

  Pages /admin/coaches and /admin/parents have existed since commit 2196eb4
  but were never wired into ADMIN_NAV or SCREEN_META. The combined
  /admin/users entry is removed from the sidebar; the two focused entries
  replace it. /admin/users remains routable for detail-row deep links."
  ```

---

## Issue B + D — Sessions: recurring templates invisible

**Root cause (admin):** `window="upcoming"` path in `compose_admin` only queried concrete `start_at` documents, silently skipping legacy recurring templates (schema: `days_of_week` + `start_time`/`end_time`, no `start_at`).

**Root cause (parent):** `available_for_parent_catalog()` had the same gap.

**Already coded:** All backend changes are in the working tree, uncommitted. New helpers `synthesize_recurring_session_docs()` and `session_start_sort_key()` were extracted into `mongo_session_repo.py` and wired into both callers. `_build_admin_session_rows` was also fixed to use request-scoped `current_academy_id()` instead of the boot-time default.

---

### Task 2: Verify and commit the sessions + parent catalog fix

**Files to commit:**
- `backend/v2/contexts/enrollment/infrastructure/mongo_session_repo.py`
- `backend/v2/contexts/enrollment/infrastructure/mongo_session_writer.py`
- `backend/v2/composition/admin.py`
- `backend/v2/tests/interface/test_admin_sessions.py`
- `backend/v2/tests/interface/test_parent_sessions_checkout.py`

- [ ] **Step 1: Activate venv and run admin sessions tests**

  ```bash
  cd backend && source .venv/bin/activate
  pytest v2/tests/interface/test_admin_sessions.py -v
  ```
  Expected: all tests pass.

- [ ] **Step 2: Run parent catalog tests**

  ```bash
  pytest v2/tests/interface/test_parent_sessions_checkout.py -v
  ```
  Expected: all pass, including `test_parent_available_catalog_includes_available_recurring_templates`.

- [ ] **Step 3: Run the full backend suite**

  ```bash
  pytest v2/tests -q
  ```
  Expected: no failures.

- [ ] **Step 4: If any test fails, fix before proceeding**

  - Synthesize logic: `mongo_session_repo.py` → `synthesize_recurring_session_docs()`
  - Admin upcoming path: `admin.py` → `list_admin_sessions()` with `window="upcoming"`
  - Parent catalog: `mongo_session_repo.py:145` → `available_for_parent_catalog()`
  - Re-run the failing test after each edit. Do not commit until all pass.

- [ ] **Step 5: Stage only these files**

  ```bash
  git add backend/v2/contexts/enrollment/infrastructure/mongo_session_repo.py
  git add backend/v2/contexts/enrollment/infrastructure/mongo_session_writer.py
  git add backend/v2/composition/admin.py
  git add backend/v2/tests/interface/test_admin_sessions.py
  git add backend/v2/tests/interface/test_parent_sessions_checkout.py
  ```

- [ ] **Step 6: Commit**

  ```bash
  git commit -m "fix(sessions): synthesize recurring templates in admin upcoming and parent catalog

  Both the admin sessions upcoming-window query and the parent available-
  sessions catalog only queried concrete start_at documents, silently
  skipping legacy recurring templates (days_of_week + start_time/end_time).

  - Extract synthesize_recurring_session_docs() + session_start_sort_key()
    into mongo_session_repo so both callers share one implementation
  - Wire synthesize into compose_admin window='upcoming' path
  - Fix _build_admin_session_rows to use current_academy_id() (request-
    scoped) instead of the app-boot default_academy_id
  - available_for_parent_catalog() already uses the new helper"
  ```

---

## Issue C — Admin student profile lacks billing context

**Root cause:** `AdminStudentDetail` (domain) and `AdminStudentDetailView` (API) had no `enrolled_sessions`, `payment_history`, or `current_payment` fields. The frontend page already renders these panels but received empty lists.

**Already coded:** Domain models, repo methods, and API view models are all uncommitted. Frontend types (`students.ts`) and UI (`students/[studentId]/page.tsx`) were already updated.

---

### Task 3: Verify and commit the student profile enrichment

**Files to commit:**
- `backend/v2/contexts/enrollment/application/use_cases/admin_directory.py`
- `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py`
- `backend/v2/interfaces/admin/views.py`
- `backend/v2/tests/interface/test_admin_directory_mongo_student_repo.py` (new file)
- `backend/v2/tests/interface/test_admin_student_user_routes.py`

- [ ] **Step 1: Run the student repo tests**

  ```bash
  cd backend && source .venv/bin/activate
  pytest v2/tests/interface/test_admin_directory_mongo_student_repo.py -v
  ```
  Expected: all tests pass.

- [ ] **Step 2: Run the admin student route tests**

  ```bash
  pytest v2/tests/interface/test_admin_student_user_routes.py -v
  ```
  Expected: all tests pass.

- [ ] **Step 3: Run the full backend suite**

  ```bash
  pytest v2/tests -q
  ```
  Expected: no failures.

- [ ] **Step 4: If any test fails, fix before proceeding**

  Key methods to debug:
  - `mongo_student_repo.py` → `_admin_student_enrolled_sessions()` — queries `enrollments` + joins `sessions`
  - `mongo_student_repo.py` → `_admin_student_payment_history()` — queries `payments` scoped to `student_id`
  - `mongo_student_repo.py` → `_admin_student_current_payment()` — derives from payment history + enrolled sessions
  - Domain models in `admin_directory.py`: `AdminStudentSessionSummary`, `AdminStudentPaymentSummary`, `AdminStudentCurrentPaymentSummary`
  - View models in `views.py`: matching `*View` classes
  - Re-run the failing test after each edit.

- [ ] **Step 5: Stage only these files**

  ```bash
  git add backend/v2/contexts/enrollment/application/use_cases/admin_directory.py
  git add backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py
  git add backend/v2/interfaces/admin/views.py
  git add backend/v2/tests/interface/test_admin_directory_mongo_student_repo.py
  git add backend/v2/tests/interface/test_admin_student_user_routes.py
  ```

- [ ] **Step 6: Commit**

  ```bash
  git commit -m "feat(student-detail): enrich admin student profile with enrolled sessions and payment history

  AdminStudentDetail and AdminStudentDetailView had no enrolled_sessions,
  payment_history, or current_payment fields. The frontend page already
  rendered the panels but showed empty lists.

  - Add domain models AdminStudentSessionSummary, AdminStudentPaymentSummary,
    AdminStudentCurrentPaymentSummary to admin_directory.py
  - Add repo methods _admin_student_enrolled_sessions(),
    _admin_student_payment_history(), _admin_student_current_payment()
    to MongoStudentRepository; get_admin_student() now populates all three
  - Add matching view models to views.py"
  ```

---

## Docs / Process changes

**Remaining uncommitted:** `AGENTS.md`, `docs/agent/architecture-rules.md`, `docs/agent/feedback-loop.md`, `docs/agent/testing-verification.md`, `scripts/ci/pr_failure_feedback.py`, `test_result.md`, and untracked files (`docs/test-results/`, `scripts/dev/test_result.py`, `tests/test_test_result_cli.py`, plan files).

---

### Task 4: Commit process and documentation changes

- [ ] **Step 1: Stage agent docs and scripts**

  ```bash
  git add AGENTS.md
  git add docs/agent/architecture-rules.md
  git add docs/agent/feedback-loop.md
  git add docs/agent/testing-verification.md
  git add scripts/ci/pr_failure_feedback.py
  git add test_result.md
  ```

- [ ] **Step 2: Stage new tooling files**

  ```bash
  git add scripts/dev/test_result.py
  git add tests/test_test_result_cli.py
  git add docs/test-results/
  ```

- [ ] **Step 3: Stage plan files**

  ```bash
  git add docs/superpowers/plans/
  ```

- [ ] **Step 4: Commit**

  ```bash
  git commit -m "chore: update agent docs, test-result ledger tooling, and session plans"
  ```

---

## Final verification checklist

- [ ] `pnpm typecheck` passes from `frontend/`
- [ ] `pytest v2/tests -q` passes from `backend/` (venv active)
- [ ] `git log --oneline -5` shows 4 clean separate commits
- [ ] Admin sidebar shows "Coaches" and "Parents" as separate entries
- [ ] `/admin/coaches` and `/admin/parents` load without 404
- [ ] Admin sessions page shows upcoming recurring sessions
- [ ] Admin student detail page shows enrolled sessions, payment history, current payment
- [ ] Parent onboarding session picker shows recurring sessions
