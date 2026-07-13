# issue-300-flaky-admin-reports-route

## Current State

Status: complete

## Problem

Investigate and resolve intermittent admin reports route-matrix timeout under sustained Playwright suite load.

## Changed Files

- `frontend/e2e/specs/saas-launch-route-matrix.spec.ts`

## Log

- 2026-07-13T08:09:39 main/NA: Task ledger created.
- 2026-07-13T08:22:37 main/working: Root cause confirmed: the route-matrix catch-all returned `{}` for new reports APIs. After delayed Next dev compilation, `AdminReportsPage` crashed at `paymentFeedQuery.data?.payments.length`; the 45-second locator wait masked the component error as a timeout. Updated the route-matrix stubs and added async empty-state assertions.

## Verification

- RED: `CI=1 PLAYWRIGHT_PORT=3114 pnpm exec playwright test --project=chromium-mobile --workers=1 --reporter=line` — reports failed twice at test 168/189; trace showed the `TypeError` at `reports/page.tsx:345`.
- Focused GREEN: `CI=1 PLAYWRIGHT_PORT=3115 pnpm exec playwright test e2e/specs/saas-launch-route-matrix.spec.ts --workers=1 -g 'admin route mounts: reports' --reporter=list` — 2 passed (Chromium and WebKit).
- Sustained Chromium GREEN: `CI=1 PLAYWRIGHT_PORT=3116 pnpm exec playwright test --project=chromium-mobile --workers=1 --reporter=line` — 102 passed, 87 skipped; reports passed at 168/189.
- Sustained WebKit: reports passed after 168 preceding executions. The overall project exited 1 because the unrelated admin-shell session-detail mount failed once and then passed on retry; 101 passed, 87 skipped.
- Static checks: `pnpm typecheck` passed. `pnpm lint` exited 0 with six existing warnings.

## Reusable Lessons

- A delayed locator timeout can mask a component error when dev-server compilation postpones hydration. Inspect Playwright error context and console traces before treating a late-suite failure as resource accumulation.
- Route-matrix tests should wait for representative async content, not only a top-level mount marker, when malformed API fixtures can crash immediately after initial render.
