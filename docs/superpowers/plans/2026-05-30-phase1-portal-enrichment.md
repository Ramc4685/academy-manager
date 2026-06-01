# Phase 1 — Parent + Coach Portal Enrichment (detailed plan)

Derived from `docs/plans/saas-v2-roadmap.md (P1 outline)`, grounded against the
**committed** baseline at `f8d11a8` (Phase 0 complete). Verified symbol inventory below.

Worktree: `<worktree>`
Branch: `feat/phase1-portal-enrichment`
Baseline: `1387 passed, 7 skipped` (unit+contract+interface).

## Verified baseline facts (do NOT re-discover; trust these, but read the file before editing)

- **Billing ledger repo EXISTS**: `billing/infrastructure/mongo_billing_ledger_repo.py`
  `MongoBillingLedgerRepository(TenantScopedRepository)` with: `create_invoice`, `get_invoice(invoice_id)`,
  `record_payment`, `allocate_payment`, `list_invoices_for_academy(limit)`. Collections: `invoices`,
  `invoice_lines`, `payments`, `payment_allocations`. **No `list_invoices_for_parent` yet** → add it.
- **Ledger domain**: `billing/domain/ledger.py` `LedgerInvoice` (fields: invoice_id, academy_id, parent_id,
  student_id|None, enrollment_id|None, period, status[open|partially_paid|paid|void], subtotal_cents,
  discount_cents, total_cents, balance_due_cents, currency, due_date, pdf_artifact_id|None, created_at,
  updated_at), `InvoiceLine` (line_id, academy_id, invoice_id, line_type, description, quantity,
  unit_amount_cents, amount_cents, source_type|None, source_id|None, created_at).
- **Billing enrollment**: `billing/domain/session_type.py` `StudentBillingEnrollment` (enrollment_id,
  academy_id, student_id, parent_id, session_type_id, stripe_subscription_id|None, billing_start_date,
  status[active|paused|cancelled|transferred_out], override_price_cents|None, enrolled_at, updated_at).
  `SessionType` (session_type_id, academy_id, name, description|None, price_cents, billing_period
  [monthly|per_session], overage_rate_cents|None, is_active, created_at, updated_at).
- **Billing ports** (`billing/application/ports.py`): `SessionTypeRepository`(save,get,list_active,
  soft_delete), `StudentBillingEnrollmentRepository`(save,get,list_for_student,list_for_parent,
  get_by_stripe_subscription), `StripeGateway` (incl. `create_subscription_checkout_session(...)
  -> (checkout_session_id, redirect_url, stripe_subscription_id)`, `cancel_subscription(sub_id,*,
  at_period_end)`, `create_customer_portal_session(...)`).
- **Parent wiring**: routes `interfaces/parent/{activity,onboarding,payment,session,pause,webhook}_routes.py`,
  all `prefix="/parent"`, mounted under `/api/v2`. DI via `interfaces/parent/deps.py`
  `get_parent_use_cases(request)->request.app.state.parent` returning `ParentUseCases` dataclass.
  Composition: `composition/parent.py` `compose_parent(...)` builds `ParentComposition` with mostly
  inline async callables. Existing inline callables: `list_children_for_parent`, `list_enrollments_for_parent`,
  `list_attendance_for_parent`, `list_progress_for_parent`, `start_autopay_for_enrollment`,
  `list_payments_for_parent`, `open_billing_portal` (route `POST /parent/billing/portal`), etc.
  DTOs in `interfaces/parent/views.py`. `MongoStudentBillingEnrollmentRepository` and
  `MongoBillingLedgerRepository` are already instantiated in `compose_parent`.
- **Coach wiring**: routes `interfaces/coach/{today,dashboard,attendance,notes}_routes.py`, `prefix="/coach"`.
  DI `interfaces/coach/deps.py` `CoachUseCases` dataclass; composition `composition/coach.py` `compose_coach(
  db, outbox, idempotency_store)` building `CoachComposition`. Already wired: `list_today`
  (`ListCoachOccurrencesForDate`), `get_roster` (`GetSessionRoster` — **wired but no route yet**),
  `mark_attendance` (`MarkAttendance`), `get_dashboard_metrics`, `create_lesson_plan`/`list_lesson_plans`,
  `create_progress_note`/`list_progress_notes`. `CoachAssignedSessionLookup(sessions_repo)` with
  `async is_coach_assigned(coach_id, session_id)->bool`.
