# Assistant Coach Role Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an academy-scoped **assistant_coach** role: a per-session helper who gets the coach shell scoped to sessions that list them as assistant and may only mark attendance, update skills, and write notes there. Never paid by payroll, never authors lesson plans, never edits rosters or billing, never messages families.

**Architecture:** New role literal `assistant_coach` (distinct from the existing per-occurrence coach-attendance role `"assistant"`, which is a payroll attendance concept). Sessions gain `assistant_coach_ids: list[str]`, copied onto every generated occurrence as `assistant_coach_ids` and re-synced onto future occurrences when the session's list changes. Coach-surface authority (`CoachAssignedSessionLookup.is_coach_assigned`, the attendance use cases' occurrence check, and the "sessions for coach" repository queries) treats an assistant id in that list like an assignment. `require_coach_surface()` admits the role; a new `require_coach_lead_surface()` (coach or supervisor, not assistant) guards the routes assistants must not reach. Payroll pays `actual_coach_id` else `scheduled_coach_id` and never sees the new list, so no payroll change. Frontend: `isAssistantCoach(roles)`, coach shell hides messaging/announcements/billing/pay, admin session detail gets an assistants editor, admins may grant `assistant_coach` (operations role).

**Spec:** `docs/superpowers/specs/2026-09-04-role-model-and-screens-design.md` (assistant row of the matrix; decision: assistants are never on payroll). Template PR for the authority threading: #632 admin coach coverage (`docs/superpowers/specs/2026-09-02-admin-coach-coverage-design.md`).

## Global Constraints

- Work only in `/Users/ramc/Documents/Code/academy-manager/.worktrees/assistant-coach` (branch `feat/assistant-coach`). Backend venv symlinked; frontend deps installed. Do not push.
- `Role` literal is duplicated by hand in `backend/v2/shared/auth/claims.py:40` and `backend/v2/contexts/identity/domain/models.py:46`; change BOTH or membership rows fail to deserialize. Role name is exactly `assistant_coach`.
- Guards return 404 on missing role. Assistants must never satisfy `is_coach_supervisor`.
- `backend/v2/composition/admin.py` is at its 4800-line cap: extract rather than add there.
- Memberships validator (migration 0132) stores roles as free strings: no migration needed for the role. Occurrence/session validators (0133) may list properties: check whether they forbid additional properties; if so add migration `0166_session_assistant_coach_ids` that widens them and backfills `assistant_coach_ids: []` (idempotent). Boot migrations are off in prod; the release note must say so.
- Keep every existing coach data-testid stable for real coaches. Hide with conditional rendering, not CSS.
- Commit trailer: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Hooks block `--amend`/rebase.

## Contract between backend and frontend (both agents rely on this)

- `/api/v2/me` `roles` may contain `"assistant_coach"`.
- `AdminSessionView.assistant_coach_ids: list[str]` (default `[]`) and `assistant_coach_names: list[str]` (resolved like `coach_name`); `CreateSessionRequest.assistant_coach_ids: list[str] = []`; `EditSessionRequest.assistant_coach_ids: list[str] | None = None` (None = unchanged, `[]` = clear). Plus `PUT /api/v2/admin/sessions/{session_id}/assistants` with body `{ "assistant_coach_ids": [...], "reason": str | None }` returning `AdminSessionView`, for the dedicated editor.
- Admin directory: `assistant_coach` is a valid role value everywhere `coach` is (create user, add/remove/replace role, list filter); admins (not just owners) may grant it (`ensure_can_assign_role` leaves it open).
- Coach routes an assistant may call (unchanged shapes): `/today`, `/today/plan`, `/sessions`, `/dashboard`, `/profile` (GET+PATCH), `/day-hub`, all `/attendance*`, all `skill_routes.py`, `notes_routes.py` GET+POST `/progress-notes`, GET `/lesson-plans`, GET `/teaching-plan`, GET `/sessions/{id}/roster`. Everything else on the coach BFF returns 404 for assistants.

---

### Task 1 (backend): role literal, session/occurrence field, queries, authority, guards, admin editor

