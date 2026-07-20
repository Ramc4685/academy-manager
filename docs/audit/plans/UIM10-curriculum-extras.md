# UIM10 — Curriculum authoring extras
Status: TODO
Size: S · Depends on: none · Tracker: ../TRACKER.md

## User value
Curriculum admins can already view the pathway, but three authoring actions only exist as dark API routes: placing a student directly into a level (onboarding transfers/assessed students), attaching external references to skills (e.g. Shuttle Time lesson citations), and one-click seeding of the badminton program for a new academy. Surfacing them removes the last "call the API by hand" steps in curriculum setup.

## Backend status (verified)
All admin-persona (`require_persona("admin")`), 503 if curriculum service unwired, 404 wrong-persona per convention:
1. `POST /admin/students/{student_id}/place-in-level` → 201 — `backend/v2/interfaces/admin/progress_routes.py:111`. Body `PlaceStudentBody` (`progress_routes.py:55`): `{ program_id?: string, level_id: string, reason?: string }`. Returns the placement object (`model_dump`).
2. `POST /admin/skills/{skill_id}/external-refs` → 201 — `backend/v2/interfaces/admin/pathway_routes.py:290`. Body `AddExternalRefBody` (`pathway_routes.py:96`): `{ source, source_title, module_name, lesson_range, reference_title, page_hint?, internal_note }`. 404 `SkillNotFound` if skill id is bad.
3. `POST /admin/programs/{program_id}/seed-badminton` — `backend/v2/interfaces/admin/pathway_routes.py:318`. No body; returns `{ program_id, name }`. (Adjacent `POST /admin/seed-lesson-cards` at `pathway_routes.py:331` is also dark — include its button in the same seed card since it depends on the pathway being seeded; it returns created/updated/unchanged counts and 409 `PathwayNotSeededError`.)

## Frontend to build
On the existing `frontend/app/(admin)/admin/pathway` pages:
1. **Place in level** — action on the student row/detail within the pathway (or on admin student detail's progress area, whichever surface UIC5 settles on): dialog with program select (optional), level select (required), reason text; POST then invalidate the student-progress queries.
2. **External refs** — on the skill detail/editor: "Add reference" form (source, source title, module, lesson range, reference title, optional page hint, internal note) + list of existing refs if a read endpoint exists on the skill payload; 404 surfaced as inline error.
3. **Seed content** — a "Seed content" card on the program page, visible when the program is empty: "Seed badminton pathway" button (confirm dialog — it creates curriculum content) and "Seed lesson cards" button showing the returned counts as a success summary; disable lesson-card seeding with an explanatory hint until the pathway is seeded (handle the 409).

Data layer: `apiFetch` mutations, TanStack Query v5 `useMutation` + invalidation of pathway/program/student-progress keys; add any new keys to `frontend/lib/query/keys.ts`.

## Backend to build (if any)
None.

## Implementation steps
1. API client functions + request/response types for the four POSTs.
2. Place-in-level dialog + wiring on the chosen student surface.
3. External-ref form on skill editor.
4. Seed card with both buttons, confirm dialog, 409/422 error handling, success counts display.

## Files to change/create
- `frontend/lib/api/v2/pathway.ts` (or nearest existing curriculum client module) — mutations + types.
- `frontend/lib/query/keys.ts` — invalidation keys if missing.
- `frontend/app/(admin)/admin/pathway/**` pages/components — three UI additions above.
- Possibly `frontend/app/(admin)/admin/students/[studentId]/page.tsx` if place-in-level lands on student detail (coordinate with MT5 split).

## Verification
- Manual: place a student (with and without program_id/reason) → 201, progress view updates; add an external ref → appears on skill; seed badminton on a fresh program → program populated; seed lesson cards before pathway → 409 surfaced cleanly, after → counts shown.
- Wrong-persona 404 spot-check unchanged.
- Frontend type-check/lint; no backend tests affected.

## Risks / rollback
- Seed endpoints mutate curriculum content; confirm dialogs and empty-program gating keep them from accidental re-runs (lesson-card seeding is upsert-style — counts show unchanged rows, safe to re-run, but say so in the dialog).
- Purely additive UI; rollback = revert PR.

## PR checklist
- [ ] Release note line
- [ ] TRACKER.md row updated (Status, PR/Issue)
- [ ] This plan's Status → DONE (PR #NNN, date)
