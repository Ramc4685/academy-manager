# prod coach pay rate 500 hotfix

## Current State

Status: active

## Problem

Admin setting a coach pay rate in production returns HTTP 500 for /api/v2/admin/coaches/{coach_id}/pay-rates

## Changed Files

- None recorded yet.

## Log

- 2026-06-14T17:17:19 main/NA: Task ledger created.
- 2026-06-14T17:17:19 main/working: Clean origin/main hotfix branch: normalize Mongo coach-rate datetimes to UTC-aware values and add regression coverage for superseding an existing naive effective_from rate.
## Verification

- No verification recorded yet.
- 2026-06-14T17:18:06: Clean origin/main hotfix branch verification: ruff format --check v2 passed; ruff check v2 passed; focused pay-rate tests passed 11; pytest v2/tests -q passed 1162, 3 warnings.
- 2026-06-14T17:24:45: Production deploy: flyctl deploy -a courtmastr-academy-api from commit 02b7794f completed; image registry.fly.io/courtmastr-academy-api:deployment-01KV43E39TZQYY12DFTK4QQD37. Post-deploy curl https://api.academy.courtmastr.com/api/v2/healthz returned {"status":"ok"}; flyctl status shows machine 781960b93e5d18 started with 1/1 checks passing.
## Reusable Lessons

- None recorded yet.
