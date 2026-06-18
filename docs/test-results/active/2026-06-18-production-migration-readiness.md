# production migration readiness

## Current State

Status: active

## Problem

Verify current branch is production-ready, confirm startup fix, review required production migrations for safety, and prepare exact migration/deploy runbook without executing production changes.

## Changed Files

- `backend/v2/migrations/0071_account_credit_ledger_indexes.py`
- `backend/v2/tests/infrastructure/test_stripe_gateway_request_shape.py`
- `docs/test-results/active/2026-06-18-production-migration-readiness.md`
- `test_result.md`

## Log

- 2026-06-18T17:12:23 main/NA: Task ledger created.
- 2026-06-18T17:12:50 main/working: Kickoff complete. Current branch is clean and ahead of origin by 4 commits; startup fix is already committed as de818337. Reviewing migrations 0071 and 0130-0133 before any production command.
- 2026-06-18T17:13:43 main/working: Migration review: runner applies absent versions from v2_migrations. Fly has V2_RUN_MIGRATIONS_ON_BOOT=true. 0130 adds Stripe/ledger indexes; 0132/0133 add launch validators and outbox indexes/backfill; 0131 mutates users/parent_billing_customers and drops retired indexes but does not delete payments rows.
## Verification

- 2026-06-18T17:14:22: Focused backend verification after formatting: source backend/.venv/bin/activate && pytest backend/v2/tests/unit/test_parent_composition.py backend/v2/tests/contract/test_migrations_legacy_compat.py backend/v2/tests/infrastructure/test_stripe_gateway_request_shape.py backend/v2/tests/interface/test_parent_invoice_routes.py -q => 28 passed, 1 known Starlette/httpx warning.
- 2026-06-18T17:14:22: Style: source backend/.venv/bin/activate && ruff format --check targeted backend migration/composition/test files => 9 files already formatted; ruff check same files => All checks passed.
- 2026-06-18T17:15:28: Pre-push: scripts/dev/pre-push-checks.sh => passed. Backend ruff format/check and pytest v2/tests passed; frontend node unit tests, pnpm typecheck, pnpm lint passed; E2E skipped because no e2e/ files changed.
- 2026-06-18T17:17:37: Local stack: scripts/local_test_stack.sh all exited 1. It reported frontend proxy health did not respond within 90s; later direct curls to backend/frontend health failed during shutdown/transition. Logs show prior backend startup and many frontend /api/v2 requests, but local smoke is not a pass.
- 2026-06-18T17:19:25: Read-only local launch audit: APP_TENANCY_MODE=single_academy PRIMARY_ACADEMY_ID=acad_blno_badminton ENABLE_PLATFORM_ROUTES=false ENABLE_OWNER_ROLE=false ENABLE_STUDENT_LOGIN=false CORS_ORIGINS=http://localhost:3001,http://blno.localhost:3001 python backend/scripts/launch_readiness_audit.py --mongo-url mongodb://127.0.0.1:27017 --db-name academy_manager_saas_staging => status=pass; required indexes, validators, ledger payment storage, billing consistency, webhook/outbox health passed.
- 2026-06-18T17:19:51: Local health: curl -sS -i http://127.0.0.1:8001/api/v2/healthz => HTTP 200 {status: ok}. Frontend proxy curl http://localhost:3001/api/v2/healthz => connection failed because frontend is stopped after local_test_stack.sh all exited non-zero.
## Reusable Lessons

- None recorded yet.
