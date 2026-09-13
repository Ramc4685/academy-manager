## What changed
- Fixes #540 — Added a terminal catch-all route to the mock-api Playwright fixture (`frontend/e2e/fixtures/mock-api.ts`), registered after all specific stubs. Any `/api/v2/**` request not matched by a specific route now gets an instant 404 JSON body `{error:{code:"e2e_unstubbed", message: path}}` instead of falling through to the dead e2e backend (`ECONNREFUSED 127.0.0.1:8001`). Each unmatched path is recorded in a new `MockState.unstubbed` array, and a new `expectNoUnstubbedRequests(mock)` helper is exported so specs can assert nothing unexpected was hit.

## Deploy notes
No migrations. No backend or runtime behavior change — this only affects the Playwright e2e mock-api test fixture used in CI/local test runs.

## Risk / rollback
Low risk: purely additive to the test fixture (a fallback route plus a new assertion helper); no production code path is touched. Verified by running the full chromium-mobile e2e project (339 tests) with zero regressions. Rollback is reverting this PR.

PR: #811
