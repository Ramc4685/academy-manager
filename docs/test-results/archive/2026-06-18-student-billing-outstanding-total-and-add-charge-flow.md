# student billing outstanding total and add charge flow

## Current State

Status: active

## Problem

Student detail Billing tab shows only one current invoice amount when multiple invoices are unpaid, and Add charge appears not to work; verify root cause and fix the flow.

## Changed Files

- None recorded yet.

## Log

- 2026-06-18T09:24:48 main/NA: Task ledger created.

## Verification

- No verification recorded yet.
- 2026-06-18T09:30:09: Fixed student Billing summary to expose/display total outstanding balance across unpaid invoices while preserving latest current invoice selection; enabled Add charge for open invoices while keeping line removal draft-only. Verification: focused backend contract/add-line tests passed (13 tests), backend ruff format/check passed for touched backend files, frontend pnpm typecheck passed, frontend pnpm lint passed with 5 pre-existing warnings outside touched files, git diff --check passed. Local read-model check for Aadhya reports current June invoice 6000 and outstanding_balance_cents 12000 across May+June.
## Reusable Lessons

- None recorded yet.
