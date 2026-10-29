# security-alert-cleanup-codeql

PR: #1089

## What changed
Fixes the real CodeQL clear-text-logging alerts. `backend/scripts/seed_local.py` now names the `SEED_*_PASSWORD` environment variables instead of printing their values, and `scripts/dev/seed_blno_staging.py` points at its 0600 creds file instead of printing staging passwords. The worktree-port node test runs its bash parity check through `bash -s` with stdin instead of `bash -c`. The remaining CodeQL alerts were reviewed and are false positives (already-redacted output, non-secret ids, test assertions); they are dismissed with reasons.

## Deploy notes
No runtime change: developer and ops scripts plus one test. No migrations, no environment changes.

## Risk / rollback
Low. Anyone who read seed passwords from script output now reads them from the env vars or the creds file. Roll back by reverting the PR.
