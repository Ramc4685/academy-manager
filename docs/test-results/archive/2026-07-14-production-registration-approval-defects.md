# production registration approval defects

## Current State

Status: active

## Problem

Approval shows an error after succeeding, enrollment dates render as 1969, and already-enrolled students can appear as pending duplicate registrations

## Changed Files

- None recorded yet.

## Log

- 2026-07-14T07:53:49 main/NA: Task ledger created.
- 2026-07-14T08:13:44 main/working: Fixed exact TanStack list invalidation so successful approval does not refetch/fail detail; registration approvals now write application.created_at as enrolled_at; migration 0146 backfills existing missing dates; active-child matching blocks parent patch/admin approve/waitlist and filters stale pending duplicates; deterministic IDs plus atomic create compensate concurrent seat reservations; tenant attribution resolves request context in production.
## Verification

- No verification recorded yet.
- 2026-07-14T08:13:44: Focused backend regression/tenant/structural suite: 49 passed. Full backend: 2408 passed, 5 warnings. ruff format/check: passed. import-linter: 5 contracts kept. Frontend typecheck: passed; lint: 0 errors, 6 pre-existing warnings; build: passed. Playwright admin registration regression chromium-mobile: 1 passed.
- 2026-07-14T08:17:33: Final post-security-review rerun: ruff format --check v2 and ruff check v2 passed; full backend pytest v2/tests -q passed 2409 tests with 5 existing warnings. Session override divergence is rejected and partial-failure retry excludes the deterministic enrollment id.
## Reusable Lessons

- None recorded yet.
