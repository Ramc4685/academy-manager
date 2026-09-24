# Mongo backup/restore script, runbook and weekly scratch-DB restore drill (D6)

PR: #TBD

## What changed

- **Script.** `backend/scripts/backup_restore.py` with four subcommands: `backup` (`mongodump --archive --gzip` to `<db>-<UTC stamp>.archive.gz` plus a sidecar manifest of per-collection document counts, index names and the archive SHA-256), `prune` (30-day retention by the stamp in the file name, dry run unless `--apply`), `restore` (into a different, empty database via `--nsFrom/--nsTo`; checks the manifest checksum first) and `verify` (collections, counts and index names vs the manifest; exit 1 on mismatch).
- **Safety.** URIs are read only from env vars named on the command line, passed to the Mongo tools through a temporary 0600 `--config` file, and redacted from all output. `restore` refuses non-localhost targets by default (`--allow-remote-target` for an owned scratch cluster), and refuses `PROD_MONGO_*` targets, hosts of any `PROD_MONGO_*` var or `BACKUP_RESTORE_DENY_HOSTS`, and same-name restores unless `--i-know-this-is-prod`.
- **CI drill.** `.github/workflows/restore-drill.yml`: weekly, on demand and on PRs touching the script. Seeds a small tenant-scoped database (every migration plus synthetic rows) on a `mongo:8.0` service container, runs backup, restore into a second database name and verify, and checks that a remote target is refused without leaking the password. No secrets.
- **Tests.** Unit tests for prune date math, the restore guard, manifest diffing and URI redaction; a real-mongod round-trip contract test (skipped where the Mongo tools are not installed; the drill workflow installs them).
- **Docs.** `docs/runbooks/backup-restore.md` (schedule, 30-day retention, off-site storage recommendation, drill steps, owner-only restore-to-production procedure); `DEPLOYMENT.md` points to it.

## Deploy notes

- No migration, no runtime code change, no env var or secret. Nothing runs against production.
- Production backups remain an owner decision (schedule and off-site storage); the runbook lists the recommendation.

## Risk / rollback

- None for the running app: the script is an operator tool and the new workflow only touches its own service container.
- Rollback: revert the PR.
