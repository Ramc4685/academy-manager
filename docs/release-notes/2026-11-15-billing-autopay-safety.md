# billing-autopay-safety

PR: #TBD

## What changed
- Autopay, missing payment method: a family with autopay on but nothing saved no longer crashes the charge. The invoice stays due as normal (late fee applies). The parent gets one email with an "Add a payment method" pay-now button, and the family shows in the Payments awaiting / past-due buckets. Autopay charges automatically once a method is saved.
- Autopay, Stripe outages: a Stripe API or network error is no longer treated as a card decline. No retry step is used up and no parent email is sent. The ladder parks and retries, and the operator digest plus a new "Autopay stuck" card on the owner dashboard flag it.
- Autopay, bank (ACH) failures: insufficient funds retries at most twice, about 3 and then 7 days after the failure is reported. A closed, invalid or unauthorized account stops at once. When the retries run out, that enrollment's autopay is paused (not switched off) and the parent is asked to re-link a bank or pay by card. Card declines keep the existing ladder.
- Late bank returns and disputes: a bank payment returned after it cleared, a dispute opened on a bank payment, or a lost card dispute reopens the invoice and pauses autopay. Bank returns email the parent; disputes do not, because the parent raised them.
- Admin "Charge now" and Billing Setup charges by bank debit now settle the invoice when Stripe confirms them. Before, the money arrived in Stripe but the invoice stayed open.
- Stripe events: a bank account Stripe blocks, or a mandate that goes inactive, stops counting as a saved method. A refund Stripe fails to deliver is listed on Billing Health under "Refunds failed".
- Receipts: every payment now sends a receipt (autopay, invoice pay link, balance checkout). The wording names card or bank, and a bank receipt says debits take a few business days. All dunning and receipt emails carry a pay-now button.
- Payment reminders: a reminder missed by a scheduler outage still goes out within 3 days, and one run sends at most one email per invoice. The setting is renamed "Payment reminder days" and accepts -7 to 60, so 0 means the due date and negative numbers mean before it.
- Card on file (#981): Billing Setup, family billing, the family list and the Payments and month-close reads now count only a card on the Stripe account the academy actually charges. A legacy platform card on a connected academy no longer shows as "card on file".
- Bank checkout: setup and pay-and-save checkouts ask Stripe for the Financial Connections permission that later bank debits need.
- Billing Health: the payment-readiness card shows whether the connected account supports direct charges (#980).
- The scheduler's autopay jobs now log and total each academy's run separately, so one failing academy no longer hides the rest.

## Deploy notes
- No migration and no new env var.
- Owner step: in the Stripe dashboard, subscribe BOTH webhook endpoints (platform and Connect) to `mandate.updated`, `payment_method.automatically_updated`, `refund.failed` and `refund.updated`. Until then the blocked-bank and failed-refund handling stays idle; nothing else depends on it.
- Behaviour change on lost disputes: a lost dispute now reverses the payment in the ledger and reopens the invoice. Before, it moved no ledger money.
- Payment reminder offsets keep their stored values; the wider -7..60 range only changes what the settings form accepts.

## Risk / rollback
Medium: this touches the autopay charge path, the dunning ladder, webhook handling and parent emails. Each change has a real-Mongo contract or use-case test. The ACH ladder only applies to a debit the ladder was holding as "processing", so a card's `insufficient_funds` keeps the card ladder. Bank checkout options are unverified against Stripe test mode. Roll back by reverting the PR. Rows written in the new shape (`settling_failure_code`, `last_failure_was_bank_debit`, `blocked_payment_method_id`, `refund_failures`) are ignored by the old code.
