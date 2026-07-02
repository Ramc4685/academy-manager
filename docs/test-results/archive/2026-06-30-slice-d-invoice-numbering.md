# slice-d-invoice-numbering

## Current State

Status: active

## Problem

Per-academy invoice numbering: minted invoice_number, atomic counter, unique index, gap policy

## Changed Files

- None recorded yet.

## Log

- 2026-06-30T23:50:44 main/NA: Task ledger created.
- 2026-06-30T23:50:52 claude/working: Implemented invoice_number field + format_invoice_number pure formatter in domain/ledger.py. Wired MongoBillingCounterRepository + MongoBillingSettingsRepository via new BillingCounterRepository/BillingSettingsRepository ports into AddInvoiceLine (Mode B on-the-fly invoice) and HandleWebhookEvent (_handle_session_type_invoice). Added migration 0138_invoice_numbering: unique sparse index (academy_id, invoice_number) + extended invoices validator (invoice_number optional, NOT backfilled onto historical invoices -- no reliable way to reconstruct what the sequence would have been). Fixed admin GET /billing/invoices list endpoint to surface invoice_number (was hardcoded to invoice_id); GET /billing/invoices/{id} detail already read it. Gap policy: gaps ARE allowed (voided/failed invoices consume a counter value that is never reused) -- documented in LedgerInvoice.invoice_number docstring, format_invoice_number docstring, and migration 0138 module docstring.
## Verification

- No verification recorded yet.
- 2026-06-30T23:50:59: pytest backend/v2/tests -q: 1775 passed, 1 known pre-existing unrelated failure (test_bootstrap_source_does_not_reference_default_academy_id). ruff check + ruff format --check backend/v2: clean. lint-imports --config backend/pyproject.toml: 4 kept, 0 broken. New tests: unit formatter (8), unit AddInvoiceLine use case (+4 new), application HandleWebhookEvent (+2 new), contract invoice numbering (4, incl. 250-parent concurrency + isolation + month-reset), contract migration smoke (4), interface admin-sees-invoice-number (3, incl. list-endpoint fallback fix).
## Reusable Lessons

- None recorded yet.
