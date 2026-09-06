# feat-payments-buckets

PR: #TBD

## What changed
The admin **Payments** page is now a bucket list for one billing period: Failed autopay,
Past due, Awaiting payment, Autopay scheduled, Paused, Paid, each row carrying its
default action (Send reminder, Record payment, Message, Skip this month, Resume). Buckets
come from a new read-only endpoint `GET /admin/payments/collections?period=YYYY-MM`,
whose "Autopay scheduled" rule calls the same eligibility predicates the dunning worker
uses (`contexts/billing/application/autopay_eligibility.py`, extracted from the worker
and the charge use case with existing tests kept green). The old invoice table lives on
an **All invoices** tab; its `Succeeded` status option and page-only `Month` filter were
removed, and the KPI strip that summed the visible page is replaced by tiles fed by the
read model. The dashboard's "Payments tracked" tile becomes Owed this month, Autopay
scheduled and Needs action. One money formatter (`lib/money.ts`) and one invoice status
vocabulary (draft / open / partially paid / paid / void) replace the page-local copies.

## Deploy notes
None. No migration, no new env vars, no data change. The worker refactor is a pure
extraction; `prepare_due_states` now projects two extra invoice fields.

## Risk / rollback
The new endpoint is read-only and every row action reuses an existing write endpoint.
Bucket placement can be wrong for odd data (a family with no `users` doc renders with a
null name; inconsistent rows fall into `unclassified`, visible with `?debug=1`) but the
page still renders. Rollback is reverting the PR; nothing persisted changes shape.
