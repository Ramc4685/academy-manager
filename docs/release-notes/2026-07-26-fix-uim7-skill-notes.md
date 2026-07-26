# fix-uim7-skill-notes

PR: #TBD

## What changed
Adds a per-skill notes panel to the coach student passport page
(`/coach/students/[studentId]/passport`), closing out audit item UIM7. The
backend `POST/GET /coach/students/{student_id}/skill-notes` routes
(`backend/v2/interfaces/coach/skill_routes.py`) were already live but had no
UI — coaches had no way to leave qualitative notes on a specific skill (e.g.
"struggles with high serve toss") for handoffs or parent conversations.

- New `Notes` button on each skill card opens a `SkillNotesPanel` modal
  (`frontend/components/coach/skill-notes-panel.tsx`) scoped to that
  student+skill. Notes fetch on open only — not prefetched per skill card —
  newest-first, with a composer (1000-char client-side cap; the backend has
  no length limit) that appends a new note on save.
- New `listSkillNotes`/`createSkillNote` API functions and `SkillNote` type
  in `frontend/lib/api/coach.ts`, a `coachSkillNotesPath` URL builder in
  `frontend/lib/api/coach-paths.ts`, and a `queryKeys.coach.skillNotes`
  query key.
- Extended the passport route's entry in the QA inventory manifest
  (`docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`)
  with the new workflow/controls/states/risk/acceptance lines so
  `test_audit_inventory_manifest.py` stays accurate.

**Not a duplicate:** the passport page already had a free-text "Notes"
field, but it's a per-test-attempt annotation (`RecordTestBody.notes`,
optional context for a single pass/fail attempt) — a different feature from
this standalone, append-only, per-skill note thread. Both remain, serving
different purposes.

**Known limitation (by design, matches the plan):** the backend has no
edit/delete routes for skill notes — v1 is append-only, and the panel has
no delete affordance to match. A 503 from the backend (use case not
composed) renders an "unavailable" state instead of crashing.

## Deploy notes
None. No new backend routes, no migration, no env vars — purely a frontend
consumer of already-deployed endpoints.

## Risk / rollback
Low. Additive UI only; no existing component, route, or query key was
changed. Rollback = revert this PR; the backend routes are untouched and
unaffected.
