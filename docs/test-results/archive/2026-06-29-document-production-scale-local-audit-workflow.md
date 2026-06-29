# document production-scale local audit workflow

## Current State

Status: active

## Problem

Agents need durable guidance for the new production-scale local audit workflow before this branch is committed and opened as a PR.

## Changed Files

- None recorded yet.

## Log

- 2026-06-29T11:22:17 main/NA: Task ledger created.
- 2026-06-29T11:23:18 main/working: Updated AGENTS.md plus testing and feedback-loop docs so future agents know when and how to run the production-scale local audit, how to interpret READY/CLEAN_PASS, and how to hand off evidence.
## Verification

- No verification recorded yet.
- 2026-06-29T11:23:35: Focused docs/audit verification: python3 -m json.tool docs/qa/2026-06-28-production-scale-local-inventory-manifest.json passed; pytest test_saas_staging_scale_command.py test_local_auth_audit_readiness.py test_inventory_gate.py test_inventory_static_gaps.py -q => 32 passed; git diff --check clean.
- 2026-06-29T11:31:07: Full pre-push verification passed: scripts/dev/pre-push-checks.sh --full => backend ruff format/check, backend pytest v2/tests, frontend node unit, typecheck, lint, and pnpm e2e all passed.
## Reusable Lessons

- None recorded yet.
