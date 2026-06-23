# admin payments unassigned student investigation

## Current State

Status: active

## Problem

Admin payments list shows Unassigned students and may show paid invoices without a resolved student; determine whether seed data or BFF mapping is the root cause.

## Changed Files

- None recorded yet.

## Log

- 2026-06-18T09:07:56 main/NA: Task ledger created.
- 2026-06-18T09:09:25 main/working: Root-cause evidence: local academy_manager_saas_staging has 115 BLNO invoices and 46 students, but all 115 invoices have student_id null; admin payments BFF copies null student_id and student detail Billing tab cannot resolve current invoice/payment history for a selected student.
## Verification

- No verification recorded yet.
- 2026-06-18T09:15:42: Fixed BLNO seed to create student/enrollment-owned tuition invoices and enriched admin payments invoice rows with student names. Verification: targeted tests passed (43 focused tests); ruff format/check passed for touched files; disposable BLNO seed DB had 0 invoices with missing student_id, Aadhya had current June invoice + 3 payment-history rows through MongoStudentRepository; launch_readiness_audit passed on disposable DB.
## Reusable Lessons

- None recorded yet.