- **Occurrences**: `MongoSessionOccurrenceRepository` (enrollment ctx): `get(id)`, `list_for_session(sid)`,
  `list_for_session_between(sid,start,end)`, `list_for_coach_on_date(coach,date)`. `SessionOccurrence`
  (occurrence_id, academy_id, session_id, start_at, end_at, status[scheduled|cancelled|completed],
  scheduled_coach_id, actual_coach_id|None, substitute_coach_id|None, is_billable, is_payable,
  cancellation_reason|None, template_session_id|None).
- **Roster**: `GetSessionRoster(enrollments,students).execute(session_id)->list[RosterEntry
  {enrollment_id, student_id, full_name, status}]`. Enrollment(session-roster) add/remove today is
  admin-only (`enrollment/application/use_cases/admin_writes.py`: `EditRosterAdd`, `WithdrawEnrollment`).
- **Attendance**: `MarkAttendance` (coaching ctx) idempotent via `@idempotent(mutation_id)`;
  `MarkAttendanceCommand{mutation_id, occurrence_id, session_id, student_id, status[present|absent|late],
  ...}`, `execute(cmd, coach_id)`. Idempotency: `shared/idempotency` `IdempotencyStore.get/put`,
  `MongoIdempotencyStore` (`idempotency_keys`).
- **Coaching notes**: `session_notes.py` `CreateProgressNote{coach_id,session_id,student_id,body}`,
  `ProgressNote{note_id,session_id,student_id,coach_id,body,created_at}`, repo
  `MongoCoachingNotesRepository`. Coach surface lookups via `CoachAssignedSessionLookup`.
- **Tests**: `tests/interface/conftest.py` fakes (FakeSessionQuery, FakeEnrollmentQuery, FakeStudentQuery,
  FakeOccurrenceQuery, FakeAttendanceRepo, FakeCoachingNotesRepo, FakeOutbox, FakeIdempotencyStore) +
  `app.dependency_overrides[get_*_use_cases]`. `coach_client`/`parent_client`/`admin_client`/`anon_client`.
  `tests/contract/` uses `mongomock-motor` (`db`/`acad` fixtures in `contract/conftest.py`).
  Run: `cd backend && uv run pytest v2/tests/{unit,contract,interface,application} -q`. Lint:
  `cd backend && uv run lint-imports`.

## Conventions (from roadmap cross-cutting + repo)
- Every Mongo repo extends `TenantScopedRepository` (`shared/tenancy/repository.py`); never hand-filter academy_id.
- Domain pure (frozen pydantic); application has ports only; no infra imports in domain/application (import-linter enforced).
- Events subclass `DomainEvent` (`shared/events/base.py`) with `Literal name="Context.EventName"` + `schema_version`.
- Migrations: `backend/v2/migrations/NNNN_name.py` with `version="NNNN"`, `async def up(db)`. Next free ≥ `0112`.
- TDD mandatory: write failing test (contract/interface/unit), watch it fail, minimal code, green, refactor.

## Plan corrections vs the P1 outline (decisions baked in)
1. **Child schedule** is built on the **enrollment-context `Enrollment`** (student→session) + occurrences,
   NOT on `StudentBillingEnrollment` (which has `session_type_id`, no session link). `GetChildSchedule`
   lives in `contexts/enrollment/application/use_cases/`.
2. **Parent self-enroll** routes use `/parent/billing-enrollments` (NOT `/parent/enrollments`, which is
   already the session-roster listing) to mirror admin `/admin/billing-enrollments`.
3. **Subscription portal**: `POST /parent/billing/portal` already exists (`open_billing_portal`). Do NOT add
   a duplicate `/parent/subscription/portal`; reuse the existing route. (Note in invoice task only.)
4. **Coach roster mutate** delegates to enrollment writes but guards on `CoachAssignedSessionLookup`.

---

## TASKS

### Task 1 — Ledger repo: `list_invoices_for_parent`
- Add `list_invoices_for_parent(self, parent_id, *, limit=100) -> list[LedgerInvoice]` to
  `MongoBillingLedgerRepository` (tenant-scoped on `invoices`, filter parent_id, sort created_at desc).
