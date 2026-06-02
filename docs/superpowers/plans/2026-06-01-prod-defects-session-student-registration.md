# Production Defects: Sessions, Student Profile, Register Child Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the production defects where sessions are not visible, the admin student profile lacks operational billing/enrollment context, and the parent register-child workflow needs local proof before production.

**Architecture:** Keep the fixes in the v2 BFF and canonical Next.js app. Backend changes should extend persona-shaped admin/parent responses rather than pushing business calculations into React. The first task is reproduction and evidence gathering; no production deploy happens until local automated and browser verification pass.

**Tech Stack:** FastAPI v2 BFF, MongoDB repositories, Next.js 15 App Router, React Query, Playwright, local Firebase Auth emulator, `scripts/local_test_stack.sh`.

---

## Current Behavior Found

1. `frontend/app/(admin)/admin/sessions/page.tsx` calls `listAdminSessions(undefined, { window: "upcoming" })`.
2. `backend/v2/composition/admin.py` handles `window == "upcoming"` by reading only concrete v2 session documents with `start_at`; it explicitly skips legacy recurring template synthesis.
3. Single-date admin session queries in `backend/v2/composition/admin.py` do synthesize legacy recurring templates from `days_of_week`, `start_time`, and `end_time`.
4. Parent onboarding calls `GET /api/v2/parent/sessions/available`; `MongoSessionRepository.available_for_parent_catalog()` also only reads concrete `start_at` session documents.
5. `frontend/app/(admin)/admin/students/[studentId]/page.tsx` exists, but it only shows editable demographics, parent account, active session count, attendance, and dues status.
6. `AdminStudentDetailView` and `AdminStudentDetail` do not include enrolled session rows, payment history, or current payment amount.
7. Parent registration/onboarding exists through `frontend/app/(marketing)/register/page.tsx` and `frontend/app/(parent)/parent/onboarding/page.tsx`, with API calls to `/register/parent`, `/parent/onboarding/*`, `/parent/sessions/available`, `/parent/enrollments/quote`, and `/parent/checkout/start`.

## Files Likely Affected

Backend:

- `backend/v2/composition/admin.py`
- `backend/v2/contexts/enrollment/infrastructure/mongo_session_repo.py`
- `backend/v2/contexts/enrollment/application/use_cases/list_parent_available_sessions.py`
- `backend/v2/contexts/enrollment/application/use_cases/admin_directory.py`
- `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py`
- `backend/v2/interfaces/admin/views.py`
- `backend/v2/interfaces/admin/directory_routes.py`
- `backend/v2/tests/interface/test_admin_directory.py`
- `backend/v2/tests/interface/test_parent_sessions_checkout.py`
- Add focused backend regression coverage for upcoming recurring sessions and enriched student detail.

Frontend:

- `frontend/lib/api/admin.ts`
- `frontend/lib/api/v2/students.ts`
- `frontend/lib/api/parent.ts`
- `frontend/app/(admin)/admin/sessions/page.tsx`
- `frontend/app/(admin)/admin/students/[studentId]/page.tsx`
- `frontend/app/(parent)/parent/onboarding/page.tsx`
- `frontend/e2e/specs/admin-students.spec.ts`
- `frontend/e2e/specs/qa-defects.spec.ts`
- Add or extend a Playwright spec for the register-child happy path.

Status/testing ledger:

- `test_result.md`

## Risks

- The session visibility defect may affect both admin and parent flows if production still has recurring template rows without concrete future instances.
- Adding billing/payment data to student detail can leak cross-tenant or cross-parent data if queries are not academy-scoped and student-scoped.
- “Current payment amount” must be defined consistently. Use the active enrollment's session monthly price or latest open invoice amount, and label the UI accordingly. Do not let the frontend infer this from unrelated payment rows.
- Register-child verification needs real local Firebase emulator credentials from `scripts/local_test_stack.sh`; do not use dummy Firebase keys for browser auth testing.
- Stripe checkout should be verified locally with the fake/test gateway only. Do not send live payments or real emails.

## Acceptance Criteria

