# Coach attendance + skills on phones, note visibility (slice 3) — implementation plan

> **For agentic workers:** this plan is executed by a Workflow (backend agent + frontend agent in parallel, then review, fix, verify). Each agent owns a disjoint file set. Do NOT `git commit` — the orchestrator commits between phases. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build-order item 3 of `docs/superpowers/specs/2026-09-04-role-model-and-screens-design.md`: (1) one-tap attendance on phones with a bulk "All present" action and honest offline/queued state, (2) skill screens as cards below the medium breakpoint with 44px targets, (3) coach notes carry a `visibility` flag — private by default, explicit share-with-parent, parents see only shared notes, assistant coaches may write notes but never share them, owner/admin see every note.

**Architecture:** `ProgressNote` and `CoachSkillNote` gain `visibility: Literal["private", "shared"]` (default `"private"`, missing field reads as private). Creation accepts an optional `visibility`; a new PATCH per note flips it. Both refuse `shared` from an assistant-only caller with **403** `Coaching.NoteShareForbidden` (a forbidden action on an allowed surface — not the 404 wrong-persona rule). The parent progress feed filters `visibility == "shared"`. Supervisors (owner/admin) listing a session's progress notes see every author's notes; coaches keep seeing their own. Migration `0167` backfills existing notes as private (runs BY HAND in prod: boot migrations are off, #629). Frontend: the roster row becomes a phone-first control (44px Present/Absent, queued state from the existing IndexedDB queue in `lib/offline/`), the note box gets a "Share with parent" switch hidden for assistants, existing notes list with a visibility chip and a share/unshare toggle; passport/skill-board controls go to 44px; the 10-device matrix verifies the four coach screens.

**Prior slices (pattern):** `docs/superpowers/plans/2026-09-05-owner-admin-split.md` (PR #660), `docs/superpowers/plans/2026-09-06-assistant-coach.md` (PR #663).

## Decisions where the spec is silent (made 2026-09-05, do not re-litigate)

1. **Existing notes become private.** The migration marks every existing progress note and skill note `private`; parents who saw them before stop seeing them until a coach shares. This is the locked "default to private" decision applied to history.
2. **Assistants cannot change visibility at all.** POST with `visibility: "shared"` and any PATCH from an assistant-only caller → 403. (Unsharing is a visibility change too; keeping one rule is simpler than two.)
3. **Visibility can be changed after creation** by the note's author or a supervisor (owner/admin). A coach who is neither → 404 (the note is not theirs to see).
4. **Supervisors see all authors' progress notes** for a session (`ListProgressNotes` drops the author filter for supervisors). Skill notes already list every author's notes for a student+skill; unchanged.
5. **Offline attendance** enables the dormant Wave-1B queue for *first marks only*: a tap while offline enqueues `POST /coach/attendance` in IndexedDB and shows "Queued"; a second tap on the same student while offline rewrites the same queued mutation (policy case #1, last write wins on device); "Mark all present" offline enqueues one mutation per unmarked student; sync on reconnect uses the existing `startAutoSync`/`syncNow`. Changing a **server-saved** mark while offline stays disabled with a hint, because the queue only replays creates and a queued correction would only 409 into the tray.
6. **Skill notes are not shown to parents today** (the parent "skill updates" feed reads status changes from `student_progress`, not `coach_skill_notes`). The flag is added to skill notes for the assistant rule and for future parent surfaces; no parent read change for skill notes.
7. **Skill cards already exist below `md`** (`components/pathway/skill-board.tsx` hides its table under `md:` and renders chips/cards; the passport and the session skills page are already lists). Item 2 is therefore: raise every phone control to 44px, add stable test ids, and prove it on the device matrix — not a rewrite.

## Global constraints

- Work only in `/Users/ramc/Documents/Code/academy-manager/.worktrees/coach-slice3` (branch `feat/coach-phone-slice3`). Backend venv is symlinked; frontend deps installed. Never touch the main checkout. Do not push.
- Do NOT run `git commit` / `git add` — the orchestrator commits. Leave the tree dirty.
- Backend commands from `backend/`: `.venv/bin/ruff format v2 && .venv/bin/ruff check v2 && .venv/bin/pytest v2/tests -n auto -q --tb=short`. Mypy from the repo root on changed files: `backend/.venv/bin/mypy --config-file backend/pyproject.toml <files>`; no NEW errors vs `backend/mypy-baseline.txt`.
- Frontend commands from `frontend/`: `pnpm test:unit && pnpm test:node && pnpm lint && pnpm typecheck`; Playwright with `--project=chromium-desktop --project=chromium-mobile --reporter=line` (the port is per-worktree; do not set `PLAYWRIGHT_PORT`).
- `backend/v2/composition/admin.py` is at its 4800-line cap — this slice must not touch it (composition changes go in `composition/coach.py` / `composition/parent.py`).
- Every coach BFF route must carry exactly one of `require_coach_surface` / `require_coach_lead_surface` (`tests/structural/test_coach_lead_gate_policy.py`). The new PATCH routes use `require_coach_surface` and enforce the assistant rule in the route body, so the lead-only set does NOT change.
- No new frontend routes → no audit-manifest change.
- Keep every existing coach `data-testid` stable: `session-detail`, `roster`, `roster-<studentId>`, `mark-<studentId>-present`, `mark-<studentId>-absent`, `mark-error-<studentId>`, `mark-all-present`, `billing-toggle-<studentId>`, `session-coach-name`, `coach-session-skills`, `coach-student-passport`, `skill-board`, `skill-board-level-<n>`, `by-skill-student-<studentId>`, `skill-cell-editor`, `quick-pass`, `needs-review`, `tray-list`, `tray-empty`.
- Styling: Tailwind, `min-h-touch`/`min-h-[44px]` for phone targets; no new inline hex colours beyond what the file already uses.
- Migrations are append-only; next free prefix is `0167` (0165 has two files, 0166 exists). Version string equals the filename stem.

## Contract between backend and frontend (both agents rely on this — do not deviate)

```
NoteVisibility = "private" | "shared"

ProgressNote (GET/POST /api/v2/coach/sessions/{session_id}/progress-notes):
  { note_id, session_id, student_id, coach_id, body, created_at, visibility }
POST body: { student_id: str, body: str, visibility?: NoteVisibility = "private" }
PATCH /api/v2/coach/sessions/{session_id}/progress-notes/{note_id}
  body { visibility: NoteVisibility } -> ProgressNoteView (200)

SkillNote (GET/POST /api/v2/coach/students/{student_id}/skill-notes):
  { note_id, academy_id, student_id, skill_id, coach_id, session_id, body, created_at, visibility }
POST body: { skill_id: str, body: str, visibility?: NoteVisibility = "private" }  (201)
PATCH /api/v2/coach/students/{student_id}/skill-notes/{note_id}
  body { visibility: NoteVisibility } -> SkillNote (200)

Errors:
  403 {"error": {"code": "Coaching.NoteShareForbidden", "message": ...}}
      — assistant-only caller sent visibility "shared" on POST, or any PATCH.
  404 Coaching.NoteNotFound — PATCH on a note that does not exist in this
      session/student, or that a non-supervisor did not author.
  Existing 404/409 behaviour for unassigned sessions/students is unchanged.

GET progress-notes: supervisors (owner/admin) receive every author's notes for
the session; coaches and assistants receive only their own. Rows carry
`visibility`. Sorted created_at desc (unchanged).

Parent GET /api/v2/parent/progress: progress_note rows are only those with
visibility == "shared" (docs without the field are private). Feedback rows
unchanged. Response shape unchanged (no visibility field needed).

/api/v2/me is unchanged; the frontend derives "assistant" from
`useIsAssistantCoach()` (components/coach/coach-surface-context.tsx).
```

---

### Task 1 (backend agent): visibility on both note kinds, PATCH routes, supervisor listing, parent filter, migration 0167, tests

**Files (modify):**
- `backend/v2/contexts/coaching/domain/errors.py`: add `NoteShareForbidden` (code `Coaching.NoteShareForbidden`, status 403) and `NoteNotFound` (code `Coaching.NoteNotFound`, status 404).
- `backend/v2/contexts/coaching/domain/models.py`: `CoachSkillNote.visibility: NoteVisibility = "private"`; define `NoteVisibility = Literal["private", "shared"]` here (domain) and import it where needed (`shared/` must not import `contexts/`; the interface layer may).
- `backend/v2/contexts/coaching/application/use_cases/session_notes.py`: `ProgressNote.visibility` (default private); `CreateProgressNoteCommand.visibility` (default private) + `is_assistant: bool = False` → raise `NoteShareForbidden` when `is_assistant and visibility == "shared"`; `ListProgressNotes.execute(coach_id, session_id, *, all_authors: bool = False)`; new `SetProgressNoteVisibility` use case with command `{coach_id, session_id, note_id, visibility, is_assistant, is_supervisor}`: assistant → `NoteShareForbidden`; session must be assigned (`is_coach_assigned`) else `SessionNotAssigned`; load note by `(session_id, note_id)`; not found or (not supervisor and note.coach_id != coach_id) → `NoteNotFound`; persist; return updated note. `CoachingNotesRepository` Protocol gains `get_progress_note(session_id, note_id) -> ProgressNote | None`, `set_progress_note_visibility(session_id, note_id, visibility) -> ProgressNote | None`; `list_progress_notes(session_id, coach_id: str | None)` (None = all authors).
- `backend/v2/contexts/coaching/application/use_cases/skill_notes.py`: `CreateSkillNoteCommand.visibility` + `is_assistant`; same 403 rule; new `SetSkillNoteVisibility` with command `{student_id, note_id, visibility, coach_id, is_assistant, is_supervisor}` (student assignment is checked in the route via the existing `_require_assigned_to_student`, as create does today); repository port (`backend/v2/contexts/coaching/application/ports.py` `SkillNoteRepository`) gains `get(student_id, note_id)` and `set_visibility(student_id, note_id, visibility)`.
- `backend/v2/contexts/coaching/infrastructure/mongo_session_notes_repo.py`, `mongo_skill_note_repo.py`: persist `visibility`; `_to_domain` reads `doc.get("visibility") or "private"`; implement the new methods (`_find_one` / `_update_one` helpers of `TenantScopedRepository` — read `backend/v2/shared/tenancy/repository.py` for the exact names; never use raw `db[...]` in tenant-owned repos — `tests/test_no_raw_tenant_mongo_access.py` enforces it).
- `backend/v2/interfaces/coach/views.py`: `ProgressNoteView.visibility`; `CreateProgressNoteRequest.visibility: NoteVisibility = "private"`; `SetNoteVisibilityRequest { visibility }`.
- `backend/v2/interfaces/coach/notes_routes.py`: pass `visibility` + `is_assistant=is_assistant_only(claims)` on create; list passes `all_authors=is_coach_supervisor(claims)`; add `PATCH /sessions/{session_id}/progress-notes/{note_id}` (`require_coach_surface`).
- `backend/v2/interfaces/coach/skill_routes.py`: `CreateSkillNoteBody.visibility`; create passes `visibility` + `is_assistant`; add `PATCH /students/{student_id}/skill-notes/{note_id}` (`require_coach_surface`, `_require_assigned_to_student` first, 503 when the use case is not configured, same as create).
- `backend/v2/interfaces/coach/deps.py` + `backend/v2/composition/coach.py`: wire `set_progress_note_visibility` and `set_skill_note_visibility` (skill one optional like `create_skill_note`).
- `backend/v2/composition/parent.py` `list_progress_for_parent`: add `"visibility": "shared"` to the progress_notes query (both the count and the find). `session_feedback` untouched.
- `backend/v2/migrations/0167_coach_notes_visibility_private.py`: docstring in the style of 0165 (says it does NOT run on boot in prod, apply by hand via `fly ssh console` + `run_pending_migrations`, and that existing notes become private for parents); `update_many({"visibility": {"$exists": False}}, {"$set": {"visibility": "private"}})` on `progress_notes` and `coach_skill_notes`; log both modified counts; idempotent. Check `backend/v2/migrations/__init__.py` / `runner.py` for whether migrations are auto-discovered or listed — register if listed.
- Validators: migration 0133's `coach_skill_notes` schema lists properties without `additionalProperties: false`, so no widening is needed; `progress_notes` has no validator. State this in the migration docstring.

**Tests (add/extend):**
- `backend/v2/tests/interface/conftest.py` `FakeCoachingNotesRepo`: new methods; `list_progress_notes(session_id, None)` returns all authors.
- `backend/v2/tests/interface/test_assistant_coach.py`: assistant POST progress note with `visibility: "shared"` → 403 `Coaching.NoteShareForbidden`; assistant POST default → 201/200 with `visibility == "private"`; assistant PATCH → 403; lead coach PATCH own note → 200 shared then private; lead coach PATCH another coach's note → 404; supervisor (admin client fixture) PATCH any note → 200 and GET lists both authors' notes; a coach's GET lists only own.
- `backend/v2/tests/interface/test_coach_skill_routes.py`: POST skill note carries `visibility` into the command; PATCH route wired to the spy use case; assistant 403 on shared create (use the existing assistant fixture pattern in that file or `test_assistant_coach.py`).
- Unit tests for the use cases in `backend/v2/tests/unit/` (new file `test_note_visibility.py`): default private, assistant share refused, author/supervisor rules, unknown note 404, all-authors listing.
- Parent: `backend/v2/tests/interface/test_parent_activity_routes.py` is a fake-use-case test; the real filter lives in `composition/parent.py`. Add a test next to whatever already covers `list_progress_for_parent` with a Mongo fake (search `tests/composition` / `tests/integration` for `progress_notes`); if none exists, add a focused test using `mongomock_motor` or the repo's existing in-memory Mongo fixture (see `backend/v2/tests/conftest.py`) that seeds one shared, one private and one legacy (no field) note and asserts only the shared one is returned and `total` counts it alone.
- Migration test in `backend/v2/tests/migrations/` (follow the neighbours' pattern for 0165/0166): legacy docs get `private`, docs with a value are untouched, second run is a no-op.
- Structural: `test_coach_lead_gate_policy.py` must still pass (new routes are `surface`).

- [ ] Implement in the order listed; run ruff format/check, the full pytest suite (`-n auto`, must be green), import-linter (`cd backend && PYTHONPATH=.. .venv/bin/lint-imports --config pyproject.toml`), and mypy on every changed backend file (no new errors).
- [ ] Return: list of changed files, test counts, mypy delta, and the exact PATCH/POST shapes as implemented (so the orchestrator can diff against the contract).

---

### Task 2 (frontend agent): one-tap attendance with queued state, note share switch + notes list, 44px skill controls, e2e

**Files (modify/create):**
- `frontend/lib/api/coach.ts`: `NoteVisibility` type; `visibility` on `ProgressNote` and `SkillNote`; `createProgressNote` / `createSkillNote` bodies accept optional `visibility`; new `setProgressNoteVisibility(sessionId, noteId, visibility)` → PATCH and `setSkillNoteVisibility(studentId, noteId, visibility)` → PATCH (`lib/api/coach-paths.ts` gets `coachSkillNotePath(studentId, noteId)`).
- `frontend/lib/query/keys.ts`: `coach.progressNotes(sessionId)` → `["coach", "progress-notes", sessionId]`.
- **New** `frontend/lib/offline/attendance-queue.ts` (pure, unit-testable): `queueMark({occurrence_id, session_id, student_id, status, client_app_version})` — finds an existing `queued` mutation for the same occurrence+student and rewrites its payload/status (case #1) else `enqueue` a new one with a fresh ULID `mutation_id`, `endpoint: "/coach/attendance"`, payload = the `MarkAttendanceRequest` shape used by `markAttendance` (`marked_at_client` set at call time); `queuedMarksFor(occurrence_id)` → `Record<student_id, {status, mutation_id}>`. Add `frontend/lib/offline/attendance-queue.test.ts` (vitest, mock `./idb` or `./queue`).
- `frontend/app/(coach)/coach/sessions/[id]/page.tsx`:
  - Offline: replace the "reconnect to mark attendance" gate. Banner `data-testid="offline-indicator"`: "You're offline — marks are saved on this phone and sent when you reconnect." Present/Absent taps on a student **without a server mark** call `queueMark` and render a "Queued" chip `data-testid="mark-queued-<studentId>"` with the tapped button in its pressed style. Taps on a student **with a server mark** stay disabled offline, with `data-testid="offline-write-blocked"` hint text once under the banner: "Saved marks can be changed when you're back online." "Mark all present" offline queues each unmarked student. On mount and whenever `online` flips, hydrate queued marks via `queuedMarksFor`. Subscribe with `onSync` (`lib/offline/sync.ts`): on `succeeded` remove that student's queued chip and invalidate `queryKeys.coach.today(date)`; on `needs_review` show `mark-error-<studentId>` with the tray reason and a link to `/coach/needs-review`; on `finished` invalidate today. Queued count pill `data-testid="queued-count"` next to the heading when > 0. Note box and Billing stay online-only (offline policy).
  - Phone-first row: name + chips on the first line; a two-button Present/Absent group each `min-h-[44px]` and at least 44px wide (`flex-1` on phones), `aria-pressed` kept, same test ids; secondary actions (Skills link, Note, Billing) on a second line as 44px-tall text buttons. On `sm:` and up keep a single row. No horizontal overflow at 320px.
  - `mark-all-present` becomes `min-h-[44px]`.
  - Note box: replace "Save note — parent will see this" with a `Save note` button plus a labelled switch/checkbox `data-testid="note-share-<studentId>"` "Share with parent" (unchecked by default). For assistants (`useIsAssistantCoach()`), no switch; helper text `data-testid="note-private-hint"` "Notes you write stay private to coaches." Submit `{ student_id, body, visibility }`.
  - Notes list: `useQuery(queryKeys.coach.progressNotes(session.session_id), listProgressNotes)` once per page (enabled when online); inside an open note box show that student's notes (newest first, `data-testid="note-<noteId>"`), each with a chip `data-testid="note-visibility-<noteId>"` reading "Shared with parent" / "Private", and — for non-assistants — a 44px button `data-testid="note-share-toggle-<noteId>"` "Share" / "Make private" calling `setProgressNoteVisibility` and invalidating the list. Fix the existing invalidation that uses the route `id` instead of `session.session_id`.
- `frontend/components/coach/skill-notes-panel.tsx`: add the same share switch (`data-testid="skill-note-share"`) hidden for assistants, `visibility` on create, chip + toggle per note (`skill-note-visibility-<noteId>`, `skill-note-share-toggle-<noteId>`), using `setSkillNoteVisibility`; the "Add Note" button and toggles are ≥44px.
- `frontend/app/(coach)/coach/students/[studentId]/passport/page.tsx`: the status `<select>`, "Record Test", "Notes", "Save Test" and "Retry" controls go from `min-h-[36px]` to `min-h-touch`; give each card `data-testid="passport-skill-<skillId>"`.
- `frontend/components/pathway/skill-board.tsx`: mobile by-student cards get `data-testid="skill-card-<studentId>"`; skill chips inside stay 44px (already); no desktop change. `skill-cell-editor.tsx` is already 44px — leave it unless a11y review finds an issue.
- `frontend/e2e/fixtures/mock-api.ts`: progress-notes stub stores created notes (with `visibility`, default private) and serves GET + PATCH; skill-notes GET/POST/PATCH stubs if not present; `/coach/attendance` stub already exists — make sure it records calls (`mock.state` or similar) so a sync test can count them.
- `frontend/e2e/specs/coach-today.spec.ts`: un-skip and rewrite the offline test using `window.dispatchEvent(new Event("offline"))`: tap present on an unmarked student → `mark-queued-st1` visible, `queued-count` shows 1, no `/coach/attendance` call yet; dispatch `online` → the stub receives one POST, chip disappears, `mark-st1-present` has `aria-pressed=true`. Add: note box shows the share switch and saving with it checked sends `visibility: "shared"`; the notes list shows the chip and the toggle flips it via PATCH. Add a 44px assertion helper (boundingBox height ≥ 44) for `mark-st1-present`, `mark-st1-absent`, `mark-all-present` on the mobile project.
- `frontend/e2e/specs/coach-assistant.spec.ts`: assistant session detail shows `note-private-hint`, no `note-share-*` switch and no `note-share-toggle-*`; skill notes panel shows no `skill-note-share`.
- `frontend/e2e/specs/coach-day-hub-passport.spec.ts` or `skill-board.spec.ts`: on `chromium-mobile`, `passport-skill-*` controls and `skill-card-*` chips are ≥44px tall and the page has no horizontal overflow.
- Parent: `frontend/lib/api/parent.ts` `ParentProgressNote` unchanged (server filters). No parent UI change.

- [ ] Run `pnpm test:unit && pnpm test:node && pnpm lint && pnpm typecheck`, then `pnpm exec playwright test e2e/specs/coach-today.spec.ts e2e/specs/coach-assistant.spec.ts e2e/specs/coach-day-hub-passport.spec.ts e2e/specs/skill-board.spec.ts e2e/specs/coach-teaching-plan.spec.ts --project=chromium-desktop --project=chromium-mobile --reporter=line` (note: `chromium-desktop` has a `testMatch` restricted to admin specs — if it runs zero coach tests, say so; do not widen the config).
- [ ] Return: changed files, the exact request bodies the UI sends, test ids added, and the test run summaries.

---

### Task 3 (orchestrator): review → fix → verify → release note → PR

- Review (parallel): backend correctness + contract conformance; frontend a11y/mobile (44px, contrast, aria-pressed, focus order, no overflow at 320px); test coverage (both sides). Findings → fix agents → re-verify.
- Verify (parallel): backend suite + ruff + import-linter + mypy delta; frontend unit/node/lint/typecheck + Playwright coach specs; then the 10-device matrix (scratch config under the session scratchpad, pointing at this worktree's `playwright.config.ts` and `e2e/helpers`, projects iPhone SE / 12 / 14 / 14 Pro Max / 15 Pro on webkit, Pixel 5 / 7, Galaxy S9+ / S24 / Tab S4 on chromium) over: `/coach/sessions/<id>` (roster row: Present/Absent ≥44px, within viewport, no horizontal overflow, note box + share switch visible), `/coach/sessions/<id>/skills`, `/coach/sessions/<id>/progress` (cards, cell editor opens within viewport), `/coach/students/<id>/passport` (controls ≥44px). Screenshots kept in the scratchpad.
- Release note `docs/release-notes/2026-09-06-coach-phone-attendance-notes.md` (three exact sections; PR number after the PR exists): deploy note MUST say migration 0167 runs by hand in prod via `fly ssh console -a courtmastr-academy-api` + `run_pending_migrations`, and that existing notes become private for parents until re-shared.
- Commit, check machine load (`uptime` < 6, no other `pre-push-checks` running), push, open PR against `main`, wait for CI Gate + Release Notes Gate, ask the owner once before merging, then run the migration in prod after Deploy Backend and report modified counts for both collections.
