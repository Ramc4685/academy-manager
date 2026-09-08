# fix-reconcile-withdraw-paths

PR: #684

## What changed
There is now ONE withdraw path (issue #670). `WithdrawEnrollment`
(`backend/v2/contexts/enrollment/application/use_cases/admin_writes.py`) is the only
writer of the lifecycle transition and drives every side effect in a fixed order: a
compare-and-set status flip first, then the billing decision (only for the caller that
won the CAS), seat release, future roster-row drop, `billing_sync` (future invoices voided, autopay off), the lifecycle
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
decrement `reserved_seats` twice; `mark_withdrawn` is removed.

Money comes after the CAS, and the billing decision can never refuse a withdrawal
(review of the first cut of this PR):

* A family billed only through the v2 invoice/AR ledger has no legacy `payments` doc
  carrying a `calculation_snapshot_id`. That used to raise `Billing.PaymentNotFound`
  (404) and abort the whole withdrawal — the seat stayed held, `billing_sync` never
  ran and autopay kept charging. It is now a zero-credit outcome: `credit_none` with
  `no_credit_reason="no_paid_tuition_snapshot"` on the lifecycle event. The preview
  route still 404s, because there the question really is unanswerable.
* `RecordWithdrawalDecision` runs only for the CAS winner, so losing a race to a
  concurrent cancel can no longer leave an APPROVED `EARLY_WITHDRAWAL_CREDIT` on a
  parent's balance with no withdrawal event behind it.
* The legacy Stripe subscription cancel is attempted on every `credit` run (including
  the already-credited retry) and a Stripe failure is recorded as
  `subscription: "cancel_failed"` in the event metadata instead of raising. A failed
  cancel can no longer both block the withdrawal and be skipped forever by the
  credit's idempotency guard.
* If the decision port itself fails, the withdrawal still completes and the event says
  `withdrawal_decision_failed` — a half-withdrawn row no retry can finish is worse
  than a visible money follow-up.

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
(vitest alongside). `withdrawErrorMessage` keys its 404 copy off the error CODE, not
the status: only the bare owner-gate 404 (FastAPI `detail: "Not found"`, no code) says
"ask the academy owner"; `Billing.PaymentNotFound` explains there is no paid tuition to
credit from, and any other coded 404 surfaces the server's own message. New Playwright
spec `e2e/specs/admin-enrollment-withdraw.spec.ts`.

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
Watch the `withdrawn` lifecycle events after deploy for `credit_none`
(`no_paid_tuition_snapshot`), `subscription: "cancel_failed"` and
`withdrawal_decision_failed`: each means the withdrawal itself succeeded but the money
side needs a human — a refund/adjustment, a subscription cancelled by hand in Stripe,
or a re-run of the credit.
Rollback is reverting the PR; no data written by the new path needs undoing.
