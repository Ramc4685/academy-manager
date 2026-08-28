# fix-recovered-monthly-invoice-shape

PR: #494

## What changed
Orphan-key recovery in the monthly invoice generator wrote a structurally
different invoice than the normal generation path for the same
enrollment/period: the tuition line and `subtotal_cents` were recorded net of
applied account credit, `discount_cents` was 0, and no discount line was
written. Since PR #487 the amount owed (`total_cents` / `balance_due_cents`)
was correct on both paths, so this was a reporting defect, not an overcharge —
but `invoice_lines`-based reporting (the tuition-discount summary) and any
subtotal-vs-total reconciliation disagreed depending on which path produced the
invoice.

- `_monthly_invoice_is_complete` now takes the gross charge and the applied
  credit explicitly and checks `total == gross - discount - credit`. The credit
  is not recoverable from the invoice document, and without it the predicate
  also rejected correctly generated *credited* invoices in the normal path's
  pre-check — which is why a second generation run over a credited period
  reported `created` instead of `skipped_existing`.
- Recovery passes the gross charge, the discount, and the discount policy
  through to the ledger write, so it emits the gross tuition line, the discount
  line, and `discount_cents` exactly as the normal path does. It keeps pricing
  the charge from the net amount, as PR #487 established.
- New `_reconcile_monthly_invoice_header` restates a pre-existing header when
  recovery repairs a partial invoice. `create_invoice` never updates an
  existing header, and when it back-fills a missing line it recomputes totals
  from the lines alone — which knows nothing about applied credit and subtracts
  a discount twice. It touches only the header, only when the stored lines
  already match the expected gross and discount, and preserves allocations.
- Recovery now bails before writing anything when the existing monthly tuition
  line disagrees with the gross charge, marking the key `repair_failed` with
  that reason. The line write is `$setOnInsert`, so such a line can never be
  corrected in place; back-filling a discount line around it would leave the
  header matching neither shape.

## Deploy notes
No migration and no configuration change. Invoices already generated are not
rewritten by this deploy; the new shape applies to invoices generated or
recovered from here on.

**Verify after deploy:** on the next monthly generation pass, check the
`monthly_invoices_generated` log line for a rise in `failed_repair`. Any
invoice recovered under the old net-of-credit shape now reports
`repair_failed` on the key (with `repair_error` naming the mismatched tuition
line) instead of being re-recovered. That is deliberate — those invoices are
left untouched for review rather than partially rewritten. Query
`billing_invoice_keys` for `status: "repair_failed"` to list them; the amount
owed on each is already correct, so no parent-facing action is needed.

## Risk / rollback
Low, and confined to the monthly generator. The change is shape-only: no path
alters what a parent owes, and `total_cents` / `balance_due_cents` are computed
exactly as before. Recovery is more conservative than it was — it refuses to
write over a mismatched line instead of layering a second shape on top of it.

Roll back by reverting this PR. Invoices written with the new shape remain
valid under the old code for reporting, but the reverted completeness predicate
will not recognise a credited invoice as complete, so a subsequent generation
run over an already-generated credited period reports `created` rather than
`skipped_existing` (the deterministic invoice id and `billing_invoice_keys`
guard still prevent a duplicate invoice or a second charge).
