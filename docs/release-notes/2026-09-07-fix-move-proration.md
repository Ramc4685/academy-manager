# fix-move-proration

PR: #678

## What changed
Moving a student between sessions ("Move" on the session roster,
`POST /api/v2/admin/enrollments/{id}/transfer`) now re-prices the **current** billing
period. Before, `TransferEnrollment` called a `record_move_proration` port that had no
production implementation, so the month's invoice kept the old session's price and the
audit event recorded `billing_result: None` (issue #669).

Policy (owner assumption): for the period the move takes effect in, the family is
charged or credited the price difference for the classes still to come — each session's
monthly price **net of the enrollment's active recurring tuition discount**, scaled by
its remaining/total billable occurrences from the effective date
(`domain/proration.py::quote_move_proration`, half-up on the final cent, the same
rounding as first-month proration). Pricing net of the discount is what the monthly
generator does (`_resolve_charge_for_enrollment` -> `monthly_discount_cents`), so a
sibling-discount family's move delta now matches the discounted invoice it lands on;
`ApplyEnrollmentMove` reads the policy through a new `MoveDiscountReader` port
(`MongoTuitionDiscountRepository`) and both sides share
`domain/tuition_discount.py::policy_applies_to_period`. Later periods already re-price
because the monthly generator reads the enrollment's current session.

The "classes still to come" boundary is **local midnight of the admin-chosen effective
date in the session's timezone**, not midnight UTC of that date (which is 19:00 the
previous evening in America/Chicago and counted an evening class the student had
already attended as remaining). The route passes `effective_date` through
`TransferEnrollmentCommand` -> `EnrollmentMoveBillingSync.apply_move` ->
`ApplyEnrollmentMoveCommand.effective_date`; the same date also names the billing
period directly rather than being inferred from the instant.

If either side's schedule cannot be expanded for the period (session doc missing, or no
billable occurrence in the month) the move is **refused for billing** with outcome
`schedule_unavailable` and nothing is written. A zero share is indistinguishable from
"no classes left", and the generator bills the full month either way, so a delta
computed against it would double-charge (or silently under-bill) the family. The roster
move itself still happens; the lifecycle event records the refusal.

New billing use case `contexts/billing/application/use_cases/apply_enrollment_move.py`
(`ApplyEnrollmentMove`), decision table per effective period:
- no invoice yet for that period → nothing; the generator prices from the new session.
- dearer session, invoice open / draft / partially paid → a `move_proration` line is
  appended to it (via `domain.ledger.add_line`, so totals and balance are recomputed
  from real allocations).
- **cheaper session, invoice still open / draft and nothing allocated to it yet → a
  NEGATIVE `move_proration` line reduces that invoice**, so autopay charges the
  corrected amount instead of the old higher one. Previously this always minted a
  credit and the worker charged the pre-move total.
- cheaper session, invoice already paid or partly paid → an APPROVED
  `MOVE_PRORATION_CREDIT` on the family's credit ledger (same ledger as withdrawal
  credits; applied to the next invoice; expires in 365 days). Reducing an invoice money
  has landed on could strand an overpayment, so the credit ledger stays the instrument
  there.
- dearer session, invoice already **paid** → a separate open adjustment invoice
  (`source_type=MOVE_PRORATION`) is minted through the ledger's idempotent
  `create_invoice`; the paid invoice is never re-opened and lines are never corrected
  in place. `MongoMonthlyBillingGenerator._find_existing_invoice_for_enrollment_period`
  now excludes `source_type=MOVE_PRORATION`: the adjustment shares
  `(enrollment_id, period)` with the month's tuition invoice and is newer, so a
  newest-first lookup used to hand it back and let a recovery pass mark the period
  complete with the tuition invoice still missing.
- same price → recorded only.

A half-applied debit self-heals: `_debit_existing` writes the line and the
version-guarded header in two round trips, and the retry branch now re-derives the
header from the lines that actually exist and saves it when it disagrees, instead of
returning the found line and leaving the invoice permanently under-stating the charge.
An adjustment invoice's due date falls back to 7 days when `billing_settings`
has `invoice_due_days` explicitly null (it used to become "due today", which the
dunning ladder chased immediately).

Idempotent per (tenant, enrollment, effective period, from-session, to-session,
**move_seq**) using the billing `@idempotent` store, and additionally keyed underneath
(line `source_id`, `create_invoice` key, credit `source_id`) so a retry after a crash
cannot double-apply. `move_seq` is how many `moved` lifecycle events the enrollment
already had when the transfer was issued: without it a second genuine A→B move in one
period (A→B, B→A, A→B) reused the first move's key and could never post money, leaving
the family net-zero in the dearer session. Retries of ONE transfer carry the same seq
and still collapse.

