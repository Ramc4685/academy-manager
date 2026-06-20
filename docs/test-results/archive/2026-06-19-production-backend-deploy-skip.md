# production backend deploy skip

## Current State

Status: active

## Problem

Deploy Backend skipped on push-to-main run 27855053131 after backend-only merge because frontend jobs were skipped.

## Changed Files

- None recorded yet.

## Log

- 2026-06-19T21:07:20 main/NA: Task ledger created.
- 2026-06-19T21:08:18 main/working: Added explicit always() status guards to deploy-backend and deploy-frontend so backend-only pushes are not blocked by intentionally skipped frontend jobs.
## Verification

- No verification recorded yet.
- 2026-06-19T21:08:19: git diff --check passed; go run github.com/rhysd/actionlint/cmd/actionlint@latest .github/workflows/production.yml passed.
- 2026-06-19T21:09:16: scripts/dev/pre-push-checks.sh failed in isolated worktree because frontend/node_modules was missing; backend checks passed before frontend typecheck/lint missing-package failures.
- 2026-06-19T21:10:08: scripts/dev/pre-push-checks.sh passed after linking existing frontend/node_modules into the isolated worktree; E2E skipped by script because no e2e/ files changed.
## Reusable Lessons

- None recorded yet.
