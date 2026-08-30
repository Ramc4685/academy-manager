# reconcile-reserved-seats-backfill

PR: #561

## What changed
`#500` made parent self-cancel release the seat and emit
`EnrollmentCancelled`, but shipped no backfill — every session where a
parent self-cancelled before that fix still carries an over-counted
`reserved_seats`, silently rejecting new enrollments and never promoting
the waitlist (`#523`). This adds
`backend/scripts/reconcile_reserved_seats.py`: it recomputes each
session's expected count from enrollments with `status == "active"`,
prints the per-session delta report before applying (`--dry-run` stops
there), applies corrections via a CAS matched on the observed counter so
a concurrent production reserve/release is never clobbered, and then
runs the production `PromoteFromWaitlist` loop for every session with
free capacity and waiting entries — the same use case the
`EnrollmentCancelled` handler calls, with `WaitlistPromoted` going
through the real outbox. A new `parent_cancel`-reason contract test pins
the handler chain end-to-end, and the script has its own contract suite.

## Deploy notes
No code path changes — the script is operator-run. After deploy, run
`python -m backend.scripts.reconcile_reserved_seats --academy-id blno
--dry-run`, review the delta report, then re-run without `--dry-run`.
A lost CAS exits non-zero; re-run to pick up the remainder. The run is
idempotent: a second pass finds zero deltas and a drained/full waitlist.

## Risk / rollback
Promotions are real: promoted families get active enrollments and the
downstream `WaitlistPromoted` notification, so run the dry-run first and
sanity-check any large delta before applying. The CAS guard means a
concurrent live reserve/release makes the script skip that session
rather than clobber it. Nothing to roll back in the app itself —
reverting the merge only removes the script and tests; corrections
already applied to `reserved_seats` are by definition the true counts.
