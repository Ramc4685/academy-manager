# billing-disputes-list-card-account

PR: TBD

## What changed
The admin Payments list (All invoices) now shows a Stripe dispute on the row it hit: amount, reason, and Stripe status while open, or the outcome once it closes (#980; the Billing Health disputes card and blocked-payments reason already shipped in #1178). The parent portal's autopay card and the autopay date-change notice preview no longer show a saved card that lives on a different Stripe account from the one autopay charges, matching the other card-on-file displays (#981).

## Deploy notes
None. No migration and no env change. The dispute fields are read from what the dispute webhook already stamps on payment rows.

## Risk / rollback
Display only: no charge, ledger or webhook path changed. If it is wrong, a disputed row shows no note, or a parent sees "no card" for a card autopay would refuse anyway. If the route lookup fails, the card shows as it did before this change. Roll back by reverting the PR.
