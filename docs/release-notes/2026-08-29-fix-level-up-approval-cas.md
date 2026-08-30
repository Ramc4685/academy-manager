# level-up-approval-cas

PR: #501

## What changed
Level-up approval is now a compare-and-set: `update_status` filters on the
expected prior state and reports whether it matched. The use case runs the
approval's (idempotent) side effects first and performs that CAS **last**, so
the status transition is the commit point: a failure part-way through leaves
the recommendation `RECOMMENDED` and re-approvable, and the loser of a race
re-applies the same writes and is then refused. A replayed approval —
an admin double-click, two admins racing, or a retried POST — now aborts with
409 instead of issuing a duplicate certificate, inserting a duplicate active
level row, and re-seeding every skill at that level to NOT_STARTED (which
destroyed any PASSED/TEST_READY progress earned since the first approval). The
approve side effects are idempotent so a mid-way failure no longer strands the
recommendation, and the admin UI handles the 409 and refreshes instead of
leaving a stale row with an enabled Approve button.

## Deploy notes
None. No migration.

## Risk / rollback
Certificate idempotency is still a non-atomic read-then-write with no unique
index behind it, so two genuinely simultaneous approvals that both miss the
read could still insert duplicates; a unique index on `skill_certificates` is
tracked as a follow-up. Separately, `get_active_for_student` counts APPROVED as
active, so a student cannot be re-recommended after an approval — pre-existing
behaviour, not introduced here, but more visible now that approvals cannot be
replayed. Roll back by reverting the merge commit; the CAS adds no persisted
state.
