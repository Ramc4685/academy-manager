# Autopay projection backfill and graceful activation

## Current State

Status: active

## Problem

2026-07-04 prod incident follow-up: student_billing_enrollments projection empty for legacy-flow enrollments broke CompleteAutopaySetup (RuntimeError 500 on checkout-status poll). Add idempotent 0145 backfill migration, repo-level self-heal from legacy enrollments, AutopayActivationFailed domain error, and an audited admin toggle for billing_settings.allow_platform_charge_fallback.

## Changed Files

- `backend/v2/migrations/0145_backfill_student_billing_enrollments.py`
- `backend/v2/contexts/billing/infrastructure/mongo_student_billing_enrollment_repo.py`
- `backend/v2/contexts/billing/domain/errors.py`
- `backend/v2/contexts/billing/application/use_cases/parent_billing.py`
- `backend/v2/contexts/billing/application/use_cases/billing_settings_admin.py`
- `backend/v2/interfaces/admin/billing_routes.py`
- `backend/v2/composition/admin.py`

## Log

- 2026-07-05T10:33:40 main/NA: Task ledger created.

## Verification

- No verification recorded yet.
- 2026-07-05T10:34:37: pytest backend/v2/tests -q: 2107 passed, 1 CWD-artifact failure (test_bootstrap_academy passes from backend/ cwd, 5 passed). Focused suites: migration 0145 (7), repo self-heal (4 new, 59 total file), billing_settings_admin unit (5), parent billing portal + webhook + admin billing interface (156). ruff check/format v2 clean; lint-imports 4 contracts kept; raw-Mongo tenant guard passes.
## Reusable Lessons

- None recorded yet.
