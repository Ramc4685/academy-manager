# late-fee-and-self-service-money

PR: #974

## What changed
The Billing rules page now says truthfully that late fees are charged automatically every hour. Turning a late fee on requires an acknowledgement and only affects invoices whose grace period ends on or after that day, so invoices already overdue are never back-charged. The late-fee pass now reads the fee only from `academies.fees` (the late-cancellation fallback is removed), reaches every overdue invoice rather than just the oldest 200, and uses the academy's timezone. On the Self-service page, only changed fields are saved. Changing the cancellation fee or notice now needs the owner, is bounded, and is recorded in the billing audit log. A cleared number box is an error instead of a 0.

## Deploy notes
None: no migration, env var or manual step. Before merging, run the read-only prod query to check BLNO's `academies.fees` shape and any existing `late_fee_applied` rows (see the PR description).

## Risk / rollback
If BLNO's late fee was stored only under `late_cancellation_fee_cents` or at the top level of the academy doc, the hourly pass stops charging it after deploy. Re-save the fee in Billing rules to fix that. No existing invoice amount changes. To roll back, revert the PR. The `late_fee_effective_from` field it writes is ignored by older code.
