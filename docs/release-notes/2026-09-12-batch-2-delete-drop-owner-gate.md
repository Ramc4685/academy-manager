# Delete/drop owner gate

PR: #0

## What changed

- Fixes #741 — `DELETE /admin/enrollments/{id}` was gated only by
  `require_persona("admin")` and never read
  `EnrollmentDeparturePolicy.delete_enrollment_requires_owner`, so any admin
  could hard-delete an enrollment regardless of the owner's toggle in
  Settings. The route now checks the policy per action (404 for a non-owner
  when the toggle requires one, same shape as
  `ensure_owner_for_withdrawal_credit`), via a new
  `ensure_owner_for_enrollment_delete` gate. A tenant whose departure policy
  was never composed keeps today's owner-only default.
- Fixes #741 — the frontend gate mirrored a hardcoded `OWNER_ONLY_ACTIONS`
  set, so turning the toggle off in Settings still showed admins a disabled
  Delete button. `RosterPanel` now passes the policy's
  `delete_enrollment_requires_owner` value through to
  `departure-actions.logic.ts`, which decides per action instead of from a
  fixed set.

## Deploy notes

No migration. No new environment variables or manual steps. The gate reads
the existing `EnrollmentDeparturePolicy` document; academies without one
composed keep the current owner-only behavior on both backend and frontend.

## Risk / rollback

Risk is narrow: an admin at an academy that has explicitly turned the
toggle off could previously delete enrollments and now cannot until an
owner does it (or vice versa — the frontend now correctly enables the
button when the toggle allows it). Both sides were covered by new tests
(`test_admin_departure_delete_owner_gate.py`,
`departure-actions.test.tsx`). Rollback is a revert of this PR's merge
commit; no data migration to undo.
