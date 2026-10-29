# void-manual-payment

PR: #TBD

## What changed
An owner can now void a cash, check, Zelle, Venmo or bank-transfer payment that was recorded by mistake, from the family record's Billing tab (Fix something → Void a manual payment). Each payment is listed with its amount, date, the invoices it paid and any account credit it created. Voiding asks for a reason and lands in the timeline. It voids the payment, not an invoice: the invoices stay, their balances reopen, and the credit the payment created is cancelled. Stripe payments are never listed; they are refunded instead. The void is refused, on screen and by the API, once any of that credit has already paid another invoice, because voiding would cancel the credit without taking back what it paid. Before, that case went through and only logged a warning. The family billing response gains a `manual_payments` list. The Payments → All invoices menu still offers no Void for manual payments, because its rows are invoices, not payments.

## Deploy notes
None. No migrations or settings. After deploy, BLNO's mistaken $300 Zelle for the Senthilkumar family can be voided from the family page and then recorded again so #1093 spreads it across the open months.

## Risk / rollback
Low. The void route itself is unchanged apart from the new spent-credit refusal, which runs before any write. The new read is one extra query set per family page, and it degrades to a warning if it fails. Revert the PR to remove the list and the refusal.
