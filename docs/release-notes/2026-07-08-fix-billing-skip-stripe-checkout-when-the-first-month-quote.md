# fix-billing-skip-stripe-checkout-when-the-first-month-quote

PR: #292

## What changed
Fixes the production "Internal Server Error" on **Continue to checkout** (blno-academy, 2026-07-07): a parent enrolling when no billable classes remain this month gets a legitimate **$0.00** quote ("billed for 0 of 0 classes"), and the checkout path sent that $0 to Stripe, which rejects zero-amount payment-mode Checkout Sessions. The unhandled failure surfaced as a raw 500.

## Deploy notes
No migration detected in the diff. Confirm no manual env var or manual step is needed before merge.

## Risk / rollback
_Auto-generated stub — author: fill in what breaks if this is wrong and how
to roll back before merge._ Revert the merge commit if this regresses.
