# stripe setup checkout hidden from payments

## Current State

Status: active

## Problem

Admin Payments shows zero-amount Stripe checkout projection rows as paid $0 unassigned payments instead of only showing real invoice/payment rows

## Changed Files

- None recorded yet.

## Log

- 2026-06-29T18:32:58 main/NA: Task ledger created.
- 2026-06-29T18:34:24 main/working: Root cause found: legacy payments admin adapter includes zero-amount Stripe checkout projection rows with no invoice/student/period/positive amount, rendering as paid $0 Unassigned rows.
- 2026-06-29T18:35:31 main/working: Added failing regression for zero-amount Stripe checkout projection, then filtered those rows from MongoPaymentRepository.list_recent_admin.
- 2026-06-29T18:45:12 main/working: Stripe CLI read-only verification found the exact app screenshot session cs_live_a1tdYDxzGSFw2xprmASxfKl2xpBLmCLSPyT1ykmBifLAp4Zlz5GgCSXbqu: mode=payment, status=complete, payment_status=paid, amount_total=0, no payment_intent, no invoice, metadata has academy_id/calculation_snapshot_id/parent_id/payment_id/session_id. Also confirmed the real $60 payment cs_live_a16KTw5yrtI0vS6G5WstJu3l0aJMMppz6U3Fq3NqfV82Vj5DsSA503jTEt has payment_intent pi_3TnklvRMJDJBjoQz1xYWOWoy and invoice_id metadata, so it should remain visible through its app invoice.
## Verification

- No verification recorded yet.
- 2026-06-29T18:36:09: RED: pytest v2/tests/contract/test_mongo_payment_repo.py::test_list_recent_admin_omits_zero_amount_checkout_projection_rows failed because the zero-amount checkout appeared in admin rows. GREEN: same behavior passed after filter; broader focused pytest v2/tests/contract/test_mongo_payment_repo.py plus admin list interface tests passed: 25 passed, 1 pre-existing Starlette warning.
- 2026-06-29T18:47:02: Formatting/lint passed: cd backend && source .venv/bin/activate && ruff format --check v2/contexts/billing/infrastructure/mongo_payment_repo.py v2/tests/contract/test_mongo_payment_repo.py && ruff check v2/contexts/billing/infrastructure/mongo_payment_repo.py v2/tests/contract/test_mongo_payment_repo.py. Final focused pytest after formatting passed: 25 passed, 1 pre-existing Starlette warning.
## Reusable Lessons

- None recorded yet.
