# fix and deploy PRs 188-192

## Current State

Status: active

## Problem

PRs 188, 189, 190, 191, and 192 need review, fixes for failing checks or comments, verification, and deployment/merge handling.

## Changed Files

- None recorded yet.

## Log

- 2026-06-13T12:38:59 main/NA: Task ledger created.
- 2026-06-13T12:51:20 main/working: PR190 focused fixes applied: lesson-card upserts now scoped by program, coach audiences resolve from active memberships, copied Shuttle Time markdown removed. Focused backend tests passed.
- 2026-06-13T13:01:39 main/working: Pushed fixes for PR188, PR189, PR190, PR191, and PR192. Local pre-push hooks passed for each pushed branch; E2E skipped where no e2e files changed.
- 2026-06-13T13:20:46 main/working: Merged PR190 and PR189 into main via server-side squash merges. PR188 CI still running after latest main merge. PR191/192 remain draft despite green checks.
## Verification

- No verification recorded yet.
- 2026-06-13T17:09:15: Merged and deployed PR188, PR189, PR190, PR191, PR192. Main production workflow runs for each merged PR completed with Backend, Backend Lint, Frontend Static, Frontend E2E Chromium/WebKit, Deploy Backend, Deploy Frontend, and Production Smoke successful.
## Reusable Lessons

- None recorded yet.
