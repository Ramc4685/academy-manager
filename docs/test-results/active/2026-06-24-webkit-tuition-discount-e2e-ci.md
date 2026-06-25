# webkit tuition discount e2e ci

## Current State

Status: active

## Problem

Fix GitHub Actions run 28123336214 Frontend E2E WebKit failure in tuition-discounts.spec.ts strict-mode discount button selector

## Changed Files

- None recorded yet.

## Log

- 2026-06-24T17:40:05 main/NA: Task ledger created.
- 2026-06-24T17:41:56 main/working: Root cause from GitHub Actions run 28123336214: WebKit mobile strict-mode violation in tuition-discounts.spec.ts after first discount save; selector matched two Discount buttons before the first row render settled. Patched the test to scope buttons by session row and wait for the scholarship row update before clicking the coach-child row.
## Verification

- No verification recorded yet.
- 2026-06-24T17:42:50: Focused verification passed after selector hardening: CI=true npx playwright test --project=webkit-mobile e2e/specs/tuition-discounts.spec.ts -> 2 passed; npx playwright test --project=chromium-mobile e2e/specs/tuition-discounts.spec.ts -> 2 passed; pnpm typecheck -> passed; pnpm lint -> passed with 5 existing warnings and 0 errors.
- 2026-06-24T17:51:39: Full pre-push gate attempt after patch: frontend node unit tests, typecheck, lint, and full pnpm e2e passed; backend ruff format/check passed; backend pytest failed only because this fresh local venv was created with Python 3.14, while CI/project expects Python 3.12, causing asyncio.get_event_loop RuntimeError in unrelated skill/progress tests.
- 2026-06-24T17:59:53: Full pre-push gate passed after rebuilding backend/.venv with Python 3.12: scripts/dev/pre-push-checks.sh --full -> backend ruff format/check passed, backend pytest v2/tests passed, frontend node unit tests passed, pnpm typecheck passed, pnpm lint passed, pnpm e2e passed; exit 0.
## Reusable Lessons

- None recorded yet.
