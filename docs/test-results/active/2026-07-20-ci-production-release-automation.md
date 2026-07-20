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
- 2026-07-20T12:21:47 main/working: Opened draft PR #309; stamped the assigned PR number into the release note. Awaiting GitHub checks after the final metadata push.
## Verification

- No verification recorded yet.
- 2026-07-20T12:16:11: python3 -m unittest discover -s scripts/dev/tests -p 'test_*.py' -v: 10 passed.
- 2026-07-20T12:16:11: scripts/dev/pre-push-checks.sh: backend ruff format/lint, full v2 pytest, frontend node unit, typecheck, and lint passed; E2E skipped because no e2e files changed.
- 2026-07-20T12:16:11: publish_release.py --dry-run against production run 29695159704: selected deploy-2026-07-14-pr-299 baseline and generated deterministic deploy-2026-07-19-a529bacb72fe catch-up notes for PRs 302-307 without publishing.
- 2026-07-20T12:16:11: Python py_compile, focused Ruff, Ruby YAML parse, and git diff --check passed. actionlint unavailable locally.
- 2026-07-20T12:22:03: Final focused suite after security hardening: 11 passed, including the 8-case smoke-gate event/component matrix.
- 2026-07-20T12:22:03: Academy security reviewer final pass: no actionable findings; write-privileged checkout pinned to actions/checkout d23441a48e516b6c34aea4fa41551a30e30af803.
## Reusable Lessons

- None recorded yet.
