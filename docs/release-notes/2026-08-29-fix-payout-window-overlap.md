# payout-window-overlap

PR: #563

## What changed
Fixes issue `#504` (audit-2026-08). Percent-of-revenue coach payouts had
two related defects. First, the expected-revenue basis was prorated
across only the occurrences inside the *requested* query window, so
generating a payout period for a short custom window inflated the
per-occurrence basis (1 of 4 July occurrences in a week-long window got
the full month's revenue — a ~4x overpay). The read model now prorates
by the session's payable, non-cancelled occurrence count in each
occurrence's own billing (calendar) month, counted from
`session_occurrences` independently of the window. Second, generation
idempotency was only the exact `(coach, period_start, period_end)`
tuple, so an overlapping custom window minted a second draft carrying
the same occurrence lines and both could be approved and paid.
`GeneratePayoutPeriod` now rejects any window that intersects an
existing period for the coach (`OverlappingPayoutPeriodError`, surfaced
as 409 `Finance.PayoutPeriodOverlap` on
`POST /admin/payout-periods/generate`), via a new tenant-scoped
`find_overlapping` repository method. Bulk month payroll counts an
overlap-blocked coach as skipped instead of aborting.

## Deploy notes
No migration and no new index required — `find_overlapping` uses the
existing `(academy_id, coach_id)` + window fields on `payout_periods`.
Existing draft periods generated from short custom windows keep their
inflated persisted lines; recompute those drafts after deploy to pick up
the corrected basis. Approved/paid history is untouched.

## Risk / rollback
The 409 is new behavior: admins who previously generated overlapping
custom windows will now be blocked until the conflicting period is
handled — that is the point of the fix, but it may surprise workflows
that relied on overlapping drafts. Exact re-requests of an existing
window still return the existing period unchanged. Rollback is a plain
revert; no data is rewritten by this change.
