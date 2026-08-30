# ach-settlement-overpayment-credit

PR: #572

## What changed
An ACH autopay debit settles days after submission. If an admin recorded a
manual payment that zeroed the invoice during that window, the late
`payment_intent.succeeded` recorded the ledger payment and then failed
allocation with `no payable invoice balance or payment amount`, burning its 24
retries into webhook quarantine (post-#491). The parent had paid twice, the
settled money sat as a permanently unapplied ledger payment, and no credit was
ever minted — cleanup was manual forensics.

`allocate_payment_to_invoice` now raises only when the payment itself has no
usable money. Allocating against a zero-balance invoice produces a zero-amount
allocation plus an APPROVED OVERPAYMENT account credit for the full usable
amount, leaving the invoice's balance and status untouched. The multi-invoice
Checkout settlement helper had the mirror-image gap — it skipped zero-balance
invoices and silently dropped any unallocatable remainder — and now allocates
the remainder once more under a dedicated `:overpayment` idempotency key so the
same credit path fires. The autopay webhook handler logs a warning whenever a
settlement converts to credit so admins can see it happened.

Three hardening follow-ups from review are included: (1) reversing an
allocation (ACH return R01/R10) now also voids the OVERPAYMENT credit minted
from it — without this, a returned debit would leave the parent a spendable
credit for clawed-back money; any portion already spent before the return is
logged for manual recovery. (2) The Checkout overflow arm is best-effort: if
the payment's unapplied balance was already consumed under a different
idempotency-key prefix it logs and leaves the remainder unapplied (pre-fix
behaviour) instead of quarantining the webhook event. (3) `RecordManualPayment`
still rejects an invoice with no balance due up front, so the new domain
leniency cannot silently convert an admin's cash entry into account credit.

## Deploy notes
No migration and no new collections — credits are written to the existing
`account_credit_ledger` with `source_type=OVERPAYMENT`, exactly like the
partial-overpayment path that already existed. Events already sitting in
quarantine for this failure are not replayed automatically; re-delivering them
(or the PaymentIntent reconciler) will now succeed and mint the credit.

## Risk / rollback
The behaviour change is confined to allocations that previously raised: money
Stripe has already settled (or an admin has already recorded) now becomes an
account credit instead of an error. Every allocation caller represents funds
actually received, so no caller relied on the raise to reject money. Redelivery
is idempotent — the credit is keyed to the allocation and the overflow
allocation to a fixed idempotency key, so double delivery cannot double-credit.
Roll back by reverting the merge commit; credits minted while live are ordinary
approved account credits and remain valid after a revert.
