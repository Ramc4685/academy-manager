## What changed

- Fixes #607 — broke the circular import between `backend.v2.shared.auth` and `backend.v2.shared.http` that made isolated test invocation of either module fail.

## Deploy notes

None. This is a module-structure fix only (import ordering); no migrations, no config, no runtime behavior change.

## Risk / rollback

Low risk: the change only reorganizes imports between two shared modules and is covered by the full `v2` test suite (5114 tests) plus `lint-imports` contract checks, both of which pass. Rollback is a straight revert of this PR.

PR: #804
