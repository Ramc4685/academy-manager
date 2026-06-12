# stripe payment hotfix

## Current State

Status: active

## Problem

Verify async Stripe webhook processing, admin reconciliation, billing portal/payment UX hotfix, CI failure fix, and PR review comment fixes.

## Changed Files

- None recorded yet.

## Log

- 2026-06-12T08:41:20 main/NA: Task ledger created.
- 2026-06-12T08:41:24 main/working: Addressed PR Codex comments: tenant-scoped Stripe webhook claims/processors and persisted stripe_payment_intent_id during admin reconciliation.
- 2026-06-12T08:56:42 main/working: Push hook surfaced a load-sensitive WebKit flake in google-signin-mode E2E; stabilized the test with explicit enabled-button readiness, URL wait before click, and a 60s timeout for this redirect case.
- 2026-06-12T10:45:37 main/working: Prod reconcile 500 root cause: Stripe SDK objects in production expose _to_dict_recursive, not to_dict_recursive; gateway retrieval crashed before reconciliation could continue. Added conversion helper and Stripe lookup error wrapping.
- 2026-06-12T10:49:37 main/working: Prod Connect-link 500 root cause: Stripe Connect client ID is not configured in production; route leaked ValueError as 500. Added route-level 503 mapping so admin sees the configuration problem instead of Internal Server Error.
## Verification

- No verification recorded yet.
- 2026-06-12T08:42:31: Focused backend: source backend/.venv/bin/activate && pytest backend/v2/tests/application/test_webhook_handler.py -q -> 21 passed. Frontend: pnpm typecheck -> passed. Backend lint: ruff check v2 -> passed before final full pre-push.
- 2026-06-12T08:45:46: Full pre-push: scripts/dev/pre-push-checks.sh -> passed backend format/lint/tests, frontend unit/type/lint, and pnpm e2e.
- 2026-06-12T09:00:48: Full pre-push rerun after Google sign-in E2E stabilization: scripts/dev/pre-push-checks.sh -> passed backend format/lint/tests, frontend unit/type/lint, and pnpm e2e.
- 2026-06-12T10:45:38: Focused regression: pytest backend/v2/tests/infrastructure/test_stripe_gateway_request_shape.py -q -> 4 passed after reproducing AttributeError and raw StripeError failures.
- 2026-06-12T10:46:39: Follow-up pre-push: scripts/dev/pre-push-checks.sh -> passed backend format/lint/tests, frontend unit/type/lint; E2E skipped because no e2e files changed.
- 2026-06-12T10:49:37: Focused Connect route regression: pytest backend/v2/tests/interface/test_admin_settings.py -q -> 8 passed after reproducing escaping ValueError failure.
- 2026-06-12T10:50:15: Follow-up pre-push after Connect route fix: scripts/dev/pre-push-checks.sh -> passed backend format/lint/tests, frontend unit/type/lint; E2E skipped because no e2e files changed.
## Reusable Lessons

- None recorded yet.
