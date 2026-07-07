# parent-self-service

## Current State

Status: active

## Problem

Verify Task 13 for the parent self-service feature (absences, makeups, trials, enrollment self-cancel, admin queues/policy settings): new Playwright e2e coverage plus the full backend/frontend verification sweep.

## Changed Files

- `frontend/e2e/specs/parent-self-service.spec.ts`
- `docs/release-notes/2026-07-06-parent-self-service.md`

## Log

- 2026-07-07T07:48:04 main/NA: Task ledger created.
- 2026-07-07T07:48:13 main/working: Added frontend/e2e/specs/parent-self-service.spec.ts (mocked v2 BFF, mirrors coach-offline-writes.spec.ts conventions): 5 scenarios covering absences (existing notice list, on-time submit success, late-notice warning banner), makeup request (pending status chip), and enrollment self-cancel (fee/timing preview visible before confirm, then confirmation). Ran with npx playwright test parent-self-service on both configured projects.
- 2026-07-07T13:26:37 main/working: Merged origin/main into PR #289 and resolved admin composition/deps conflicts by preserving parent self-service admin use cases plus main's platform-charge fallback use cases.
## Verification

- No verification recorded yet.
- 2026-07-07T07:48:25: npx playwright test parent-self-service (chromium-mobile + webkit-mobile): 10/10 passed.
- 2026-07-07T07:48:25: cd backend && source .venv/bin/activate && pytest v2/tests -q: 2271 passed, 2 failed. Both failures are pre-existing and unrelated to this task: test_audit_inventory_manifest.py::test_inventory_manifest_matches_frontend_app_route_tree and test_inventory_static_gaps.py::test_current_inventory_manifest_has_no_static_source_gaps fail because docs/qa/2026-06-28-production-scale-local-inventory-manifest.json (dated before this feature) does not list the new /admin/requests, /admin/settings/self-service, and /parent/requests routes added in Tasks 10-12. Not fixed here; out of Task 13 scope.
- 2026-07-07T07:48:25: cd backend && source .venv/bin/activate && ruff format --check v2 && ruff check v2: both clean (795 files already formatted; all checks passed).
- 2026-07-07T07:48:25: lint-imports --config backend/pyproject.toml (run from repo root, backend/.venv activated): 4 contracts kept, 0 broken.
- 2026-07-07T07:48:35: cd frontend && pnpm typecheck: clean. pnpm lint: 0 errors, 5 pre-existing warnings unrelated to this feature (parent/dashboard, branding-panel, vitals.ts, persistence.ts, postcss.config.mjs).
- 2026-07-07T07:48:35: cd frontend && node --no-warnings --test lib/api/*.node-test.mjs lib/auth/*.node-test.mjs: 32/32 passed.
- 2026-07-07T07:48:35: cd frontend && pnpm exec vitest run --exclude 'e2e/**': 22/22 passed across 6 files, including lib/parent-requests.test.ts (2/2, touched by this feature). Note: unscoped 'pnpm exec vitest run' picks up e2e/specs/*.spec.ts and fails 22 files with Playwright-vs-Vitest test.describe collisions -- a pre-existing vitest.config.ts include/exclude gap, not caused by this task. Excluding e2e/** is required to get a clean vitest run.
- 2026-07-07T13:28:33: Conflict resolution verification: rg conflict markers in backend/v2/composition/admin.py backend/v2/interfaces/admin/deps.py found none; git diff --check clean; cd backend && source .venv/bin/activate && ruff format --check v2/composition/admin.py v2/interfaces/admin/deps.py && ruff check v2/composition/admin.py v2/interfaces/admin/deps.py && pytest v2/tests/unit/test_billing_settings_admin.py v2/tests/interface/test_admin_self_service_requests.py v2/tests/interface/test_admin_self_service_policies.py -q passed (34 passed); repo-root import check for compose_admin/AdminUseCases passed; cd backend && source .venv/bin/activate && pytest v2/tests/unit/test_admin_composition_tenancy.py v2/tests/contract/test_admin_billing_idempotency.py -q passed (29 passed); cd frontend && pnpm exec node --no-warnings --test lib/parent-autopay-optin.node-test.mjs lib/api/*.node-test.mjs lib/auth/*.node-test.mjs passed (45 passed).
## Reusable Lessons

- None recorded yet.
