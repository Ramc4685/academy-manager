# payment-risk-draft-invoices

PR: #576

## What changed
The payment-risk campaign audience resolver
(`resolve_payment_risk_audience` in
`backend/v2/contexts/communications/infrastructure/mongo_audience_resolver.py`)
included invoices in `draft` status, but draft invoices are not payable
anywhere in the app — parent checkout and the digest dues view restrict
to `{open, partially_paid}` because a pay link for a draft invoice 404s.
An admin drafting next term's invoices ahead of time with past-due
due_dates caused payment-risk campaigns to email those parents a
dunning-style message about balances they cannot pay. `"draft"` is now
dropped from the invoice status filter so the campaign audience matches
the set of actually-payable invoices, with a regression test proving a
parent whose only overdue invoice is a draft is excluded while a parent
with an overdue open invoice is still resolved.

## Deploy notes
No migration, no config, no new indexes. Takes effect on the next
payment-risk campaign send after deploy.

## Risk / rollback
Strictly narrows the campaign audience — no parent who legitimately owes
money is removed, since draft invoices carry no payable balance. If a
workflow somehow relied on dunning draft-invoice parents, revert the
merge to restore the old filter; no data is touched either way.
