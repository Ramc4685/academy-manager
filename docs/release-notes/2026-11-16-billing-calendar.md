# billing-calendar

PR: TBD

## What changed
Billing can now charge autopay on a different day from the invoice due date. An academy setting, `autopay_charge_offset_days`, counts days from the invoice date. A dated `schedule_change` switches the due window, the charge day and the reminder days from a given date. BLNO is scheduled to switch on 2027-01-01: invoices and autopay on the 1st, manual payers due on the 5th, reminders on the due date and 3 and 7 days after. December runs on today's schedule.

When an invoice has a charge day, these all read it, and otherwise fall back to the due date: the dunning ladder, collections buckets, month close, the "next charge" line on the admin family page, and the autopay emails. The billing rules page shows the pending change as a read-only row.

There is an API-only preview of the autopay date-change email (`GET /api/v2/admin/billing/ach-notice/preview`), with the list of autopay families it is meant for. There is no UI for it yet. It returns 404 when no charge-day change is set up. Nothing sends the email: there is no job, no outbox event and no send path, and a test asserts the sender is never called.

Smaller fixes from the same review:
- A reopened invoice moves both its due date and its charge date to reopen day + 5, so autopay cannot retry before then.
- Payment reminders skip exactly the invoices the late-fee pass treats as an active retry: a ladder active or processing, unless it is parked waiting on the parent to add a card. The two share one filter. A family parked on "no saved payment method" still gets its reminders. This applies from deploy.
- A blocked bank account is now matched by Stripe customer too. For `mandate.updated` the customer comes from looking up the payment method.
- Returned money now goes through one ledger rule that never lowers or doubles a payment's refunded total:
  - Charge refunds merge Stripe's cumulative refunded amount into the charge's share of the total.
  - Disputes and payment-intent returns add once each. They are keyed by dispute or payment intent in a new `return_sources` field on the payment.
  - So a dispute followed by a plain refund is counted in full.
  - A partial bank return on a payment with no invoice allocations now marks the payment `partially_refunded` and writes a `payment_return_unreconciled` billing audit row on every pass. Before, it was silently dropped. The rest of the payment stays as the family's unapplied credit.
- The owner overdue-families counts now use the shared failed-attempt and park-reason rules. Ladders parked on `attempt_indeterminate` or `stripe_unavailable` now count as needing attention.
- Monthly generation pages ops (Sentry, error level) when it cannot read billing settings, as well as falling back to the defaults.

Defaults chosen by the lead, not the owner:
- `autopay_charge_offset_days` defaults to none (charge on the due date) and must not exceed `invoice_due_days`.
- The switch-over is a `schedule_change` applied when settings are read on or after its date. Base settings stay untouched until the next settings save.
- "Due on the 5th" is generation day + 4.
- Off-cycle invoices on autopay carry no charge date and charge on their due date.
- Late fees keep their current per-invoice behaviour and grace setting.
- The notice is meant for every family with active autopay. It always says "your usual monthly tuition", because no per-family projection of the next charge exists yet.

Known behaviours after the switch:
- A parent who turns on autopay between the 1st and the 5th is charged within the hour, with no notice before the charge.
- A failing-card ladder now starts on the 1st, so it ends earlier, and the late fee lands at due + 3 instead of later.
- Returned money that was already minted as overpayment credit stays spendable. The Sentry alert and the billing audit row are the backstop for reconciling it by hand.
- The scheduled change is promoted by UTC date. Near midnight in the academy's timezone, the switch can land a few hours early or late. This does not matter for a 1st-of-month run at 09:00 local.

## Deploy notes
- Two migrations, applied by the deploy pipeline's Migrate Production step:
  - `0230_autopay_charge_date_index` adds a partial index `academy_invoice_status_autopay_charge_date` on invoices.
  - `0231_blno_billing_calendar` seeds the 2027-01-01 `schedule_change` on BLNO's billing settings only. It is idempotent and leaves base fields alone.
- No new env var.
- Owner check after deploy: Settings, Billing rules shows the "Scheduled change" row, and BLNO's `billing_day` is 1.
- Before January, the owner reads the notice through the preview route and sends it through their own channel.

## Risk / rollback
Medium. The change touches invoice generation, the dunning ladder's due query, payment reminders and webhook reopen, return and refund handling. Each change has a real-Mongo contract test or a use-case test.

Before 2027-01-01 the only behaviour changes are:
- reminders now skip invoices still in an active retry
- the review fixes to returns and refunds

Invoices generated without an offset carry no charge date, and every reader falls back to the due date.

To roll back, revert the PR. Old code ignores `autopay_charge_date`, `schedule_change` and `return_sources`. If the revert lands after 2027-01-01, BLNO's stamped invoices would ladder on their due date (the 5th) instead of the 1st. To cancel the switch, drop `schedule_change` from BLNO's billing settings.
