# recancel-half-cancelled-backfill

PR: #600

## What changed
Adds one one-off repair script, `backend/scripts/recancel_half_cancelled_sessions.py`,
and its contract tests. No production code is touched — the diff is two new files.

Before PR #589 (`75262193`), cancelling an admin session flipped `sessions.status`
to `"cancelled"` but never touched the already-materialised `session_occurrences`,
which stayed `status: "scheduled"`. Every downstream reader keys off the
occurrence status — coach payroll (`mongo_payout_read_models`), the
expected-payroll/revenue report (`admin_reports_read_model`), the coach day view
(`mongo_occurrence_repo`) — so those sessions keep appearing on coach schedules
and accruing expected pay, while #589's listing filter hides them from the admin
sessions list so nobody can find them to re-cancel by hand. #589 fixed the
go-forward path only; this is the backfill for the sessions cancelled before it.

The script finds cancelled sessions that still own `scheduled` occurrences and,
only under an explicit `--apply`, feeds each post-cancel session aggregate into
the very same `maintain_session_occurrences` closure the DELETE route calls. It
never writes `session_occurrences` itself, so the `_is_clean_future_occurrence`
predicate is the same gate production uses and the write is a soft-cancel.

It drives the cascade in-process rather than re-issuing
`DELETE /api/v2/admin/sessions/{id}` as the issue sketched: that route runs
`CancelSession` first, which re-writes every active enrollment and appends a
fresh `EnrollmentCancelled` per enrollment with no already-cancelled
short-circuit — on an already-cancelled session, pure duplicate-event noise.

The report separates a FUTURE bucket (repairable) from a PAST bucket (counted
and listed, never repaired). The past bucket matters because the #593 population
is mostly old cancels whose whole stranded run is already behind `now`: a
future-only report would call those academies clean while
`effective_occurrence_status` reads a past `scheduled` occurrence as
`"completed"` and `MonthlyCoachOccurrenceReaderAdapter` still selects it for
payroll. Cancelled sessions with no `academy_id` cannot be tenant-scoped, so
they are reported as failures and make the run exit non-zero instead of being
logged away.

## Deploy notes
Nothing to deploy: no production code, no migration, no schema change, no new
environment configuration. The script is run by hand, and **must not be run
until PR #589 (`75262193`) is confirmed deployed to production** — verify the
running revision contains that commit first. Repairing history while the
go-forward fix is still missing is pointless churn.

Run the dry run first on every deploy target and read the per-academy table:

    backend/.venv/bin/python -m backend.scripts.recancel_half_cancelled_sessions

Apply is the only form that writes:

    backend/.venv/bin/python -m backend.scripts.recancel_half_cancelled_sessions --apply

Add `--academy-id <id>` to either to restrict to one academy. The script reads
`MONGO_URL` / `MONGO_DB` via `get_settings()` and `backend/.env`, exactly like
`reconcile_reserved_seats.py`, and has no environment guard — confirm the
environment points at the intended database before passing `--apply`.

After the apply run, check: `Occurrences soft-cancelled: N` is the repair count;
`Future scheduled occurrences ... (after): M` will NOT necessarily be zero, as
any remainder is occurrences the cascade deliberately retained (attended,
coach-assigned, or already on a payout line); a non-empty `Sessions skipped or
failed` exits 1 and needs investigating before a re-run. Re-run `--apply` once
more to confirm idempotence — it should report zero repaired, zero cancelled.

Two follow-ups the script reports but does NOT fix. Payroll already GENERATED
off these occurrences is not corrected — audit payout periods covering the
repaired dates and decide whether to recompute. And every `PAST scheduled` row
it lists is still headed for the next payroll generation as a class that was
cancelled and never taught; those need a manual decision, since soft-cancelling
the past would change #589's predicate.

## Risk / rollback
Low for the repo, and the write path is the conservative half. Nothing ships to
a running service, so there is no rollback to perform on this PR: reverting it
just removes the script. Dry run is the default, `--apply` is the only thing
that enables writes, `--dry-run` wins when both are passed, and a misspelled
flag exits through argparse before any database work.

The repair itself is a soft-cancel through the production composition closure —
nothing is deleted, and attendance history and earned coach pay cannot be
rewritten, because the same `_is_clean_future_occurrence` predicate rejects
anything past, non-`scheduled`, coach-assigned, attended, or on a payout line.
A regression test proves the unsafe shortcut is caught: replacing the cascade
call with a blanket `update_many` cancels 5 occurrences instead of 2 and fails.
Each session is repaired inside `tenant_scope`, and a session un-cancelled
between the scan and the repair is reported and skipped rather than cascaded.

Residual: the finder's filter has only ever been exercised against
mongomock-motor, not a real MongoDB server, and the scan is a full `sessions`
pass with one `count_documents` per cancelled session against no assumed index —
so the dry run may be slow on a large database. It is read-only, so that is a
runtime cost, not a risk, and the dry run is the safe way to confirm the counts
look sane before applying. The script is also outside CI's mypy selection
(`-p backend.v2` does not cover `backend/scripts/`), the same gap that already
applies to the other scripts in that directory; its tests do run in CI.