- Admin sessions list shows upcoming concrete sessions and recurring/template sessions that should occur in the next 30 days.
- Parent onboarding session picker shows available sessions for the same data set that admins can see, subject to capacity.
- Admin student profile shows enrolled session names/times/status, payment history, and current payment amount without raw internal IDs in normal UI.
- Admin can still edit the student profile and change parent.
- Register-child flow works locally through account registration/sign-in, onboarding steps, session selection, quote display, and checkout start.
- `test_result.md` records the defects, files changed, focused checks, browser checks, and any skipped checks.

---

### Task 1: Reproduce And Record The Defects

**Files:**

- Modify: `test_result.md`
- Read/check: `backend/scripts/seed_local.py`
- Read/check: `/tmp/academy-manager-local/*.log` after local stack startup

- [ ] **Step 1: Record the new production defect bundle in `test_result.md`**

Add a new `user_problem_statement` or status entry for:

```yaml
user_problem_statement: "Production defects: sessions not showing, admin student profile needs enrolled sessions/payment history/current payment amount, and register-child workflow needs local verification before prod."
```

Add three high-priority tasks with `implemented: false`, `working: "NA"`, and `needs_retesting: true`.

- [ ] **Step 2: Start the local stack**

Run:

```bash
scripts/local_test_stack.sh all
```

Expected: MongoDB, Firebase Auth emulator, backend, and frontend start. If it fails because a port is occupied, use:

```bash
scripts/local_test_stack.sh status
```

then stop only processes started by this helper:

```bash
scripts/local_test_stack.sh stop
scripts/local_test_stack.sh all
```

- [ ] **Step 3: Seed local data**

Run:

```bash
scripts/local_test_stack.sh seed
```

Expected: seeded admin, parent, students, sessions, enrollments, waiver data, and local login details printed by the seed script.

- [ ] **Step 4: Capture API evidence for session visibility**

Run authenticated local checks using the seeded admin token/cookie path from the local stack. Compare:

```bash
curl -sS 'http://127.0.0.1:8001/api/v2/admin/sessions?window=upcoming'
curl -sS 'http://127.0.0.1:8001/api/v2/admin/sessions?date=2026-06-01'
curl -sS 'http://127.0.0.1:8001/api/v2/parent/sessions/available'
```

Expected before the fix: any recurring/template-only session visible through a single-date query is absent from `window=upcoming` and/or parent available sessions.

---

### Task 2: Fix Upcoming Session Visibility

**Files:**

- Modify: `backend/v2/composition/admin.py`
- Modify: `backend/v2/contexts/enrollment/infrastructure/mongo_session_repo.py`
- Test: `backend/v2/tests/interface/test_parent_sessions_checkout.py`
- Add/modify focused test: `backend/v2/tests/interface/test_admin_sessions.py` or nearest existing admin sessions interface test

- [ ] **Step 1: Add backend regression tests first**

Add tests proving:

- `GET /api/v2/admin/sessions?window=upcoming` includes a recurring template whose next occurrence is within the next 30 days.
- `GET /api/v2/parent/sessions/available` includes an available recurring template with seats.
- Cancelled/completed sessions and full sessions remain hidden from the parent catalog.
- Rows are academy-scoped.

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/interface/test_parent_sessions_checkout.py v2/tests/interface/test_admin_sessions.py -q
```

Expected before implementation: at least one new test fails because recurring/template sessions are missing.

- [ ] **Step 2: Extract shared recurring-session synthesis**

In `backend/v2/composition/admin.py`, replace the inline single-date legacy synthesis with a helper that can synthesize occurrences for a date range. The helper should:

- Accept `range_start`, `range_end`, and current academy-scoped session repository access.
- Read template docs with `days_of_week` and no `start_at`.
- Produce normalized dicts containing `session_id`, `title`, `location`, `coach_id`, `capacity`, `status`, `start_at`, and `end_at`.
- Use the template `session_id` or `_id` as the session identity unless the existing codebase already stores a generated occurrence id.

- [ ] **Step 3: Include synthesized rows in `window=upcoming`**

Update the `window == "upcoming"` branch in `backend/v2/composition/admin.py` to combine:

- Concrete v2 docs from `sessions_r._find_many({"start_at": {"$gte": start, "$lte": end}})`.
- Synthesized recurring rows for the same range.

Sort the combined rows by `start_at`, then return `_build_admin_session_rows(combined_rows)`.

- [ ] **Step 4: Extend parent session catalog for recurring templates**

Update `MongoSessionRepository.available_for_parent_catalog()` so the parent catalog also includes recurring/template sessions with future occurrences. Preserve:

- `status` filtering.
- capacity checks using active enrollments and reserved seats.
- `_amount_cents()` normalization.
- tenant scoping through repository helpers.

- [ ] **Step 5: Verify backend**

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/interface/test_parent_sessions_checkout.py v2/tests/interface/test_admin_directory.py -q
ruff check v2
ruff format --check v2
```

