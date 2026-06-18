# admin student billing account balance and add charge

## Current State

Status: active

## Problem

Admin student billing should show total outstanding balance, let admins select unpaid invoices, and add charges without invoice due_date validation failures.

## Changed Files

- None recorded yet.

## Log

- 2026-06-18T10:49:03 main/NA: Task ledger created.
- 2026-06-18T10:49:59 main/working: Root cause confirmed: ledger repository serializes due_date as an ISO string before Mongo writes, which violates the current invoices validator during add-line invoice updates. Starting regression test before code change.
## Verification

- No verification recorded yet.
- 2026-06-18T10:56:14: Focused backend regression passed: cd backend && source .venv/bin/activate && pytest v2/tests/contract/test_billing_ledger_storage.py::test_save_invoice_keeps_due_date_as_mongo_date v2/tests/contract/test_billing_ledger_storage.py::test_add_invoice_line_repairs_existing_string_due_date v2/tests/unit/test_add_invoice_line_use_case.py v2/tests/interface/test_admin_billing.py::test_add_invoice_line_returns_refreshed_invoice_totals -q => 13 passed, 1 existing StarletteDeprecationWarning.
- 2026-06-18T11:03:02: Frontend verification passed: cd frontend && pnpm typecheck passed; pnpm lint passed with only 5 pre-existing warnings outside touched files; pnpm build passed locally with same warnings; scripts/dev/saas_staging.sh rebuild-api passed; scripts/dev/saas_staging.sh rebuild-ui passed on retry and restarted frontend. Playwright browser smoke logged in to http://blno-academy.localhost:3000, opened Aadhya billing tab, saw account balance , 2 unpaid invoices, invoice list with 3 records, selected invoice actions, and 0 console/page errors; screenshot /tmp/admin-student-billing-account-balance.png.
## Reusable Lessons

- None recorded yet.
