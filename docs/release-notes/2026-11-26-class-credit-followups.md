# Class-credit follow-ups: skipped months and seat counts

PR: TBD

## What changed
Calling off a class no longer credits a family from the class fee for a month the monthly run never invoices: an open billing deferral or a skipped month. A month with a real invoice, or paid at checkout, is still credited. Crediting a missed class now reports the one-time seats it removed and the make-ups and trials it reopened, and the month-dates page shows them.

## Deploy notes
None.

## Risk / rollback
Credit decisions only; no stored data or migrations change. Families skipped show a new reason (`deferral_not_invoiced`, `skip_period_not_invoiced`). Revert this change if a family who paid is skipped.