Expected: focused tests pass; ruff passes.

---

### Task 3: Enrich Admin Student Detail BFF

**Files:**

- Modify: `backend/v2/contexts/enrollment/application/use_cases/admin_directory.py`
- Modify: `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py`
- Modify: `backend/v2/interfaces/admin/views.py`
- Modify: `frontend/lib/api/v2/students.ts`
- Test: `backend/v2/tests/interface/test_admin_directory.py`
- Test: `backend/v2/tests/application/test_admin_student_edit.py` if the application model changes affect existing use-case tests

- [ ] **Step 1: Add student detail response models**

Add backend models for:

- `AdminStudentSessionSummary`: `enrollment_id`, `session_id`, `session_title`, `location`, `start_at`, `end_at`, `status`, `payment_mode`, `subscription_status`, `amount_cents`.
- `AdminStudentPaymentSummary`: `payment_id`, `session_id`, `period`, `amount_cents`, `paid_amount_cents`, `balance_due_cents`, `status`, `payment_method`, `created_at`.
- `AdminStudentCurrentPaymentSummary`: `amount_cents`, `source`, `status`, `period`, `payment_id`, `session_id`.

Extend `AdminStudentDetail` and `AdminStudentDetailView` with:

```python
enrolled_sessions: list[AdminStudentSessionSummary] = Field(default_factory=list)
payment_history: list[AdminStudentPaymentSummary] = Field(default_factory=list)
current_payment: AdminStudentCurrentPaymentSummary | None = None
```

- [ ] **Step 2: Add failing backend tests**

Add test data with one active enrollment, one session, one paid payment, and one pending current invoice for the student. Assert `GET /api/v2/admin/students/{student_id}` returns:

- the active enrolled session title and schedule;
- payment rows newest first;
- current payment amount from the open invoice when present;
- no rows for another academy or another student.

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/interface/test_admin_directory.py -q
```

Expected before implementation: the new detail fields are missing.

- [ ] **Step 3: Implement scoped Mongo aggregation**

In `MongoStudentRepository.get_admin_student()`:

- Reuse the resolved `student_id`.
- Query active enrollments scoped by `academy_id` and `student_id`.
- Batch load sessions for those enrollment session ids.
- Query payments scoped by `academy_id`, `student_id`, and `is_deleted != true`, sorted by newest first.
- Compute `current_payment` from the newest unpaid/partially-paid pending invoice; if no open invoice exists, use active enrollment/session amount as `source="session_price"`.

Do not rewrite historical parent/payment rows during this read.

- [ ] **Step 4: Preserve existing edit/change-parent behavior**

Run existing edit and parent-change focused tests:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/application/test_admin_student_edit.py v2/tests/interface/test_admin_student_user_routes.py -q
```

Expected: existing edit and change-parent behavior still passes.

---

### Task 4: Build The Student Profile UI

**Files:**

- Modify: `frontend/lib/api/v2/students.ts`
- Modify: `frontend/app/(admin)/admin/students/[studentId]/page.tsx`
- Modify: `frontend/e2e/specs/admin-students.spec.ts`

- [ ] **Step 1: Extend frontend student types**

