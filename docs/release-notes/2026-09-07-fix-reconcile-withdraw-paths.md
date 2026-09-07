# fix-reconcile-withdraw-paths

PR: #TBD

## What changed
There is now ONE withdraw path (issue #670). `WithdrawEnrollment`
(`backend/v2/contexts/enrollment/application/use_cases/admin_writes.py`) is the only
writer of the lifecycle transition and drives every side effect in a fixed order: the
billing decision first, then a compare-and-set status flip, seat release, future
roster-row drop, `billing_sync` (future invoices voided, autopay off), the lifecycle
event, the `EnrollmentCancelled` outbox event for waitlist promotion, and the staff
notice. The early-withdrawal credit is a billing-side step — the new
`RecordWithdrawalDecision` use case in
`contexts/billing/application/use_cases/withdrawal_credit.py`, reached through the new
`EnrollmentWithdrawalDecisionPort` and the adapter in `composition/lifecycle_billing.py`
(`compose_withdrawal_decision`). It reuses the ledger logic the standalone
`ApproveWithdrawalCredit` had (one `EARLY_WITHDRAWAL_CREDIT` per enrollment via
`find_active_for_enrollment`, legacy Stripe subscription cancelled at period end) and
the lifecycle event now records what actually happened: `credit_approved`,
`credit_already_approved`, `credit_none`, or the honest `refund_manual` /
`adjustment_manual` — `decision_not_recorded` is gone.

Guards both ways: withdrawing a row that is already `withdrawn` or `cancelled` raises
`EnrollmentNotWithdrawable` (409, `Enrollment.NotWithdrawable`) instead of silently
returning. The status flip is `MongoEnrollmentWriter.mark_withdrawn_if_open`, a CAS
whose pre-image is the seat token, so a retry or two concurrent submits can never
decrement `reserved_seats` twice; `mark_withdrawn` is removed. The decision runs
before any write, so a refused credit (no paid tuition snapshot, 404) leaves the row
untouched and the owner can pick another outcome.

Routes: `POST /api/v2/admin/enrollments/{id}/withdrawal-credit/approve` is REMOVED.
`POST /api/v2/admin/enrollments/{id}/withdraw` stays admin-reachable and gates the
`credit` outcome per action (`ensure_owner_for_withdrawal_credit` in
`interfaces/admin/owner_gate.py`, 404 exactly like `require_owner`); refund and
adjustment stay open to admins. The preview route is unchanged.
`composition/admin.py` drops from 4751 to 4711 lines.

Frontend: the session-detail Withdraw dialog
(`frontend/app/(admin)/admin/sessions/[id]/dialogs.tsx`) sends every outcome through
`withdrawEnrollment`; `approveWithdrawalCredit` is removed from `lib/api/admin.ts`. The
"Account credit" option is disabled for admins without the owner scope with a hint, the
409 message is shown verbatim, and the pure rules live in `lib/admin/withdrawal.ts`
(vitest alongside). New Playwright spec `e2e/specs/admin-enrollment-withdraw.spec.ts`.

## Deploy notes
No migration, no new env vars, no data backfill. The removed route has no callers
other than the dialog shipped in the same deploy. No new collection fields: the
lifecycle event's `billing_result` stays a string and `metadata` a string map, both
already allowed by migration 0133's validator. Legacy enrollment rows with no `status`
field are treated as open (active) by the CAS, matching every other reader.

## Risk / rollback
Behaviour change for owners: approving a credit now also releases the seat, offers it
to the waitlist, voids future invoices and disables autopay — the side effects the old
approve route skipped (the bug). A second withdraw of the same row is now a 409 where
it used to be a silent 204; the roster hides the button once a row is withdrawn, so
only stale tabs and API callers see it. `cancel_subscription_immediately` (never sent
by the UI) is dropped; the legacy subscription is always cancelled at period end.
Rollback is reverting the PR; no data written by the new path needs undoing.
