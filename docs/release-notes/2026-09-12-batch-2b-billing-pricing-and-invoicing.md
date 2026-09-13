# Batch 2b: billing, pricing and invoicing fixes

PR: #771

## What changed

- Fixes #730 — the 4-classes-per-meeting cap now applies to continuing (already-enrolled) families too, not just new signups.
- Fixes #729 — moving an enrollment now credits the from-session consumed-first, matching how a withdrawal already credits a session.
- Fixes #724 — "Bill this month" now prices through the same monthly-generator resolver the automated run uses, instead of a separate ad hoc price calculation.
- Fixes #739 — every hand-billed invoice (Create invoice, Bill this month, the enrollment-move top-up) now dates itself from the same `invoice_due_days` Billing rule the monthly generator uses, so one month never carries two due dates for a family and month close no longer reports `charge_on_varies`.
- Fixes #727 — hand-created invoices are audited (an `invoice_hand_billed`-style entry now appears on the family timeline / invoice audit drawer) and de-duplicated: the idempotency key is derived from the parent and the client's request id instead of a ULID minted inside the same call, so a double-click or retried request can no longer leave two blank drafts.
- Fixes #726 — a staff admin (not just the owner) can now void the unsent draft invoice they created via Create invoice / Bill this month, instead of that draft sitting there blocking or duplicating the month's generator run until the owner logs in.
- Fixes #738 — SendInvoice (the admin hand-send path) is now autopay-aware: for an autopay-active family it sends the pre-charge notice instead of minting a Stripe "Pay invoice" checkout link and email, avoiding a double-charge risk when the dunning worker later charges the card on the due date.
- Fixes #736 — an unsent draft invoice now owes nothing and counts as nothing billed everywhere (family page, billing summaries), matching what the #722 family page already displayed.
- Fixes #737 — month close's "invoice with no enrollment" anomaly check no longer flags a hand-created invoice that was deliberately created with no class attached (#722's "Not tied to a class"); it now only flags a genuine dangling `enrollment_id` reference.
- Fixes #725 — same one-predicate defect as #737, verified from the other angle; added a regression test pinning that an untied hand-created invoice stays off the month-close anomaly report.
- Also included: fixed two tests for #739 (`test_manual_invoice_due_date.py`, `test_admin_billing.py`) that compared against local-time `date.today()` instead of the UTC date the production code actually uses, which flaked by one day in the evening (US Central) — pinned to `datetime.now(UTC).date()`.

## Deploy notes

None. No new migrations, no schema changes, no new environment variables or manual steps required.

## Risk / rollback

Low risk — all changes are scoped to billing/invoicing use cases and interface routes, covered by unit/contract/interface tests, and the full backend + frontend gates pass. Rollback is a revert of this PR; no data backfill is required since no invoice documents' shape changed (only which invoices are created, audited, priced, dated, voided, sent, and reported).
