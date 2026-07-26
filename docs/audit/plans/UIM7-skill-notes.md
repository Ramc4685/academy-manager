# UIM7 — Coach skill-notes UI
Status: DONE (PR #353, 2026-07-26)
Size: S · Depends on: none · Tracker: ../TRACKER.md

## User value
Coaches can record status/test attempts on skills but have nowhere to leave qualitative per-skill notes ("struggles with high serve toss"). The backend note store is live and dark; a notes panel on the student passport closes the loop for coach handoffs and parent conversations.

## Backend status (verified — routes, DTO fields)
`backend/v2/interfaces/coach/skill_routes.py`, persona `coach`, both guarded by `_require_assigned_to_student` (coach must be assigned to a session containing the student):
- `:506` `POST /coach/students/{student_id}/skill-notes` (201) — body `CreateSkillNoteBody {skill_id: str, body: str}` (skill_routes.py:70-72). Route resolves `session_id` from the assignment check and stamps `coach_id=claims.user_id`; returns the created note's `model_dump()`.
- `:529` `GET /coach/students/{student_id}/skill-notes?skill_id=` (skill_id REQUIRED query param) → `{notes: [...]}`.
- Note shape (from `backend/v2/contexts/coaching/application/use_cases/skill_notes.py` `CreateSkillNote`): `{note_id, student_id, skill_id, coach_id, session_id, body, created_at}`.
- 503 if `use_cases.create_skill_note` / `list_skill_notes` not composed — render as "notes unavailable" state.

## Frontend to build (pages/components/queries — concrete)
- Host: coach student passport page `frontend/app/(coach)/coach/students/[studentId]/passport/page.tsx` (exists). Add a notes affordance on each skill row/card: note-count badge or "Notes" button opening a panel/drawer scoped to that skill.
- Component `frontend/components/coach/skill-notes-panel.tsx`:
  - List: fetch on open (notes are per student+skill; don't prefetch for every skill), newest-first by `created_at`, show relative time + "you"/coach id.
  - Composer: textarea + Add button (disable empty), optimistic append or invalidate on success.
- API fns in `frontend/lib/api/coach.ts`: `listSkillNotes(studentId, skillId)`, `createSkillNote(studentId, {skill_id, body})` via `apiFetch`.
- Query key in `frontend/lib/query/keys.ts` under `queryKeys.coach`: `skillNotes: (studentId: string, skillId: string) => ["coach","skill-notes", studentId, skillId]`. Mutation invalidates that key. Note: coach.* keys persist to IndexedDB for offline (see keys.ts header comment) — read cache offline is fine; the create mutation should fail visibly offline (no queued writes in v1).
- Types mirror the note shape above (`SkillNote` interface).

## Backend to build (if any — route, use case, tests, manifest registration)
None. No new frontend route (panel on the existing passport page) → extend the passport page's entry in `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` (add notes modal/drawer to `controls`, plus workflow/acceptance/risk lines; keep `backend/v2/tests/unit/test_audit_inventory_manifest.py` invariants).

## Implementation steps (phased if L; each phase one PR)
1. Single PR: API fns + query key + panel component + passport wiring + manifest entry update.

## Files to change/create
- Create: `frontend/components/coach/skill-notes-panel.tsx`
- Modify: `frontend/app/(coach)/coach/students/[studentId]/passport/page.tsx`, `frontend/lib/api/coach.ts`, `frontend/lib/query/keys.ts`, `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`

## Verification
- `pnpm typecheck && pnpm lint`; manifest test green
- Manual/e2e: add note → appears in list and count badge increments; second coach on same session sees it; coach not assigned to the student gets the 403/404 state; 503 (service not composed) renders the unavailable state, not a crash; mobile viewport (coach surface is mobile-first) drawer usable

## Risks / rollback
- No edit/delete routes exist — v1 is append-only; state that in the UI (no delete affordance).
- `body` has no server-side length cap — cap client-side (e.g. 1000 chars) to keep documents sane.
- Rollback: remove the panel; routes untouched.

## PR checklist (release note · TRACKER.md · plan Status → DONE)
- [x] Release note
- [x] Update TRACKER.md row UIM7
- [x] Plan Status → DONE
