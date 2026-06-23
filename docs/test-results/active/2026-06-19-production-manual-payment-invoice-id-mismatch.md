# production manual payment invoice id mismatch

## Current State

Status: active

## Problem

Admin student Billing tab Record payment sends a legacy pay_* id to the ledger invoice manual-payment endpoint, causing production invoice-not-found errors.

## Changed Files

- None recorded yet.

## Log

- 2026-06-19T23:04:00 main/NA: Task ledger created.
- 2026-06-19T23:04:09 main/working: Diagnosed screenshot failure: student Billing tab selects legacy payment_id pay_* from payment_history and posts it to /api/v2/admin/billing/invoices/{invoice_id}/record-payment; backend record manual payment only supports ledger invoice ids, so ledger lookup returns invoice not found.
## Verification

- No verification recorded yet.
- 2026-06-19T23:04:17: Code inspection: frontend student BillingWorkflowPanel selects row.payment_id/current.payment_id and calls recordAdminInvoicePayment(invoiceId); backend route /api/v2/admin/billing/invoices/{invoice_id}/record-payment calls RecordManualPayment against ledger invoices only. get_billing_invoice_detail has a legacy payments fallback, but record-payment does not. No prod writes or runtime tests run.
## Reusable Lessons

- None recorded yet.