Mirror the backend fields in `frontend/lib/api/v2/students.ts`:

- `enrolled_sessions`
- `payment_history`
- `current_payment`

- [ ] **Step 2: Add profile sections**

In `frontend/app/(admin)/admin/students/[studentId]/page.tsx`, add sections under the existing header:

- Current payment amount card.
- Enrolled sessions table/list with session name, location, schedule, status, amount.
- Payment history table/list with date, period, status, amount paid, balance.

Keep the existing profile edit form and parent-change panel.

- [ ] **Step 3: Add empty/error-safe UI states**

Show:

- “No active sessions” when `enrolled_sessions.length === 0`.
- “No payments recorded” when `payment_history.length === 0`.
- “No current payment due” when `current_payment === null`.

- [ ] **Step 4: Add Playwright coverage**

Extend `frontend/e2e/specs/admin-students.spec.ts` with a route stub for:

```txt
GET /api/v2/admin/students/student-1
GET /api/v2/admin/users?role=parent
```

Assert the detail page renders:

- student name;
- current amount;
- enrolled session title;
- payment history row;
- editable profile form.

Run:

```bash
cd frontend
pnpm e2e -- --grep "admin students"
pnpm typecheck
pnpm lint
```

Expected: admin student tests, types, and lint pass.

---

### Task 5: Verify Register-Child Workflow Locally

**Files:**

- Modify if needed: `frontend/app/(marketing)/register/page.tsx`
- Modify if needed: `frontend/app/(parent)/parent/onboarding/page.tsx`
- Modify if needed: `frontend/lib/api/parent.ts`
- Add/modify: `frontend/e2e/specs/qa-defects.spec.ts` or a new `frontend/e2e/specs/register-child.spec.ts`

- [ ] **Step 1: Add a mocked Playwright happy-path test**

Stub:

- `POST /api/v2/register/parent`
- `POST /api/v2/parent/onboarding/start`
- `PATCH /api/v2/parent/onboarding/{id}`
- `GET /api/v2/parent/sessions/available`
- `POST /api/v2/parent/enrollments/quote`
- `POST /api/v2/parent/checkout/start`

Assert the user can:

- open `/register`;
- complete Google or email registration path with API stubs;
- land on `/parent/onboarding`;
- enter parent and child data;
- accept waiver;
- select a session;
- see quote/current charge;
- click checkout and receive a redirect URL.

- [ ] **Step 2: Fix only reproduced workflow defects**

If the mocked or local browser path fails, fix the narrow cause. Do not redesign onboarding in this slice unless the failure is caused by the current layout or missing state.

- [ ] **Step 3: Run local browser verification with the real local stack**

Run:

```bash
scripts/local_test_stack.sh all
scripts/local_test_stack.sh seed
```

Open:

```txt
http://blno.localhost:3001/register
```

Verify:

- Firebase calls go to the Auth emulator.
- `NEXT_PUBLIC_FIREBASE_API_KEY` is not `dummy`.
- parent registration creates/returns the parent user row;
- onboarding session picker has sessions;
- quote displays;
- checkout start returns a local/test redirect.

---

### Task 6: Final Verification And Handoff

**Files:**

- Modify: `test_result.md`

- [ ] **Step 1: Run focused backend verification**

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/interface/test_parent_sessions_checkout.py v2/tests/interface/test_admin_directory.py v2/tests/application/test_admin_student_edit.py -q
ruff check v2
ruff format --check v2
```

- [ ] **Step 2: Run focused frontend verification**

Run:

```bash
cd frontend
pnpm typecheck
pnpm lint
pnpm e2e -- --grep "admin students|register child|parent onboarding"
```

- [ ] **Step 3: Run local smoke**

Run:

```bash
scripts/local_test_stack.sh smoke
```

- [ ] **Step 4: Update `test_result.md`**

Record:

- implementation files changed;
- exact commands run;
- pass/fail output summaries;
- manual browser scenarios;
- any skipped checks and why.

- [ ] **Step 5: Final pre-finish checks**

Run:

```bash
git status --short --branch
git diff
```

Confirm only related changes are present.
