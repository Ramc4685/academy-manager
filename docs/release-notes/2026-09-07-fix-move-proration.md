# fix-move-proration

PR: #TBD

## What changed
Moving a student between sessions ("Move" on the session roster,
`POST /api/v2/admin/enrollments/{id}/transfer`) now re-prices the **current** billing
period. Before, `TransferEnrollment` called a `record_move_proration` port that had no
production implementation, so the month's invoice kept the old session's price and the
audit event recorded `billing_result: None` (issue #669).

Policy (owner assumption): for the period the move takes effect in, the family is
charged or credited the price difference for the classes still to come — each session's
monthly price scaled by its remaining/total billable occurrences from the effective date
(`domain/proration.py::quote_move_proration`, half-up on the final cent, the same
rounding as first-month proration). Later periods already re-price because the monthly
generator reads the enrollment's current session. Tuition discount policies are not
re-applied to the delta.

New billing use case `contexts/billing/application/use_cases/apply_enrollment_move.py`
(`ApplyEnrollmentMove`), decision table per effective period:
- no invoice yet for that period → nothing; the generator prices from the new session.
- dearer session, invoice open / draft / partially paid → a `move_proration` line is
  appended to it (via `domain.ledger.add_line`, so totals and balance are recomputed
  from real allocations).
- dearer session, invoice already **paid** → a separate open adjustment invoice
  (`source_type=MOVE_PRORATION`) is minted through the ledger's idempotent
  `create_invoice`; the paid invoice is never re-opened and lines are never corrected
  in place.
- cheaper session → an APPROVED `MOVE_PRORATION_CREDIT` on the family's credit ledger
  (same ledger as withdrawal credits; applied to the next invoice; expires in 365 days).
- same price → recorded only.

Idempotent per (tenant, enrollment, effective period, from-session, to-session) using
the billing `@idempotent` store, and additionally keyed underneath (line `source_id`,
`create_invoice` key, credit `source_id`) so a retry after a crash cannot double-apply.

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
raises that invoice's balance; an adjustment invoice is a normal open invoice with the
enrollment id set. In both cases the existing dunning ladder / autopay worker decides
whether and when to charge (`autopay_eligibility`); nothing in the move charges a card
immediately. A credit is picked up by the next invoice's credit application.

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
that month prices from the new session when generated. Repeating the identical move in
the same period (A→B, B→A, A→B) returns the first result rather than re-applying — by
design, stated in the issue. The Move dialog does not yet show the delta; it is in the
enrollment timeline via the lifecycle event. Rollback is reverting the PR: lines,
adjustment invoices and credits already written stay valid ledger entries and are not
undone.
