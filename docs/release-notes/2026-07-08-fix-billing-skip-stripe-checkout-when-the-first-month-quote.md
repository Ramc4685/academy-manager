# fix-billing-skip-stripe-checkout-when-the-first-month-quote

PR: #292

## What changed
Fixes the production "Internal Server Error" on **Continue to checkout** (blno-academy, 2026-07-07): a parent enrolling when no billable classes remain this month gets a legitimate **$0.00** quote ("billed for 0 of 0 classes"), and the checkout path sent that $0 to Stripe, which rejects zero-amount payment-mode Checkout Sessions. The unhandled failure surfaced as a raw 500.

Also closes a billing-correctness gap flagged in review: the $0 checkout branch skipped Stripe and sent the application to admin review, but nothing recorded which billing period had been quoted at $0. Enrollment documents never carry `billing_start_at`/`created_at` (confirmed by tracing `admin_registration_review.py` and `confirm_enrollment.py` — neither writer stamps these fields), so `generate_monthly_payments`'s proration logic has no way to know this enrollment started mid-cycle; without a fix, the very next monthly billing run would charge the **full** monthly tuition for the period that was supposed to be free. `Application.zero_quote_period` now carries the quoted period forward, and admin approval stamps it onto `enrollment.skip_periods` (the same mechanism already used for parent-approved billing pauses), so the monthly generator correctly skips that period.

## Deploy notes
No migration detected in the diff — `zero_quote_period` and `skip_periods` are additive optional fields that default to absent on existing documents. No manual env var or step needed before merge.

## Risk / rollback
**What breaks if this is wrong:** a parent whose checkout quote is $0 (no billable classes left this month) has their application routed to admin review without payment, same as before. If `zero_quote_period` failed to persist or `skip_periods` failed to stamp, the parent isn't charged anything extra at approval time — the risk is a **delayed correctness regression**: the next `generate_monthly_payments` run for that period would bill the enrollment the full monthly tuition instead of $0, i.e. re-introducing the pre-existing gap this PR closes. It would not cause a 500 or block checkout.

**Rollback:** revert the merge commit. `zero_quote_period` and the `skip_periods` entries it wrote are additive Mongo fields — a revert stops new writes but leaves any already-stamped `skip_periods` values in place, which is harmless (they only ever prevent a charge, never cause one). No backfill or cleanup required.