**Files (create/modify):**
- `backend/v2/shared/auth/claims.py:40`, `backend/v2/contexts/identity/domain/models.py:46` (+ docstring), `backend/v2/contexts/identity/infrastructure/mongo_user_repo.py:53-58` (`_ROLE_PRIVILEGE`: student 0, parent 0, assistant_coach 1, coach 2, admin 3, owner 4; update `backend/v2/scripts/reconcile_membership_roles.py` if it hard-codes values)
- `backend/v2/interfaces/admin/views.py` role Literals at :23, :29, :58, :210, :215 and `directory_routes.py:78, :207`
- `backend/v2/shared/http/persona.py`: `require_coach_surface()` admits `assistant_coach`; add `require_coach_lead_surface()`; add `is_assistant_only(claims) -> bool`
- `backend/v2/contexts/enrollment/domain/models.py`: `Session.assistant_coach_ids: tuple[str, ...] = ()` (:32 area), `SessionOccurrence.assistant_coach_ids: tuple[str, ...] = ()` (:83 area)
- `backend/v2/contexts/enrollment/application/use_cases/generate_session_occurrences.py:65` copy the list onto occurrences
- Repos: `mongo_session_repo.py` `for_coach`, `for_coach_on_date`, `assigned_session_ids_for_coach` → `$or: [{coach_id}, {assistant_coach_ids: coach_id}]`; `mongo_occurrence_repo.py` `list_for_coach_on_date`, `list_for_coach_upcoming` → add `{assistant_coach_ids: coach_id}` to the `$or`; persistence of the new fields in both repos
- `backend/v2/composition/coach.py:199-228` `is_coach_assigned`: True when `coach_id in session.assistant_coach_ids`
- Attendance use cases `mark_attendance.py:132-142`, `bulk_mark_attendance.py:121`, `correct_attendance.py:108-110`: the allowed set also includes `occurrence.assistant_coach_ids`. Leave `mark_coach_attendance.py` alone (assistants do not self-mark payroll attendance).
- Admin: `sessions_routes.py` create/edit accept `assistant_coach_ids`; new `PUT /sessions/{session_id}/assistants` (admin persona); use case `SetSessionAssistants` in a NEW module `backend/v2/composition/admin_session_staff.py` (validates each id is an active membership holding `coach` or `assistant_coach`, updates the session, re-syncs `assistant_coach_ids` on all FUTURE occurrences of that session); `AdminSessionView.assistant_coach_ids` + `assistant_coach_names`
- Guard application (`require_coach_lead_surface()`): `notes_routes.py` POST `/lesson-plans`; `roster_routes.py` POST + DELETE; all of `billing_enrollment_routes.py`; all of `messages_routes.py`; all of `announcement_routes.py`; `feedback_routes.py` POST + GET. Also `composition/coach.py:313-328` `_visible_session_ids` must NOT include assistant sessions (assistants are not a messaging audience).
- Seed `backend/scripts/seed_local.py`: user `helper@blno.academy` with `roles: ["assistant_coach"]`, no `coach_rates` row, listed as assistant on the first seeded session.
- Tests: `tests/interface/conftest.py` `_assistant_coach_claims()` (`user_id="asst-1"`, roles `("assistant_coach",)`) + `assistant_client` fixture; teach the `_SL` fake (:585-597) and the other `is_coach_assigned` fakes an `assistant_ids_by_session`; new `tests/interface/test_assistant_coach.py` modelled on `test_coach_admin_coverage.py`: assistant sees only assigned sessions on `/today` and `/sessions`; can mark attendance (single + bulk) and set a skill status and post a progress note on an assigned session; gets 404 on an unassigned session's attendance; gets 404 on lesson-plan POST, roster POST, billing-enrollments GET, messages GET, announcements GET, feedback POST; `is_coach_supervisor` false for assistant; admin PUT `/assistants` rejects a parent id (422) and accepts a coach id, and future occurrences carry the ids; `_ROLE_PRIVILEGE` ordering test; structural test that every coach route is guarded by exactly one of the two coach guards. Payroll contract test: an occurrence with `assistant_coach_ids` still pays `actual_coach_id`/`scheduled_coach_id` only (`tests/contract/test_coach_payout_snapshot_reader.py` neighbour).
- Migration check per Global Constraints (0133 validators).

- [ ] Steps: implement in the order listed, running `cd backend && .venv/bin/ruff format v2 && .venv/bin/ruff check v2 && .venv/bin/pytest v2/tests -n auto -q --tb=short` at the end (must be green). Also run mypy on changed modules from the repo root: `backend/.venv/bin/mypy --config-file backend/pyproject.toml <files>` and make sure no NEW errors appear (pre-existing ones are in `backend/mypy-baseline.txt`).
- [ ] Commit (one or two commits): `feat(coaching): assistant_coach role — session assistants, scoped coach surface, lead-only guards`.

---

