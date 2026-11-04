# manual-payment-pays-older-invoices

PR: #1093

## What changed
Recording a manual payment (cash, check, Zelle, bank transfer) that is more than the chosen invoice's balance now pays the family's other open invoices before anything becomes account credit. The chosen invoice is paid first. The extra then settles the family's other open or partially paid invoices, oldest due date first, and only what is still left is minted as an approved account credit. Before this, the whole excess became credit. Account credit is only spent when the next monthly invoice is generated, so a family that paid several months at once (for example $300 Zelle against one $60 month) kept four older months showing unpaid.

The record-payment dialogs (Payments buckets and the student billing tab) now say where the extra goes when the amount is over the balance. The API response and the `manual_payment_recorded` audit entry gain `previous_balance_applied_cents`; the response also returns `overpayment_credit_cents`. Each step of the spread is keyed on the payment id, so a retried submission replays instead of paying an invoice twice.

## Deploy notes
None. No migrations or settings. Credit that earlier manual overpayments already created is left as it is; applying it to open invoices is a separate fix.

## Risk / rollback
The change touches money allocation, and it only runs when the amount is over the chosen invoice's balance. Exact and partial payments behave as before. Invoices stamped with another of the parent's alias ids are not included in the spread; that money becomes credit, as it did before this change. Revert the PR to go back to "excess becomes credit"; payments recorded meanwhile stay correctly allocated.
