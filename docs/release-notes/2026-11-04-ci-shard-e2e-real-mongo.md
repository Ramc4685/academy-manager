# ci-shard-e2e-real-mongo

PR: #1130

## What changed
CI-only. The Chromium mobile Playwright gate runs as two shards so it no longer hits its 12-minute budget and cancels main deploys. The backend contract (repository) tests now also run against the real MongoDB 8.0 that CI installs, in a new "Backend Contract (real Mongo)" job, instead of only mongomock. Three contract test files had seeds that production validators reject; the seeds now satisfy them. No application code changed.

## Deploy notes
None. No migration, no env vars, no runtime change. The required status checks are unchanged (CI Gate, Release Notes Gate).

## Risk / rollback
If wrong, a pull request is blocked on a CI job, not on production behavior. The real-Mongo job is new and its first 8.0 run is this PR's CI; if it proves flaky, drop it from the ci-gate needs list while keeping the fixture. Roll back by reverting the PR.
