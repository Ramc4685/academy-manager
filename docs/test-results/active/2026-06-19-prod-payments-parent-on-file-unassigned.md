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
- 2026-06-19T19:26:08 main/working: CI run 27854504008 failed in Backend dependency vulnerability scan. Job log shows pip-audit -r requirements.txt found pydantic-settings 2.14.1 vulnerable to GHSA-4xgf-cpjx-pc3j; fixed version is 2.14.2.
## Verification

- No verification recorded yet.
- 2026-06-19T19:19:17: Prod read-only audit: academies=[acad_blno_badminton], invoices_2026_06_active=1 missing_student_id=0, pending_payments_2026_06=41 missing_student_id=0, payments student join health count=41 join_count=1. No prod writes run.
- 2026-06-19T19:19:17: Regression red/green: new test initially failed with student_name None in original branch; after patch selected admin payments composition tests passed (4). ruff check and ruff format --check passed for touched backend files.
- 2026-06-19T19:19:53: Clean PR worktree verification: pytest selected admin payments composition tests passed (4), ruff check passed, and ruff format --check passed using the existing backend virtualenv against the worktree files.
- 2026-06-19T19:31:57: Post-CI-fix backend verification passed: python -m compileall ., PYTHONPATH=/Users/ramc/Documents/Code/academy-manager/.worktrees/admin-payments-legacy-student-name lint-imports --config pyproject.toml, and pytest v2/tests --override-ini=testpaths=v2/tests --cov=v2/shared --cov-report=term-missing --cov-fail-under=70 (1421 passed, coverage 87.22%).
- 2026-06-19T19:31:57: CI failure 27854504008 reproduced locally: cd backend && source .venv/bin/activate && pip-audit -r requirements.txt failed on pydantic-settings 2.14.1 / GHSA-4xgf-cpjx-pc3j. Updated backend/requirements.txt to pydantic-settings==2.14.2; pip-audit -r requirements.txt now reports no known vulnerabilities.
- 2026-06-19T19:32:48: scripts/dev/pre-push-checks.sh after dependency bump: backend ruff format/check and pytest v2/tests passed; frontend typecheck/lint failed because isolated worktree had no frontend/node_modules. This is a local worktree setup issue, not a code failure; rerunning with local dependency symlink.
- 2026-06-19T19:33:59: scripts/dev/pre-push-checks.sh passed after local worktree dependency symlink: backend ruff format/check, pytest v2/tests, frontend node tests, pnpm typecheck, pnpm lint; E2E skipped because no e2e/ files changed.
## Reusable Lessons

- None recorded yet.
