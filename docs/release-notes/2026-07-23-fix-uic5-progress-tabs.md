# fix-uic5-progress-tabs

PR: #TBD

## What changed
Student and session skill progress now appear as tabs on their detail
screens instead of being one hop away behind separate buttons/links.

- **Admin:** `/admin/students/[studentId]` gains a 6th tab-link "Progress"
  that navigates to the existing `/admin/students/[studentId]/progress`
  route (canonical URL unchanged, no redirect). Both pages now render a
  shared `components/admin/StudentDetailTabs.tsx` header — the 5 existing
  state-tabs (Overview/Training/Sessions/Billing/Family & Compliance) plus
  the Progress link-tab. `?return_to=`/`?return_label=` deep links into the
  progress page (from `admin/sessions/[id]` and `admin/pathway/progress`)
  are unaffected.
- **Coach:** `/coach/sessions/[id]` gains an Attendance · Skills · Progress
  tab strip (`components/coach/SessionDetailTabs.tsx`), replacing the old
  "Skill updates" / "Skill Progress" buttons. The `skills` and `progress`
  subroutes render the same strip and preserve the `?date=` query param
  across tabs.

This is a pure presentational wiring change (audit item UIC5) — no routes
added, moved, or deleted, no data or API changes. The admin student detail
page shrinks slightly (inline tab-strip code replaced by the shared
component) rather than growing, consistent with the MT5 monolith-split
constraint.

## Deploy notes
None — frontend-only. No backend, migration, or env-var changes.

## Risk / rollback
Lowest-risk item in the audit set: no routes or data touched. Rollback =
revert the single PR.
