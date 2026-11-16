# faster-local-gate

PR: #1177

## What changed
The local pre-push hook no longer runs the full backend suite (CI still does, as the required merge check); its high-risk tier now runs whole-tree ruff, lint-imports and mypy instead, matches risk by real path prefixes, and caps pytest at 4 workers. The Release Notes Gate accepts a complete note added in the PR with `PR: TBD`, so authors no longer need an extra push to stamp the number.

## Deploy notes
None. Developer tooling and docs only; no runtime code, migration or env var changes.

## Risk / rollback
A full-suite failure now shows up in CI about 7 minutes after the push instead of blocking it locally; `PREPUSH_FULL=1` restores the old local behavior per push. Roll back by reverting the merge commit.