`TransferEnrollment` now refuses a non-transferable enrollment: only `active` and
`paused` rows can move, matching the docstring. A cancelled/withdrawn row would consume
a seat on the target session, release the old seat a second time, and get billed a
proration for classes it will not attend. New domain error
`Enrollment.NotTransferable` (HTTP 409) raised before any side effect.

A repeat transfer to the session the enrollment is *already* in is still a no-op — with
one exception: if the last `moved` event recorded `billing_sync_failed` /
`billing_sync_unwired`, it re-drives `ApplyEnrollmentMove` with the seq and effective
date stored on that event and writes a follow-up `moved` event carrying
`retry_of_event_id`. `_sync_move_billing` never raises, so before this there was no way
at all for an admin to recover a move whose billing sync had blipped.

Wiring: new port `EnrollmentMoveBillingSync.apply_move` in
`contexts/enrollment/application/ports.py`, adapted in
`composition/lifecycle_billing.py::compose_enrollment_move_billing_sync` and passed as
`billing_sync=` to `TransferEnrollment` from `composition/admin.py` (two lines; admin.py
is at 4753 of 4800). The transfer never fails because of billing — a billing error is
logged and the `moved` lifecycle event records `billing_sync_failed`. The event now
carries `billing_policy=move_proration_current_period`, `billing_result`
(`debit:<cents>` / `credit:<cents>` / `no_change` / `no_invoice`) and metadata with the
invoice / line / credit ids. The dead `record_move_proration` port and its test fakes
are deleted; `record_withdrawal_decision` stays (issue #670 owns it).

Autopay: the moved enrollment keeps its autopay status. A line added to an open invoice
raises (or lowers) that invoice's balance; an adjustment invoice is a normal open
invoice with the enrollment id set. In both cases the existing dunning ladder / autopay
worker decides whether and when to charge (`autopay_eligibility`); nothing in the move
charges a card immediately. A credit is picked up by the next invoice's credit
application.

**Known gap — an autopay family whose invoice grows after the pre-charge notice was
already sent.** `SendGeneratedInvoices` only ever selects from
`list_undelivered_invoices_for_period`, so an invoice whose "$X will be charged on
<date>" email has gone out is never re-noticed when a move raises its total. The worker
will charge the new, higher balance on the scheduled date and the family will have seen
only the smaller figure. This PR does **not** re-notice; it makes the case visible
instead: when a debit lands on an invoice whose `delivery_status` is already `sent`,
`ApplyEnrollmentMoveResult.notice_stale` is true and the `moved` lifecycle event's
metadata carries `notice_stale=true`. Admins moving a student up a tier between the
notice and the charge date should tell the family, or wait for the next period. A
negative delta is safe in the other direction — the family is charged less than they
were quoted. Automatic re-noticing (reset delivery state, or an "invoice amended"
email) is deliberately left as a follow-up because it touches the delivery/dunning
model rather than the move path.

## Deploy notes
None. No migration: `account_credit_ledger`'s validator (0132) types `type` as a plain
string, so `MOVE_PRORATION_CREDIT` needs no schema change; invoice `source_type` is an
optional string. No new env vars, no new endpoint (the transfer route is unchanged in
path and shape, so the audit inventory manifest is untouched). Moves made before this
deploy were never re-priced; correct those by hand with an invoice line or manual
credit if the family was under/over-charged.

## Risk / rollback
The delta is computed only for the period the move takes effect in and only when that
period already has an invoice; a move dated into a future month does nothing today and
that month prices from the new session when generated. Note the roster move applies
immediately regardless of `effective_date`, so a future-dated move leaves the current
period priced at the old session — unchanged by this PR and tracked separately.
Discounted families now get a smaller delta than before this change; that is the fix,
but it does change the numbers a re-run would produce. `schedule_unavailable` is a new
terminal outcome: sessions with no expandable schedule (no `start_date`/`end_date`/
`days_of_week` and no `start_at`/`end_at`) are no longer billed on a move at all —
repair the session doc and re-issue the transfer. The Move dialog does not yet show the
delta; it is in the enrollment timeline via the lifecycle event. Rollback is reverting
the PR: lines, adjustment invoices and credits already written stay valid ledger entries
and are not undone.
