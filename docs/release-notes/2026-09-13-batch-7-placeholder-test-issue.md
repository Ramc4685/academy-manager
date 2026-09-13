# batch-7: dead outbox methods cleanup

## What changed
- Fixes #536 — removed the dead, unsafe `MongoOutbox.pull_unprocessed`/`mark_processed` methods (and the matching `Outbox` protocol declarations) from `backend/v2/shared/events/outbox.py`. `pull_unprocessed` only filtered on the legacy `processed` flag and `mark_processed` never set `status`, so any future caller replaying events through them would re-deliver events the dispatcher's claim path already owns via `status` (pending/retry). Confirmed no production caller exists; `dispatcher.py` operates on the collection directly via `status`.
- Removed the two matching dead methods from `FakeOutbox` and `_AdminFakeOutbox` test fakes in `backend/v2/tests/interface/conftest.py` that mirrored the protocol, and dropped the now-unused `Any` import.

## Deploy notes
None. No schema, migration, or config changes; this is a pure code-removal cleanup of unused/dead methods.

## Risk / rollback
Low risk — the removed methods had no production callers (verified by search) and were never exercised outside the test fakes that mirrored them. Full test suite (5115 tests), ruff, import-linter, and mypy all pass. Rollback: revert this PR.

PR: #0
