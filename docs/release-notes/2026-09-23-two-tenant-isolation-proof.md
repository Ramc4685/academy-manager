# Automated two-tenant isolation proof (roadmap L10)

PR: #TBD

## What changed

- New contract test `backend/v2/tests/contract/test_two_tenant_isolation.py` replaces the manual "Tenant isolation" check in `docs/runbooks/saas-admin-route-matrix.md`. It boots the real v2 app in SaaS mode on a throwaway, fully migrated database on the CI `mongod`, seeds two academies with synthetic data, and reads the admin, coach and parent routes from the app's router.
- Every route with a path parameter (175 today) is called by academy A's actor with academy B's ids. The route must not crash, must return none of B's data, and must leave B's stored documents unchanged. Every GET route without a path parameter (96) is scanned for B's ids and names. The 50 GET detail routes get a positive control: B reads its own ids first, which proves the seed is real. Each actor's token is also refused on the other academy's host.
- Route coverage and per-outcome counts are printed in the pytest warnings summary. `CROSS_TENANT_ALLOWLIST` (reviewed exceptions) and `KNOWN_LEAKS` (strict xfail with the issue number) are both empty: the run found no cross-tenant read or write.
- The runbook's cross-route check now points to the test.
- Test and docs only. No application code, route, migration or frontend change.

## Deploy notes

- Nothing to deploy. The test runs in the existing backend CI job, which already provides a `mongod` service. It skips when no `mongod` is reachable, like the other real-mongod contract tests.

## Risk / rollback

- None for production. The CI cost is one migrated database and one app boot per xdist worker, about a minute of wall time with 4 workers.
- Rollback: revert the PR.
