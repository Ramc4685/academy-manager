# batch-0-student-detail-held-visibility

PR: #757

## What changed

- Fixes #733 — a held (or mid-reclaim) child no longer vanishes from the admin student profile's Sessions panel. `MongoStudentRepository.get_admin_student` filtered enrollments to `active`/`paused` only, while `PAST_ENROLLMENT_STATUSES` covers just the terminal four, so a `held` or `reclaim_pending` row matched neither the current list nor the past list and disappeared from the profile entirely — taking #720's Return action with it. This mirrors #717's fix on the sibling class-roster read. The query now includes `held` and `reclaim_pending` alongside `active`/`paused`, and the profile's `StatusChip` renders both hold states as the same muted "ON HOLD" chip the class roster already uses, so a held child reads as on hold rather than withdrawn.

## Deploy notes

Backend query change plus a frontend chip-mapping change. No migrations, no new env vars, no schema change.

## Risk / rollback

Two enrollment statuses (`held`, `reclaim_pending`) are added to an existing `$in` filter and one chip mapping is extended; no existing status handling is removed or altered, and `past_enrollments` behavior for terminal statuses is unchanged. Covered by a new repository contract test and a new StatusChip unit test, both passing. Revert this PR if it regresses.
