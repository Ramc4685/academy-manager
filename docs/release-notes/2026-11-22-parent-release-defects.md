# parent-release-defects

PR: TBD

## What changed
Parent Children → Enrollments: the class name now wraps in full, and on phones one "Manage enrollment" menu replaces the inline Pause and Cancel buttons (desktop keeps them). Both the pause step and the cancel confirmation now name the child and the class. Requests → Absences and the Children session rows now show a date the child already has an absence notice for as "Already reported" and disabled, instead of letting the parent submit a duplicate the backend then refuses. Progress shows coach notes for the selected child only, under "Notes from coaches about <name>", so switching child switches both the skill journey and the notes (a sibling's note used to appear under the other child's skills).

## Deploy notes
None. No migration, env var or manual step. `GET /parent/children/{student_id}/schedule` gains an additive `absence_reported` boolean per entry, read from the child's existing absence notices; older cached PWA clients ignore it. `GET /parent/progress` accepts an optional `student_id` (limited to the parent's own children; any other id returns an empty list), which the Progress tab now sends. The page still filters by child as well, so a frontend that ships before the API stays correct. OpenAPI snapshot and generated types are updated.

## Risk / rollback
The backend duplicate-notice guard (pre-check plus the unique index) is unchanged and still refuses a concurrent double submit with a 409; a new real-Mongo test pins that. If the flag were wrong, a parent would see a date disabled or offered wrongly, but submission rules are server-side either way. The schedule read now also lists the child's absence notices (one tenant-scoped query per schedule load). Roll back by reverting the PR.
