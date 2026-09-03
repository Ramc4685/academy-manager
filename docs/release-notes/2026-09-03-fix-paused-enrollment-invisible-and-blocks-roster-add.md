# fix-paused-enrollment-invisible-and-blocks-roster-add

PR: #TBD

## What changed
Prod, BLNO, 2026-09-03: "Add to roster" for Harshith Bhaskar (Thu 6:45 PM
Intermediate) failed with **"Harshith Bhaskar is already on this roster
(paused). Remove the existing enrollment first."** — but the roster showed no
such row, the student page said "No active session enrollments", he was not
on the session's Waitlist tab and there was no pause request. Nothing an admin
could see or click could clear the block.

Root cause (code, verified against `origin/main`): two readers disagreed about
what "on the roster" means.

- The roster read (`composition/admin.py`, `list_admin_enrollments_for_session`)
  filtered `status: "active"`, so paused rows were never returned. The roster
  panel's PAUSED chip and **Resume** button (`RosterPanel.tsx`) had never been
  reachable.
- PR #620's add-to-roster pre-check (`EditRosterAdd._BLOCKING_STATUSES`) blocked
  on `{"active", "paused"}`. Correct on its own — a second row next to a paused
  one would be a duplicate — but it turned an invisible row into a dead end.
- The student page's "Enrolled sessions" read (`mongo_student_repo.py`) was
  also active-only, so the paused enrollment was hidden there too.

Harshith's enrollment (`enr_71e884b5e4b41e31f50f`) was paused on 2026-07-04 by
an older pause path (lifecycle event has `billing_policy: null`, empty
metadata) that wrote no waitlist entry, so the "look on the Waitlist tab"
escape hatch did not exist for him either.

Fix:

- **Roster read lists active AND paused rows.** The PAUSED chip and Resume
  button now render. Seat counters are untouched: `enrolled_count` (capacity /
  open spots) still counts `active` only, because pause releases the seat.
  Frontend "In session" / `n/capacity` count active rows and show "N paused"
  as a detail.
- **Re-adding a paused student resumes the existing row.** `EditRosterAdd`
  now takes the `ResumeEnrollment` use case; when the pre-check finds a paused
  row it delegates to it (re-reserve seat, remove waiting entry, `resumed`
  lifecycle event, close billing deferral, resume autopay) and returns the
  same enrollment as `active`. No second row, no 409. If the resume use case
  is not wired the 409 remains, but now says "Use Resume on the roster
  instead."
- **Student page "Enrolled sessions" lists paused rows** with their status
  chip; the "N active" header counts active only.
- Structural policy test inverted: it previously *asserted* that the roster
  read excluded paused rows (no rationale in history); it now pins the
  corrected policy and that seat counts stay active-only.

Tests: `test_existing_paused_enrollment_is_resumed_in_place`,
`test_existing_paused_enrollment_is_refused_when_resume_is_unwired`,
`test_pause_and_resume_enrollment` (interface, now expects the paused row in
the listing), `test_admin_roster_policy.py` (3 structural checks).

## Deploy notes
- No migration. No data repair needed for Harshith: after deploy, either click
  **Resume** on his (now visible) roster row or run "Add to roster" again —
  both resume `enr_71e884b5e4b41e31f50f` and reserve one seat (session was
  14/16).
- Resume can raise `CapacityExceeded` (409) if the session is full; the dialog
  surfaces the message.
- The billing side of "paused" is unchanged by this PR and is still
  inconsistent (paused rows are invoiced by monthly generation unless a
  period-matched deferral exists; coach payroll counts active only). Tracked
  separately.

## Risk / rollback
- Low. Reads widen by one status; writes only change behaviour for the
  previously-failing paused case. Revert the PR to restore the old behaviour;
  no data is written that the old code cannot read.
