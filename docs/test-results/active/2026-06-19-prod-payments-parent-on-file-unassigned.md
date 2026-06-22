# prod payments parent on file unassigned

## Current State

Status: active

## Problem

Production payments list shows Parent on file as Unassigned for pending invoices; determine root cause and safe remediation.

## Changed Files

- None recorded yet.

## Log

- 2026-06-19T15:43:14 main/NA: Task ledger created.
- 2026-06-19T15:44:23 main/working: Investigated admin payments Unassigned label. Frontend renders payment row student_name fallback; backend enriches invoice rows by joining invoices.student_id to students.student_id. Safe prod remediation is invoice student_id backfill from matching student_billing_enrollments, not payment/Stripe mutation.
- 2026-06-19T16:24:21 main/working: Read-only prod Mongo audit via Fly app env: DB academy_manager, real academy_id acad_blno_badminton, 41 pending 2026-06 legacy payments, zero missing student_id, and all 41 join to students. Root cause is backend admin list projection using legacy payment rows without student enrichment, not prod DB corruption.
- 2026-06-20T01:11:07 main/working: Expanding task: fix Admin Payments invoice actions to use internal invoice_id, add month/session filters, and investigate production paid Stripe row still showing Unassigned after legacy archive.
## Verification

- No verification recorded yet.
- 2026-06-19T15:44:23: Code inspection only: frontend/app/(admin)/admin/payments/page.tsx renders p.student_name || Unassigned; backend/v2/composition/admin.py list_payments_recent enriches invoice rows from invoices.student_id -> students.full_name. No production DB writes run.
- 2026-06-19T16:24:21: Regression red/green: new test initially failed with student_name None; after patch cd backend && source .venv/bin/activate && pytest selected admin payments composition tests -q passed (4). ruff check and ruff format --check passed for touched backend files.
- 2026-06-19T16:24:21: Prod read-only audit: academies=[acad_blno_badminton], invoices_2026_06_active=1 missing_student_id=0, pending_payments_2026_06=41 missing_student_id=0, payments student join health count=41 join_count=1. No prod writes run.
- 2026-06-20T01:15:46: Production duplicate Jayaparthiban Stripe row cleanup: backed up exact duplicate docs to /tmp/blno-duplicate-stripe-row-cleanup-20260620-011437.json.gz, then deleted only inv-from-01KVGHQVV26FSH26M1HEY77SW6, line-from-01KVGHQVV26FSH26M1HEY77SW6, lp-from-01KVGHQVV26FSH26M1HEY77SW6, and alloc-from-01KVGHQVV26FSH26M1HEY77SW6. Post-check: all bad counts=0; correct ledger invoice ledger-in_1ThFmlRMJDJBjoQzbRKLAP87 remains paid for stu_60a5a0e49bdb20b18a2d with stripe_invoice_id=in_1ThFmlRMJDJBjoQzbRKLAP87 and one allocation.
- 2026-06-20T01:16:31: Code verification for Admin Payments fixes: API now exposes invoice_id for payment rows and frontend uses invoice_id for invoice actions while displaying invoice_number; added month/session filters. Commands passed: pytest backend/v2/tests/interface/test_admin_billing.py::test_list_payments_exposes_invoice_id_for_invoice_actions backend/v2/tests/interface/test_admin_billing.py::test_list_payments_returns_recent -q (2 passed); ruff format --check and ruff check passed for touched backend files; frontend pnpm typecheck passed; frontend pnpm lint passed with only pre-existing unrelated warnings outside touched Payments page.
- 2026-06-20T01:17:51: Second Jayaparthiban duplicate cleanup after user screenshot: backed up exact migrated duplicate docs to /tmp/blno-jayaparthiban-migrated-duplicate-cleanup-20260620-011705.json.gz, then deleted inv-from-01KTVHV1TCZNYBF0G1DS2W090B, line-from-01KTVHV1TCZNYBF0G1DS2W090B, lp-from-01KTVHV1TCZNYBF0G1DS2W090B, and alloc-from-01KTVHV1TCZNYBF0G1DS2W090B. Post-check: active_june_invoice_count_for_student=1; remaining invoice is ledger-in_1ThFmlRMJDJBjoQzbRKLAP87, paid, total=6000, balance=0, stripe_invoice_id=in_1ThFmlRMJDJBjoQzbRKLAP87; both duplicate generated invoice/payment sets have count 0.
## Reusable Lessons

- None recorded yet.
