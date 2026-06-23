# production e2e failed action 27343184757

## Current State

Status: archived

## Problem

GitHub Actions run 27343184757 failed frontend E2E Chromium/WebKit because the admin replacement-coach test used an expired date; verify the test fixture stays valid over time. PR verification also exposed a WebKit-only flaky Google redirect test that failed CI under failOnFlakyTests.

## Changed Files

- frontend/e2e/specs/admin-session-creation-ui.spec.ts
- frontend/e2e/specs/google-signin-mode.spec.ts
- frontend/lib/auth/firebase.ts

## Log

- 2026-06-11T06:47:31 main/NA: Task ledger created.
- 2026-06-11T06:52:34 main/working: Fixed the replacement coach E2E fixture by computing the next valid Wednesday date instead of hard-coding 2026-06-10, which became invalid after the UI min=today guard on 2026-06-11.
- 2026-06-11T12:24:00 main/working: Made Google sign-in E2E bypass deterministic for mobile redirect mode so WebKit no longer depends on the Firebase SDK network redirect handoff during CI.

## Verification

- pnpm install --frozen-lockfile completed in the clean worktree.
- pnpm exec playwright test e2e/specs/admin-session-creation-ui.spec.ts -g "session detail adds replacement coach" --project=chromium-mobile --project=webkit-mobile passed 2/2.
- pnpm exec playwright test e2e/specs/google-signin-mode.spec.ts --project=webkit-mobile --repeat-each=3 passed 3/3.
- pnpm exec playwright test e2e/specs/google-signin-mode.spec.ts --project=webkit-mobile --repeat-each=5 passed 5/5 after the deterministic E2E redirect change.
- node --no-warnings --test lib/api/*.node-test.mjs lib/auth/*.node-test.mjs passed 19/19.
- pnpm typecheck passed.
- pnpm lint passed with no ESLint warnings or errors.
- CI=1 pnpm exec playwright test --project=chromium-mobile passed 75, skipped 15.
- CI=1 pnpm exec playwright test --project=webkit-mobile passed 75, skipped 15.

## Reusable Lessons

- Date-sensitive E2E fixtures must avoid hard-coded dates that can fall outside product validation windows.
- E2E auth bypass should avoid real third-party SDK redirect handoffs when the test only needs to assert the app's routing choice.
