# fix-family-charge-audit

PR: #666

## What changed
"Charge card now" on the **Family billing** page now records who charged the card and
why. The audited charge flow that lived inside Billing Setup's closure in
`composition/admin.py` is extracted to
`contexts/billing/application/charge_admin_invoice.py` and reused, so an admin charge
from any surface is attributed in Stripe (`source="admin_manual"`, actor id) and written
to the trail as `admin_charge_initiated` with the admin's reason — the entry the family
timeline renders. Previously the family page charged through the bare autopay use case:
the attempt looked like an unattributed worker `autopay` run and the reason the dialog
demanded went nowhere. The billing-health and reports lists get the same attribution.
The charge endpoint accepts an optional `reason` and `request_id`; the client sends a
`request_id` so a retried submit is the same charge, not a second one.

## Deploy notes
None. No migration, no new env vars, no new endpoint. Billing Setup keeps its exact
idempotency-key prefix and audit id, so a charge in flight across the deploy still
resolves to the same request. `composition/admin.py` drops from 4783 to 4751 lines.

## Risk / rollback
The charge path is unchanged in behaviour apart from attribution and the audit entry:
the same saved-card, invoice-ownership, in-flight and confirmed-amount guards run, and
the confirmed-amount guard stays optional so the list surfaces that never confirmed an
amount are not newly blocked. Double-charge protection is unchanged (idempotency plan +
result keys, plus prior-attempt reconciliation). Rollback is reverting the PR.
