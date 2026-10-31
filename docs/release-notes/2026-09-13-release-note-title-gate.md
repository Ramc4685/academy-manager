# Release-note title validated in the PR gate

## What changed

- `scripts/dev/release_notes_check.py` now reports a missing or over-long H1 title, the same rule the production publisher already enforces, so an untitled note fails the PR gate instead of the post-deploy Publish Production Release step. Adds titles to the three batch-7 notes that lacked one.

## Deploy notes

- None. Re-running the publish step, or the next main run, publishes the pending release.

## Risk / rollback

- Low: a stricter docs check. If it rejects a legitimate note, add a `# Title` first line. Rollback is a revert.

PR: #824
