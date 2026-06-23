# issue 229 payout missing price warnings

## Current State

Status: active

## Problem

Verify typed percent-revenue payout warnings, payroll visibility, exports, setup warnings, and approval blocking for missing session prices without changing payout math or out-of-scope systems.

## Changed Files

- None recorded yet.

## Log

- 2026-06-22T07:25:38 main/NA: Task ledger created.
- 2026-06-22T07:43:14 main/working: Implemented typed payout warnings for missing price/rate/percent, persisted warning snapshots, monthly/detail/export API warning visibility, approve/mark-paid blocking, setup guards, and admin UI warning copy.
## Verification

- No verification recorded yet.
- 2026-06-22T07:43:14: Focused backend tests: 104 passed; backend v2 suite: 1491 passed; ruff format --check v2 and ruff check v2 passed; frontend warning vitest 3 passed; frontend node unit tests 25 passed; pnpm typecheck passed; pnpm lint passed with 5 existing warnings; pnpm build passed with same warnings. E2E skipped: no targeted payout/payroll E2E spec exists.
## Reusable Lessons

- None recorded yet.
