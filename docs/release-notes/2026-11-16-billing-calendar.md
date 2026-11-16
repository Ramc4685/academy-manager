# billing-calendar

PR: TBD

## What changed
Billing can now charge autopay on a different day from the invoice due date. An academy setting, `autopay_charge_offset_days`, counts days from the invoice date. A dated `schedule_change` switches the due window, the charge day and the reminder days from a given date. BLNO is scheduled to switch on 2027-01-01: invoices and autopay on the 1st, manual payers due on the 5th, reminders on the due date and 3 and 7 days after. December runs on today's schedule. The dunning ladder, collections buckets, month close, the parent's "next charge" line and the autopay emails all read the charge day when an invoice has one, and fall back to the due date otherwise. The billing rules page shows the pending change as a read-only row. Admins get a preview of the autopay date-change email and the list of autopay families it is meant for (`GET /api/v2/admin/billing/ach-notice/preview`). Nothing sends it: there is no job, no outbox event and no send path, and a test asserts the sender is never called.

Smaller fixes from the same review:
- A reopened invoice moves both its due date and its charge date to reopen day + 5, so autopay cannot retry before then.
- Payment reminders skip invoices whose dunning ladder is active or processing, including parked ladders.
- A blocked bank account is now matched by Stripe customer too. For `mandate.updated` the customer comes from looking up the payment method.
- A partial bank return on a payment with no invoice allocations now marks the payment `partially_refunded` and writes a `payment_return_unreconciled` billing audit row. Before, it was silently dropped. The returned amount comes off the payment, and the rest stays as the family's unapplied credit.
- The owner overdue-families counts now use the shared failed-attempt and park-reason rules. Ladders parked on `attempt_indeterminate` or `stripe_unavailable` now count as needing attention.

Defaults chosen by the lead, not the owner:
- `autopay_charge_offset_days` defaults to none (charge on the due date) and must not exceed `invoice_due_days`.
- The switch-over is a `schedule_change` applied when settings are read on or after its date. Base settings stay untouched until the next settings save.
- "Due on the 5th" is generation day + 4.
- Off-cycle invoices on autopay carry no charge date and charge on their due date.
- Late fees keep their current per-invoice behaviour and grace setting.
- The notice is meant for every family with active autopay. It always says "your usual monthly tuition", because no per-family projection of the next charge exists yet.
- Reminders skip invoices with an active or processing ladder.

## Deploy notes
- Two migrations, which must be applied by hand in prod (boot migrations are off):
  - `0230_autopay_charge_date_index` adds a partial index `academy_invoice_status_autopay_charge_date` on invoices.
  - `0231_blno_billing_calendar` seeds the 2027-01-01 `schedule_change` on BLNO's billing settings only. It is idempotent and leaves base fields alone.
- No new env var.
- Before January, the owner should read the notice through the preview route and send it through their own channel.
- Settings reads promote the change by UTC date. Near midnight in the academy's timezone, the switch can land a few hours early or late. This does not matter for a 1st-of-month run at 09:00 local.

## Risk / rollback
Medium. The change touches invoice generation, the dunning ladder's due query and webhook reopen and return handling. Each change has a real-Mongo contract test or a use-case test. Before 2027-01-01 nothing changes for any academy unless an admin sets an offset: invoices generated without an offset carry no charge date, and every reader falls back to the due date. To roll back, revert the PR. Old code ignores `autopay_charge_date` and `schedule_change`. If the revert lands after 2027-01-01, BLNO's stamped invoices would ladder on their due date (the 5th) instead of the 1st. To cancel the switch, drop `schedule_change` from BLNO's billing settings.