- Add the method to any `BillingLedgerReader`/port if a protocol exists; else expose via repo directly.
- **Tests** (contract, `tests/contract/`): seed two academies + two parents; assert parent A only sees A's
  invoices; tenant isolation (other academy returns none). Follow `test_session_type_billing_repos.py`.

### Task 2 — Parent invoices (routes + view + inline use case)
- `interfaces/parent/invoice_routes.py` (`prefix="/parent"`):
  `GET /parent/invoices` → list parent's invoices; `GET /parent/invoices/{invoice_id}` → single (404 if not
  owned / wrong academy). Inline callables `list_invoices_for_parent` / `get_invoice_for_parent` in
  `compose_parent` reusing `MongoBillingLedgerRepository` (already instantiated there) + `get_invoice`.
- Views in `views.py`: `ParentInvoiceView{invoice_id, period, status, total_cents, balance_due_cents,
  currency, due_date, pdf_url|None, created_at}`, `ParentInvoicesResponse{invoices:[...]}`,
  `ParentInvoiceDetailView` adding `lines:[{description, quantity, unit_amount_cents, amount_cents}]`.
  pdf_url derived from `pdf_artifact_id` (or Stripe invoice_pdf if present); None otherwise.
- Wire field into `ParentUseCases`/`ParentComposition`/`deps.py`; register router in `main.py`.
- **Tests** (interface): parent sees own invoices; detail returns lines; cross-parent/admin/coach → 404/wrong
  persona; anon → 401. Mirror existing parent interface tests; add a fake invoice repo to conftest.

### Task 3 — Child schedule
- `contexts/enrollment/application/use_cases/get_child_schedule.py`:
  `GetChildSchedule(enrollments, occurrences, sessions, students)`,
  `execute(parent_id, student_id, *, frm: date|None, to: date|None, limit, offset)`. Validates student
  belongs to parent (students lookup). Resolves student's active session enrollments → occurrences in range
  (default: next 30 days) → returns `ChildScheduleEntry{occurrence_id, session_id, session_title, start_at,
  end_at, status, coach_name|None}`.
- `interfaces/parent/schedule_routes.py`: `GET /parent/children/{student_id}/schedule?from=&to=&limit=&offset=`.
  404 if student not owned.
- Views: `ParentScheduleEntryView`, `ParentScheduleResponse{entries, total, limit, offset}`.
- Wire composition (`ParentComposition.get_child_schedule`) + deps + main.py.
- **Tests** (interface + a use-case/application unit test): happy path returns ordered upcoming occurrences;
  date-range filter; non-owned student → 404; pagination.

### Task 4 — Attendance/progress enrichment + pagination
- Extend inline `list_attendance_for_parent` / `list_progress_for_parent` in `compose_parent` to:
  (a) add `coach_name` (resolve coach_id → user/coach full name; None if unknown);
  (b) accept `limit`/`offset` (default 50/0) and return total count.
  (session_title already present for attendance; add it for progress where applicable.)
- Update views `ParentAttendanceResponse`/`ParentProgressResponse` to include pagination fields + coach_name.
- Update `activity_routes.py` `GET /parent/attendance` & `/parent/progress` to pass query params.
- **Tests** (interface): coach_name populated; pagination limits results + total correct; existing tests updated.

### Task 5 — Parent self-enroll in a session type
- `contexts/billing/application/use_cases/enroll_child_in_session_type.py`:
  `EnrollChildInSessionType(enrollments(StudentBillingEnrollmentRepository), session_types, stripe,
  student_owner_lookup, clock)`; `EnrollChildCommand{parent_id, student_id, session_type_id, success_url,
  cancel_url}`. Validates student ownership + session_type active; creates `StudentBillingEnrollment`
  (status active), starts Stripe subscription via `create_subscription_checkout_session`, persists
  enrollment with `stripe_subscription_id`. Returns `{enrollment, redirect_url}`.
  Define a `StudentOwnerLookup` port (is_owned(parent_id, student_id)->bool) implemented in composition.
- `CancelBillingEnrollment(enrollments, stripe)`; `execute(parent_id, enrollment_id)`: validate ownership,
  `stripe.cancel_subscription(sub_id, at_period_end=True)`, set status `cancelled`, save.
- `interfaces/parent/enrollment_routes.py`: `POST /parent/billing-enrollments`,
  `POST /parent/billing-enrollments/{enrollment_id}/cancel`.
