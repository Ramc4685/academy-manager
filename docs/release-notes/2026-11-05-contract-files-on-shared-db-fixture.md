# contract-files-on-shared-db-fixture

PR: #1143

## What changed
Eleven contract test files that built their own in-memory Mongo client now use the shared `db` fixture. That puts their 67 tests on the real MongoDB server in the "Backend Contract (real Mongo)" CI job. Without `CONTRACT_TESTS_MONGO_URL` they still run on mongomock locally. Test-only change; no product behaviour changes.

## Deploy notes
None. No migrations, no env vars, nothing ships to production.

## Risk / rollback
The real-Mongo CI job runs 67 more tests, adding a small amount of time under its 25-minute timeout. If one of them turns out flaky on a real server, revert the PR to put those files back on mongomock. Known limit: the shared fixture's real database has no migrations applied, so production validators are still not enforced on these tests.
