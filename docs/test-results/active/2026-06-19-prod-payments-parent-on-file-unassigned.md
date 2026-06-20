# prod payments parent on file unassigned

## Current State

Status: active

## Problem

Production payments list shows Parent on file as Unassigned for pending legacy payments; fix backend projection after read-only prod audit showed valid student links.

## Changed Files

- None recorded yet.

## Log

- 2026-06-19T19:19:04 main/NA: Task ledger created.
- 2026-06-19T19:19:17 main/working: Patched backend/v2/composition/admin.py list_payments_recent to use MongoPaymentRepository.list_recent_admin for legacy payments so student_name/parent_name enrichment is preserved; added regression test for legacy payment student_name.
- 2026-06-19T19:19:17 main/working: Read-only prod Mongo audit via Fly app env: DB academy_manager, real academy_id acad_blno_badminton, 41 pending 2026-06 legacy payments, zero missing student_id, and all 41 join to students. Root cause is backend admin list projection using legacy payment rows without student enrichment, not prod DB corruption.
## Verification

- No verification recorded yet.
- 2026-06-19T19:19:17: Prod read-only audit: academies=[acad_blno_badminton], invoices_2026_06_active=1 missing_student_id=0, pending_payments_2026_06=41 missing_student_id=0, payments student join health count=41 join_count=1. No prod writes run.
- 2026-06-19T19:19:17: Regression red/green: new test initially failed with student_name None in original branch; after patch selected admin payments composition tests passed (4). ruff check and ruff format --check passed for touched backend files.
- 2026-06-19T19:19:53: Clean PR worktree verification: pytest selected admin payments composition tests passed (4), ruff check passed, and ruff format --check passed using the existing backend virtualenv against the worktree files.
## Reusable Lessons

- None recorded yet.
