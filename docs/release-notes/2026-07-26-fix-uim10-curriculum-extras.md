# fix-uim10-curriculum-extras

PR: #TBD

## What changed
Surfaces two curriculum-authoring routes that only existed as "dark" admin
APIs (UIM10):

- **External references** — an "+ Reference" control on each skill in
  `/admin/pathway/[programId]` opens a form (source, source title, module,
  lesson range, reference title, optional page hint, internal note) that
  POSTs to `/admin/skills/{skill_id}/external-refs`. Existing references
  returned by the pathway payload (`SkillWithCriteria.external_refs`) now
  render under each skill.
- **Seed badminton pathway** — a "Seed content" card on `/admin/pathway`
  (shown when the academy has no programs yet) confirms, then POSTs to
  `/admin/programs/_/seed-badminton`. The route ignores its `{program_id}`
  path segment server-side (it seeds/returns the one academy-wide badminton
  program idempotently), so any placeholder segment works.

Place-in-level was already fully wired (dialog on
`/admin/students/[studentId]/progress`, `placeStudentInLevel` →
`POST /admin/students/{id}/pathway-placement`) and lesson-card seeding was
already wired (`LessonCardsPanel` on the program detail page) — both
verified against `progress_routes.py` / `pathway_routes.py` and left
untouched.

## Deploy notes
none — frontend-only, no migrations, no env vars.

## Risk / rollback
Purely additive UI calling existing, already-tested backend routes. Seeding
is idempotent (checked server-side by sport + existing active program), and
the client shows a `window.confirm` before calling it. Rollback = revert
this PR.
