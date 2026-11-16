# billing-autopay-safety

PR: #TBD

## What changed
Autopay no longer breaks or mis-charges when a family has no saved method, when Stripe is down, or when a bank debit fails or comes back later: each case now parks, retries or pauses the family's autopay, and tells the parent when they need to act. Every payment now sends a receipt, payment reminders catch up after a missed run, and the owner dashboard flags autopay stuck on Stripe setup or on our side. Card on file now counts only cards on the Stripe account the academy actually charges (#981).

## Deploy notes
- No migration and no new env var.
- Owner step: in the Stripe dashboard, subscribe BOTH webhook endpoints (platform and Connect) to `mandate.updated`, `payment_method.automatically_updated`, `refund.failed` and `refund.updated`. Until then the blocked-bank and failed-refund handling stays idle; nothing else depends on it.
- Behaviour change on disputes: a lost dispute (card or bank), or a dispute opened on a bank payment, now reverses the payment in the ledger, reopens the invoices it paid (autopay or pay link) with a due date 5 days out, and pauses autopay for the whole family. The parent is emailed only for bank-return disputes (insufficient funds, incorrect account details, bank cannot process). Before, a lost dispute moved no ledger money.
- Payment reminder offsets keep their stored values; the wider -7..60 range only changes what the settings form accepts.

## Risk / rollback
Medium: this touches the autopay charge path, the dunning ladder, webhook handling and parent emails. Each change has a real-Mongo contract or use-case test. A partial bank return is not reversed automatically: the family is paused and the return is flagged to ops for a manual fix. Bank checkout options are unverified against Stripe test mode. Roll back by reverting the PR. Rows written in the new shape (`settling_failure_code`, `last_failure_was_bank_debit`, `parked_since`, `blocked_payment_method_id`, `refund_failures`) are ignored by the old code.
