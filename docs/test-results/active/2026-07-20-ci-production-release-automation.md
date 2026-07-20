# CI production release automation

## Current State

Status: active

## Problem

Release Notes mutates PR branches and retriggers full CI; successful production smoke does not publish a GitHub Release.

## Changed Files

- None recorded yet.

## Log

- 2026-07-20T12:04:43 main/NA: Task ledger created.
- 2026-07-20T12:12:45 main/working: Implemented read-only PR release-note validation, strict changed-component smoke gating, deterministic post-smoke GitHub Release publication, backlog note cleanup, docs, and focused unit/workflow policy tests.
## Verification

- No verification recorded yet.
- 2026-07-20T12:16:11: python3 -m unittest discover -s scripts/dev/tests -p 'test_*.py' -v: 10 passed.
- 2026-07-20T12:16:11: scripts/dev/pre-push-checks.sh: backend ruff format/lint, full v2 pytest, frontend node unit, typecheck, and lint passed; E2E skipped because no e2e files changed.
- 2026-07-20T12:16:11: publish_release.py --dry-run against production run 29695159704: selected deploy-2026-07-14-pr-299 baseline and generated deterministic deploy-2026-07-19-a529bacb72fe catch-up notes for PRs 302-307 without publishing.
- 2026-07-20T12:16:11: Python py_compile, focused Ruff, Ruby YAML parse, and git diff --check passed. actionlint unavailable locally.
## Reusable Lessons

- None recorded yet.
