# parent pay-balance startup crash

## Current State

Status: active

## Problem

Staging backend fails during FastAPI startup because ParentComposition is missing start_balance_payment_for_parent while compose_parent passes it.

## Changed Files

- None recorded yet.

## Log

- 2026-06-18T16:54:22 main/NA: Task ledger created.
- 2026-06-18T16:54:42 main/working: Focused parent composition test reproduces staging startup crash: ParentComposition rejects start_balance_payment_for_parent.
## Verification

- No verification recorded yet.
- 2026-06-18T16:55:51: RED before fix: source backend/.venv/bin/activate && pytest backend/v2/tests/unit/test_parent_composition.py -q => 2 failed with ParentComposition unexpected keyword start_balance_payment_for_parent. GREEN after fix: same command => 4 passed.
## Reusable Lessons

- None recorded yet.
