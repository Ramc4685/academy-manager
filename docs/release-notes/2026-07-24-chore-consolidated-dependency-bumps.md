# chore-consolidated-dependency-bumps

PR: #345

## What changed
Consolidates the open Dependabot version bumps into one green change, plus the
code fix required by the FastAPI upgrade. Supersedes and closes the individual
Dependabot PRs #333–#342.

Backend (`backend/requirements.txt`):
- annotated-types 0.7.0 → 0.8.0 (#333)
- fastapi 0.136.3 → 0.139.2 (#334)
- openai 2.44.0 → 2.48.0 (#335)
- stripe 15.1.0 → 15.3.1 (#336)
- tzlocal 5.4.3 → 5.4.4 (#337)

Frontend (`frontend/package.json`):
- @tanstack/query-sync-storage-persister 5.101.2 → 5.101.4 (#338)
- autoprefixer 10.5.0 → 10.5.4 (#339)
- @radix-ui/react-dialog 1.1.18 → 1.1.21 (#340)
- @tanstack/react-query 5.101.2 → 5.101.4 (#341)
- @playwright/test 1.61.0 → 1.61.1 (#342)
- @tanstack/react-query-persist-client 5.101.2 → 5.101.4 (kept in lockstep with
  the react-query bump; a split leaves two `@tanstack/query-core` versions and
  fails typecheck)

Code fix for the FastAPI bump:
- FastAPI 0.139 keeps an `_IncludedRouter` wrapper in `app.routes` instead of
  eagerly flattening mounted routes, so `route.path` no longer surfaces nested
  business routes. Added `backend/v2/tests/_route_paths.py` (`iter_route_paths`
  / `route_paths`) which walks the wrapper tree, and switched
  `test_healthz.py` and `test_saas_production_wiring.py` onto it. The helper is
  backward-compatible with FastAPI < 0.139.

## Deploy notes
None. Dependency bumps only; no schema, env, or config changes. Standard
backend + frontend deploy picks up the new versions.

## Risk / rollback
Low. All are patch/minor bumps within the same majors. Full backend suite
(2556 tests), ruff, import-linter, pip-audit, and frontend typecheck/lint/audit
pass locally. To roll back, revert this commit to restore the prior pins.