- Views: request/response DTOs.
- Wire composition + deps + main.py. Use `FakeStripeGateway` in tests (no real keys).
- **Tests** (interface + application): create enrollment returns redirect_url + persisted enrollment;
  non-owned student → 403/404; inactive session type → 400; cancel sets status + calls
  `cancel_subscription`; cross-parent cancel → 404.

### Task 6 — Coach roster (view + add/remove)
- Route `GET /coach/sessions/{session_id}/roster` using existing `get_roster` (`GetSessionRoster`),
  guarded so a coach only sees rosters for sessions they're assigned to (`CoachAssignedSessionLookup`);
  not-assigned → 403.
- Coach add/remove use cases (enrollment ctx, guarded by assignment): `CoachAddStudentToRoster`,
  `CoachRemoveStudentFromRoster` — thin wrappers validating assignment then delegating to existing
  enrollment writes (`EditRosterAdd` / `WithdrawEnrollment`) or equivalent repo ops. Routes:
  `POST /coach/sessions/{session_id}/roster` (body {student_id}),
  `DELETE /coach/sessions/{session_id}/roster/{student_id}`.
- Wire into `CoachUseCases`/`CoachComposition`/`coach/deps.py`; register routes (new
  `interfaces/coach/roster_routes.py`).
- **Tests** (interface): assigned coach sees roster + can add/remove; unassigned coach → 403; parent/admin
  → wrong-persona 404; anon → 401.

### Task 7 — Bulk mark attendance
- `contexts/coaching/application/use_cases/bulk_mark_attendance.py`:
  `BulkMarkAttendance` reusing the attendance repo + occurrence/enrollment lookups + outbox +
  idempotency store. `BulkMarkAttendanceCommand{mutation_id, occurrence_id, session_id,
  entries:[{student_id, status}]}`; idempotent on `mutation_id`. Validates coach assignment + each student
  enrolled; persists all + appends events. Returns per-entry results.
- Route `POST /coach/occurrences/{occurrence_id}/attendance/bulk` in `attendance_routes.py` (or new file).
- Wire composition + deps.
- **Tests** (interface): bulk marks all; idempotent replay returns same; unassigned coach → 403;
  non-enrolled student entry → error (define: 422 whole batch).

### Task 8 — Session feedback (domain + repo + event + routes + migration)
- Domain: `contexts/coaching/domain/models.py` add `SessionFeedback` (frozen) {feedback_id, academy_id,
  session_id, occurrence_id|None, coach_id, student_id, body, rating|None, created_at}.
- Event: `Coaching.SessionFeedbackPosted` in coaching `events.py` (DomainEvent, schema_version=1).
- Port + repo: `SessionFeedbackRepository` (save, list_for_session, list_for_student);
  `infrastructure/mongo_session_feedback_repo.py` (collection `session_feedback`, TenantScoped).
- Use cases: `CreateSessionFeedback` (guard coach assignment + student enrolled, save, emit event via
  outbox), `ListSessionFeedback`.
- Routes (`interfaces/coach/feedback_routes.py`): `POST /coach/sessions/{session_id}/feedback`,
  `GET /coach/sessions/{session_id}/feedback`.
- Surface to parents: extend `list_progress_for_parent` to merge session feedback for the parent's students
  (or add `feedback` to the progress feed). Keep it additive; mark source.
- Migration `migrations/0112_phase1_portal.py`: indexes for `session_feedback`
  (`feedback_id` unique; `(academy_id, session_id)`; `(academy_id, student_id, created_at)`) and any
  invoices-by-parent index needed for Task 1 (`(academy_id, parent_id, created_at)`).
- **Tests** (contract for repo tenant-isolation; interface for routes; application for use case + event emit).

### Task 9 — Final integration
- Confirm all routers registered in `main.py`; `ParentComposition`/`CoachComposition`/deps in sync.
- Run full `uv run pytest v2/tests/{unit,contract,interface,application} -q` → all green.
- Run `uv run lint-imports` → green (DDD layering).
- Run migration runner against scratch Mongo (if available) or assert migration import-loads & defines
  `version`/`up`.

## Verification (per roadmap)
- Per task: targeted pytest module(s) green; whole suite green at the end; `lint-imports` green.
- Tenant isolation contract test for every new repo/method.
- No real Stripe keys: all Stripe via `FakeStripeGateway`.
