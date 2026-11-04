# Fix missing release-note title for PR #800

## What changed

- Adds the missing H1 title to `docs/release-notes/2026-09-13-batch-6-frontend-fixes.md` (PR #800). Production run 34800700535 deployed backend, frontend and smoke successfully, then failed only at Publish Production Release with `invalid release-note title` for that file. Docs only.

## Deploy notes

- None. Re-running the publish step, or the next main run, publishes the release.

## Risk / rollback

- None: a docs file. Rollback is a revert.

PR: #822
