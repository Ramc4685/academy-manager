# coach payroll percentage rules

## Current State

Status: active

## Problem

Verify percentage-based coach pay, absence gating, replacement attribution, and admin pay-rate management

## Changed Files

- None recorded yet.

## Log

- 2026-06-09T18:04:31 main/NA: Task ledger created.
- 2026-06-09T18:04:31 main/working: Added percent_of_revenue coach rates, attendance gating + overrides in ComputeCoachPayout and billing derive path, expected-revenue resolver, admin pay-rate routes + UI
- 2026-06-09T20:37:11 main/working: Item 4: past non-cancelled occurrences now count as completed in both payout paths (billing derive filter + composition adapter status mapping)
## Verification

- No verification recorded yet.
- 2026-06-09T18:04:31: backend: pytest v2/tests 990 passed; ruff format+check clean. frontend: tsc clean, eslint clean, node unit tests pass. E2E skipped (no e2e changes).
- 2026-06-09T20:37:11: pytest v2/tests 992 passed (2 new contract tests for completion derivation); ruff clean
## Reusable Lessons

- None recorded yet.
