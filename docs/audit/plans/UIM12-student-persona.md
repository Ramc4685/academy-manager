# UIM12 — Student login persona
Status: TODO
Size: L · Depends on: none (parent invite flow PR #297/298 is the template) · Tracker: ../TRACKER.md

## User value
Older students (teens/adults) want to see their own schedule and skill progress without going through a parent's account. A minimal read-only student login also unblocks adult-learner academies where "parent" is a fiction.

## Backend status (verified)
- `enable_student_login: bool = Field(default=False)` exists and is **inert** — `backend/v2/shared/config/settings.py:59`; nothing reads it.
- No `backend/v2/interfaces/student/` package exists (admin/coach/parent/platform only).
- No `frontend/app/(student)` route group exists.
- **The identity model has no student concept.** `Role = Literal["admin","coach","parent"]` (`backend/v2/contexts/identity/domain/models.py:35`); `AcademyMembership` roles are drawn from that literal. The `Student` domain model (`backend/v2/contexts/enrollment/domain/models.py:70`) is `{ student_id, academy_id, parent_id, full_name, date_of_birth? }` — **no user link field**. A student today is a record owned by a parent, not a principal.
- Reusable pieces: parent read use cases (`get_child_schedule` behind `GET /parent/children/{student_id}/schedule`, `parent/schedule_routes.py:20`; progress/passport reads in coach/parent contexts); invite machinery `send_login_invite` / `provision_parent_login` (`backend/v2/contexts/identity/application/use_cases/`) which provisions a Firebase account and emails a password-reset link that also marks email verified (the PR #297/298 pattern — and note the prod Firebase enumeration gotcha: check `get_user_by_email` before `generate_password_reset_link`).

## The identity-model work (this is the L part — be honest about it)
A student login needs a **student ↔ user linkage** plus persona plumbing:
1. `Student.student_user_id: str | None` — new optional field on the enrollment-context Student model + Mongo docs (no migration needed; absent = no login). Uniqueness: one user per student per academy, enforced at link time.
2. `Role` literal gains `"student"`; `AcademyMembership` with `roles=("student",)` created when a student login is provisioned. Claims loading (`load_auth_claims.py`) must map that membership to a `student` persona AND resolve which `student_id` the user is — recommended: store the link on the Student doc (authoritative) and look it up at claims time or in the student BFF deps.
3. Invite flow `ProvisionStudentLogin` mirroring `provision_parent_login` + `send_login_invite`: admin (or parent, later) supplies an email for a student → create Firebase user, create membership, stamp `student_user_id`, send set-password link. Admin route `POST /admin/students/{student_id}/login-invite`.
4. Decisions to settle in the PR (document in the ADR-style docstring): minimum-age policy is a product setting, not code; unlinking/revocation (revoke membership + clear `student_user_id`); a user being both parent and student is allowed by the membership model — persona routing follows the requested BFF.

## Backend to build (Phase 1 — one PR)
Read-only `backend/v2/interfaces/student/` package, entirely behind `enable_student_login` (flag off → routes 404):
- `deps.py` with `StudentUseCases` + `get_student_use_cases` resolving `student_id` from claims; `require_persona("student")` support in `backend/v2/shared/http`; wrong-persona 404.
- `GET /student/schedule` — reuse the same application-layer schedule query that powers the parent child-schedule route, invoked with the claims-resolved `student_id` (do NOT import the parent interface; share at the use-case layer per DDD rules).
- `GET /student/progress` — reuse existing progress/passport read use cases the same way.
- `GET /student/me` — name, academy, level (small profile read).
- Identity work from the section above (link field, role, provision use case, admin invite route).
- Register every new route in `backend/v2/tests/unit/test_audit_inventory_manifest.py`.
- Tests: claims → student_id resolution; flag-off 404; wrong-persona 404; a parent token cannot hit /student/* and vice versa; invite idempotency.

## Frontend to build (Phase 2 — one PR)
Minimal `frontend/app/(student)` route group:
- Layout with role gating (student membership required) mirroring the other persona layouts.
- `/student/dashboard` (next sessions + level summary), `/student/schedule`, `/student/progress` — read-only, reusing existing schedule/progress display components where they aren't parent-specific.
- Data layer: `apiFetch` client module `frontend/lib/api/v2/student.ts`; `student` namespace in `frontend/lib/query/keys.ts`; TanStack Query v5.
- Login itself reuses the existing Firebase password login; only role routing changes.

## Implementation steps (phased; each phase one PR)
1. **Phase 1a (identity):** `student` role + `student_user_id` link + `ProvisionStudentLogin` + admin invite route + tests.
2. **Phase 1b (student BFF):** `interfaces/student/` read routes + composition wiring + manifest + tests. (1a and 1b can be one PR if reviewable; the seam is clean if split.)
3. **Phase 2 (frontend):** `(student)` route group + client + keys.

## Flag rollout
Ship dark (`enable_student_login=False`). Staging: seed a student, provision login, walk the three pages. Enable per-academy decision in prod; flag is the kill switch.

## Files to change/create
- `backend/v2/contexts/identity/domain/models.py`, `application/use_cases/{load_auth_claims,provision_student_login}.py`, `manage_user_roles.py`.
- `backend/v2/contexts/enrollment/domain/models.py` (Student field) + its Mongo repo mapping.
- `backend/v2/interfaces/student/{__init__,router,deps,schedule_routes,progress_routes,me_routes}.py`; admin `directory_routes.py` or `progress_routes.py` for the invite route; app router; `backend/v2/tests/unit/test_audit_inventory_manifest.py`.
- `frontend/app/(student)/**`; `frontend/lib/api/v2/student.ts`; `frontend/lib/query/keys.ts`.

## Verification
- Backend unit/interface tests above; import-linter green (no cross-interface imports; sharing only at application layer).
- E2E (staging): invite email → set password → land on /student/dashboard → schedule + progress match what the parent view shows for the same student.
- Firebase gotcha check: invite against a non-existent prod account path uses `get_user_by_email` first (PR #304 postmortem).

## Risks / rollback
- Identity changes touch claims loading for every persona — keep the `student` branch strictly additive and covered by regression tests for admin/coach/parent claims.
- A mis-resolved `student_id` would show someone else's child's data: the claims→student resolution test matrix is the critical control. Security-reviewer pass recommended on Phase 1.
- Rollback: flag off (instant); revert PRs; `student_user_id` fields left behind are inert.

## PR checklist (per phase)
- [ ] Release note line
- [ ] TRACKER.md row updated (Status, PR/Issue)
- [ ] This plan's Status → DONE (PR #NNN, date) after Phase 2
