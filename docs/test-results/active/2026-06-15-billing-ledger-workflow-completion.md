# billing ledger workflow completion

## Current State

Status: active

## Problem

Complete missing Billing-tab workflow, frontend API clients, backend route hardening, and verification for billing ledger convergence

## Changed Files

- None recorded yet.

## Log

- 2026-06-15T13:18:02 main/NA: Task ledger created.
- 2026-06-15T13:20:01 main/working: Starting bounded backend hardening for admin billing invoice routes: remove-line repo method, void reason body, focused tests.
- 2026-06-15T13:20:07 main/working: Adding typed frontend API wrappers/types for admin billing products and ledger invoice workflow; no UI/backend edits planned.
- 2026-06-15T13:22:04 main/working: Frontend API/type slice complete: updated frontend/lib/api/admin.ts and frontend/lib/api/v2/students.ts only; backend invoice detail still does not return line ids/type/quantity/unit amount so those detail fields remain optional.
- 2026-06-15T13:24:39 main/working: Hardened admin billing invoice routes: remove-line now uses a billing use case and repository delete method, void requires request body reason, add-line response includes refreshed invoice totals/status.
- 2026-06-15T13:33:41 main/working: Implemented admin student Billing-tab ledger workflow UI: create invoice, add/remove line, send, record manual payment, autopay trigger, void, invoice totals, allocations/credits; widened invoice detail DTO for editable line fields.
- 2026-06-15T13:37:56 main/working: Patched admin invoice-detail composition to return ledger invoice id, totals, delivery metadata, and editable line fields so the Billing tab can render/remove real ledger lines.
- 2026-06-15T13:43:02 main/working: Addressed code-review findings: create-invoice validates route/body student, parent, and enrollment scope; add-line rejects negative unit amounts; void rejects invoices with recorded payments; UI disables unsafe void and fixes stale line-delete spinner.
## Verification

- No verification recorded yet.
- 2026-06-15T13:22:04: frontend: pnpm typecheck passed after adding admin billing product and ledger invoice API wrappers/types.
- 2026-06-15T13:24:39: backend: pytest v2/tests/interface/test_admin_billing.py v2/tests/unit/test_add_invoice_line_use_case.py v2/tests/unit/test_billing_ledger.py v2/tests/unit/test_ledger_domain.py v2/tests/contract/test_billing_ledger_storage.py v2/tests/contract/test_billing_idempotency.py -q passed (74 tests). ruff format --check and ruff check passed for touched backend files.
- 2026-06-15T13:33:41: frontend: pnpm typecheck passed; pnpm lint passed with 5 pre-existing warnings outside touched Billing-tab files. backend: focused billing/interface/unit/contract set passed (81 tests); ruff format --check and ruff check passed for touched backend files.
- 2026-06-15T13:37:56: backend after composition patch: ruff format --check and ruff check passed for touched admin billing/composition files; focused billing/interface/unit/contract set passed again (81 tests).
## Reusable Lessons

- None recorded yet.
 yet.
