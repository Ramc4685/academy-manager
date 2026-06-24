# tuition discounts phase b

## Current State

Status: active

## Problem

Verify parent invoice itemization and finance reporting for recurring tuition discounts

## Changed Files

- None recorded yet.

## Log

- 2026-06-24T07:04:49 main/NA: Task ledger created.
- 2026-06-24T07:13:28 main/working: Phase B implemented: ledger projection now writes tuition + discount lines with gross/discount/net identity; parent invoice detail exposes discount label without internal fields; added tuition discount summary query and admin finance route; parent UI renders line label when present.
## Verification

- No verification recorded yet.
- 2026-06-24T07:13:28: Focused lint/typecheck: ruff format --check and ruff check on touched backend files passed; frontend npx tsc --noEmit passed; npm run lint passed with 5 existing warnings and 0 errors.
- 2026-06-24T07:13:28: Focused Phase B backend: pytest test_mongo_payment_repo_discounts.py test_parent_invoice_routes.py test_finance_mongo_repos.py test_admin_billing.py -q -> 90 passed, 1 StarletteDeprecationWarning.
- 2026-06-24T07:14:22: Broader backend regression: python -m pytest backend/v2/tests/unit backend/v2/tests/application backend/v2/tests/contract backend/v2/tests/interface -q -k 'discount or payment or billing or ledger or student' -> 460 passed, 1008 deselected, 3 warnings.
- 2026-06-24T07:17:31: Full pre-push check: git diff --check && scripts/dev/pre-push-checks.sh -> backend ruff format/check passed, backend pytest v2/tests passed, frontend node unit tests passed, pnpm typecheck passed, pnpm lint passed; E2E skipped because no e2e/ files changed; exit 0.
## Reusable Lessons

- None recorded yet.
