# dependency-pr-repair

## Current State

Status: active

## Problem

Consolidate open Dependabot PRs #389 and #403-#411, satisfy release-note validation, and reproduce/fix their CI failures.

## Changed Files

- None recorded yet.

## Log

- 2026-08-09T14:07:08 main/NA: Task ledger created.
- 2026-08-09T14:07:08 codex/working: Started from origin/main in isolated worktree; GitHub Actions inspection found missing release notes on all PRs, frontend audit failures, a Ruff lint failure, and an older FullCalendar build failure.
- 2026-08-09T14:17:57 codex/working: Applied consolidated compatible dependency pins; added patched transitive overrides; updated Ruff 0.16 lint/format compatibility across existing v2 files. pnpm audit now passes its high-severity gate; Ruff 0.16 check and format check pass.
- 2026-08-09T14:20:53 codex/working: Pre-push review found protobufjs 7.6.4 vulnerable in Firebase production path; added protobufjs >=7.6.5 override and regenerated lockfile. Re-audit now reports only 3 low and 1 moderate finding.
## Verification

- No verification recorded yet.
- 2026-08-09T14:17:57: pnpm audit --audit-level=high passed (5 low/moderate only); uvx --from ruff==0.16.1 ruff check backend/v2 and ruff format --check backend/v2 passed.
- 2026-08-09T14:20:53: Review remediation: pnpm audit --audit-level=high passed after protobufjs 7.6.5 lock resolution; pnpm lockfile confirms protobufjs@7.6.5.
## Reusable Lessons

- None recorded yet.
