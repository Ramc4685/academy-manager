# C4 — Kill boot-time academy_id closures (parent reads + coach writes)
Status: DONE (PR #317, 2026-07-20)
Size: M · Depends on: none · Tracker: ../TRACKER.md

## Problem

Several parent read paths and coach write paths bind `academy_id` **once at process boot** instead of resolving it per-request. `compose_parent` (`backend/v2/composition/parent.py:391-400`) takes `academy_id` as a parameter; `main.py:239-245` passes `runtime_academy_id` computed at startup (`main.py:147`, from `_runtime_academy_id(settings)` at `main.py:584-590`). `compose_coach` (`backend/v2/composition/coach.py:214-220`) captures `settings.default_academy_id` directly. Every inline function that closes over that value queries or writes the **boot** tenant regardless of the request's tenant. The moment `APP_TENANCY_MODE=multi_academy` is live traffic (settings fallback at `backend/v2/shared/config/settings.py:146-147`), these paths leak/write cross-tenant. This exact bug class already shipped once (self-cancel fee line, fixed in PR #289 — see the fix comment at `parent.py:642-645`). GAPS.md #1 documents the coach half with an explicit in-code TODO (`coach.py:371-373`).

## Current behavior (verified)

**The correct pattern already exists** — `parent.py:640-646` inside `_SelfCancelFeeBillingPort`:

```python
# Request-time tenant, not the composition-time closure:
# every repo in this flow scopes by the ContextVar, and a
# multi-tenant process would otherwise write the fee line
# to the boot academy while cancelling in another.
academy_id=current_academy_id(),
```

(`current_academy_id` imported at `parent.py:198` from `backend.v2.shared.tenancy`.)

**Parent offenders (closure over the boot `academy_id`):**

- `list_payments_for_parent` (`parent.py:721-826`): raw queries `db["ledger_payments"].find({"academy_id": academy_id, ...})` (:755-756), `db["payment_allocations"].find({"academy_id": academy_id, ...})` (:789-790), `db["invoices"].find({"academy_id": academy_id, ...})` (:798-801).
- `_parent_students` (`parent.py:831-842`): `db["students"].find({"academy_id": academy_id, ...})` (:836).
- `list_children_for_parent` (`parent.py:844-872`): `db["enrollments"].count_documents({"academy_id": academy_id, ...})` (:849-851), two `db["attendance"].count_documents` (:852-861).
- `list_enrollments_for_parent` (`parent.py:874-...`): `db["parent_billing_customers"].find_one` (:879-881), `db["enrollments"].find` (:899-908), `db["sessions"].find_one` (:914-916), `db["student_billing_enrollments"].find_one` (:917-923).
- Additional closure captures in the same file (use-case constructor args, same residue class): `ConfirmEnrollment` (:670-679), `PromoteFromWaitlist` (:680-687), `AcceptParentWaiver` (:694), `StartApplication` (:695). Enumerate the full set during implementation with `grep -n "academy_id=academy_id\|\"academy_id\": academy_id" backend/v2/composition/parent.py`.

**Coach offenders (`composition/coach.py`):**

- `:222` — `MongoUserRepository(db, default_academy_id=settings.default_academy_id)`.
- `:238-243` — a request-time helper **already exists**:
  ```python
  def request_academy_id() -> str:
      try:
          return current_academy_id()
      except TenantContextUnset:
          return settings.default_academy_id
  ```
  and is used by `get_dashboard_metrics` (:245). Writes don't use it.
- `:344-351` — `MarkAttendance(..., academy_id=settings.default_academy_id)` (class at `backend/v2/contexts/coaching/application/use_cases/mark_attendance.py:70`).
- `:352-359` — `BulkMarkAttendance(..., academy_id=settings.default_academy_id)` (`.../bulk_mark_attendance.py`).
- `:371-380` — the TODO ("academy_id is baked in at startup ... must be replaced with per-request tenant resolution before multi-tenant rollout") above `CoachAddStudentToRoster(..., academy_id=settings.default_academy_id)` (class at `backend/v2/contexts/enrollment/application/use_cases/coach_roster_writes.py:43`).

**Known residue explicitly out of scope here** (note in PR, file follow-ups): `composition/admin.py` (~:2560, :2941 per GAPS.md #1) and the structural test extension (tracker item MT4, "Depends on: C4 ideally after").

## Proposed change

Two mechanical conversions, both to request-time resolution via the tenancy ContextVar:

1. **Parent inline read functions**: at the top of each offending function body, add `academy_id = current_academy_id()` (shadowing the closure), exactly mirroring the :646 pattern. No signature changes; callers (parent interface routes) are unaffected. This is the tactical fix — moving these raw queries into `TenantScopedRepository` read models is GAPS.md #2 / MT-scope, *not* this plan.
2. **Use cases constructed with `academy_id: str`** (coach writes + the parent use-case constructor args listed above): change the constructor parameter from `academy_id: str` to `academy_id: Callable[[], str]` (a zero-arg provider), call it inside `execute()` at the point of use. In `compose_coach`, pass the existing `request_academy_id` helper; in `compose_parent`, pass a module-level equivalent `lambda: current_academy_id()` wrapped with the same `TenantContextUnset → boot value` fallback so single-academy behavior is byte-identical. Delete the TODO at `coach.py:371-373` as part of the change.

Rationale for the provider over resolving inside composition wrappers: the use cases stamp `academy_id` on domain events and documents at execute time; a provider keeps that stamping in one place and makes the boot-time-capture pattern impossible to reintroduce silently. The fallback-to-boot-value keeps today's single-academy deployment (tenancy middleware already forces `primary_academy_id` in `single_academy` mode) behaviorally unchanged.

`MongoUserRepository`'s `default_academy_id` (coach.py:222) follows the repo's own default-tenant convention — verify during implementation whether it scopes queries by ContextVar internally (it is a `TenantScopedRepository` question); convert only if it uses the value per-query.

## Implementation steps

Do one converted path per commit; keep each commit green.

1. **Parent reads** (`composition/parent.py`): insert `academy_id = current_academy_id()` as the first line of `list_payments_for_parent`, `_parent_students`, `list_children_for_parent`, `list_enrollments_for_parent`. Run the grep from above and convert any remaining inline raw-query closure the same way (`list_attendance_for_parent`, `list_progress_for_parent`, `get_academy_info` per GAPS.md #2 if they close over it).
2. **Coach writes**:
   a. `contexts/coaching/application/use_cases/mark_attendance.py` and `bulk_mark_attendance.py`: constructor `academy_id: Callable[[], str]`; replace `self._academy_id` reads with `self._academy_id()` at execute time.
   b. `contexts/enrollment/application/use_cases/coach_roster_writes.py` (`CoachAddStudentToRoster`): same conversion.
   c. `composition/coach.py`: pass `request_academy_id` at :350, :358, :379; delete the TODO at :371-373.
3. **Parent use-case constructor args** (`ConfirmEnrollment`, `PromoteFromWaitlist`, `AcceptParentWaiter`/`AcceptParentWaiver`, `StartApplication` — plus any others the grep finds in `enrollment`/`registration` contexts): same provider conversion; in `compose_parent` pass a `request_academy_id`-style helper (add one near the top of `compose_parent`, fallback to the boot `academy_id` argument).
4. **Fix all constructor call sites** each conversion breaks — tests construct these use cases directly; update `backend/v2/tests/**` fakes/builders to pass `lambda: "test-academy"` (grep per class name).
5. **Tenant-isolation test per converted path** (see Tests below).
6. Update `GAPS.md` #1 status note and leave admin.py residue + MT4 pointers.

## Files to change

- `backend/v2/composition/parent.py`
- `backend/v2/composition/coach.py`
- `backend/v2/contexts/coaching/application/use_cases/mark_attendance.py`
- `backend/v2/contexts/coaching/application/use_cases/bulk_mark_attendance.py`
- `backend/v2/contexts/enrollment/application/use_cases/coach_roster_writes.py`
- `backend/v2/contexts/enrollment/application/use_cases/confirm_enrollment.py`, `promote_from_waitlist.py`; registration-context `AcceptParentWaiver`/`StartApplication` use-case files (locate via the class-name grep)
- `backend/v2/tests/**` (constructor call sites + new isolation tests)
- `GAPS.md` (#1 status)

## Tests & verification

New tests — one per converted path, colocated with existing composition/contract tests (`backend/v2/tests/composition/`, `backend/v2/tests/contract/`; mirror the style of the existing suites that use `tenant_scope`):

- **Pattern (writes)**: compose against mongomock with boot academy `A`; inside `tenant_scope("academy-B")` execute `MarkAttendance` / `BulkMarkAttendance` / `CoachAddStudentToRoster`; assert the persisted attendance/enrollment doc has `academy_id == "academy-B"` (would be `"A"` before the fix). Repeat for `ConfirmEnrollment`, `PromoteFromWaitlist`, waiver/application starts.
- **Pattern (reads)**: seed identical parent/student data under academies `A` and `B` with boot academy `A`; inside `tenant_scope("academy-B")` call `list_payments_for_parent`, `list_children_for_parent`, `list_enrollments_for_parent`; assert only `B` rows return (before the fix, `A` rows return).
- **Fallback**: outside any `tenant_scope`, coach writes still land in `settings.default_academy_id` (single-academy behavior preserved).

```bash
cd backend && pytest v2/tests -q
cd backend && pytest v2/tests/structural v2/tests/test_no_raw_tenant_mongo_access.py -q
cd backend && ruff check v2 && lint-imports --config pyproject.toml
```

Log via `scripts/dev/test_result.py log` per AGENTS.md. Follow-up (tracked as MT4, not in this PR): structural test asserting no `academy_id=settings.default_academy_id` / boot-closure constructions remain in `composition/`.

## Risks / rollback

- **Behavior change if a path runs without tenant context** (schedulers, outbox handlers, webhook processors call these outside a request): the `TenantContextUnset → boot value` fallback makes those identical to today. Audit each converted use case's non-HTTP callers (grep for the use-case attribute names in `main.py` scheduler/dispatcher wiring) before merging.
- **Missed constructor call site** → test collection fails loudly (TypeError), caught in CI.
- **Webhook path** (`compose_parent_webhook_handler`, `parent.py:298-306`) intentionally keeps per-academy explicit `academy_id` (it is dispatched per academy at `main.py:246`); do not convert it.
- Rollback: pure code revert; no migrations, no data written differently in single-academy prod (fallback preserves current stamping).

## PR checklist

- [ ] Release note in docs/release-notes/ (per AGENTS.md)
- [ ] TRACKER.md status updated
- [ ] This plan's Status line flipped to DONE