### Task 2 (frontend): types, coach shell gating, admin assistants editor, role options, e2e

**Files:**
- `frontend/lib/api/me.ts:3` add `"assistant_coach"` to `UserRole`; `PersonaRole = Exclude<UserRole, "owner" | "assistant_coach">`; `homeForRoles`: assistant_coach → `/coach/today`
- `frontend/lib/api/v2/memberships.ts:11` `MembershipRole` + `"assistant_coach"`; `frontend/lib/api/admin.ts:1129` `AdminUserRole` + `"assistant_coach"`; `AdminSessionView`-typed client types gain `assistant_coach_ids: string[]`, `assistant_coach_names: string[]`; client `setSessionAssistants(sessionId, ids, reason?)` → `PUT /api/v2/admin/sessions/{id}/assistants`
- `frontend/lib/auth/coach-supervisor.ts`: `COACH_SURFACE_ROLES = ["coach", "assistant_coach", ...COACH_SUPERVISOR_ROLES]`, `isAssistantCoach(roles)` (true only when roles include assistant_coach and NOT coach/admin/owner); `availablePersonaViews` maps assistant_coach to the coach view; node test additions
- `frontend/app/(coach)/layout.tsx:39` allow-list → `COACH_SURFACE_ROLES`; when `isAssistantCoach`: hide Messages link and skip the messages query, show banner `data-testid="coach-assistant-banner"` "Assistant coach. You see the sessions you're assigned to and can mark attendance, update skills and add notes."; `/coach/messages` renders an access-denied notice for assistants
- `frontend/app/(coach)/coach/sessions/[id]/page.tsx`: hide `AnnouncementsPanel`, `BillingPreviewDrawer` and its toggle for assistants
- `frontend/app/(coach)/coach/profile/page.tsx:101-109`: hide Pay & statements card for assistants
- Admin session detail `frontend/app/(admin)/admin/sessions/[id]/page.tsx` + `SessionEditing.tsx`: a "Coaching staff" lane above "Replacement coaches" showing primary coach, and an **Assistants** editor: chips of current assistant names + "Edit assistants" dialog listing academy users holding coach or assistant_coach (reuse the existing users list API used by the coach picker) with checkboxes; saves via `setSessionAssistants`; testids `session-assistants`, `edit-assistants`, `assistant-option-<userId>`
- Role options: `roles-panel.tsx:22`, `users/new/page.tsx:10`, `users/[userId]/page.tsx:36`, `AdminUsersDirectory.tsx` filter tabs and create form: add `assistant_coach` (label "Assistant coach") wherever `coach` appears; owner-only rule unchanged (`assignableRoles` from PR #660 lets admins assign it); `lib/admin/role-chip.ts` colour for it
- e2e: `frontend/e2e/fixtures/saas-stubs.ts` `RoleName` + `"assistant_coach"`, add `ASSISTANT_USER`; `frontend/e2e/fixtures/mock-api.ts:324` support an assistant `/me` variant; new spec `frontend/e2e/specs/coach-assistant.spec.ts`: assistant on `/coach/today` sees the banner, no Messages link, session detail has attendance buttons and no announcements panel or billing toggle, profile has no pay card, `/coach/messages` shows the denied notice; admin-shell addition: session detail shows `session-assistants` and the editor opens (stub the PUT). Update `local-auth-inventory.spec.ts:34` comment (seed now has an assistant). Route manifest: `frontend/e2e/specs/coach-assistant.spec.ts` adds NO routes, so no manifest change; verify `pnpm test:unit` route-count audits still pass.
- Run `pnpm test:unit && pnpm test:node && pnpm lint && pnpm typecheck`, then `pnpm exec playwright test e2e/specs/coach-assistant.spec.ts e2e/specs/coach-today.spec.ts e2e/specs/coach-day-hub-passport.spec.ts e2e/specs/admin-shell.spec.ts --project=chromium-desktop --project=chromium-mobile --reporter=line`.
- [ ] Commit: `feat(coach): assistant coach shell — scoped banner, lead-only surfaces hidden; admin session assistants editor`.

---

### Task 3 (orchestrator): release note, PR, deploy

- Release note `docs/release-notes/2026-09-06-assistant-coach-role.md`: what changed; deploy notes (any 0166 migration runs by hand; grant `assistant_coach` from the user's page; assign per session from the session detail "Assistants" editor); risk/rollback.
- Push, PR, CI, merge, run pending migrations in prod via `fly ssh console` if 0166 exists, verify an assistant user in prod after the owner assigns one.
