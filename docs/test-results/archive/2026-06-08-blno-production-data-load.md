# BLNO production data load

## Current State

Status: active

## Problem

Load the reviewed current BLNO Mongo data bundle into production after backup, dry-run, and explicit apply confirmation.

## Changed Files

- None recorded yet.

## Log

- 2026-06-08T16:32:39 main/NA: Task ledger created.
- 2026-06-08T16:32:46 main/blocked: Production data load requested. Environment check found PROD_MONGO_URL is not set in the shell; mongodump and backend/.venv/bin/python are available. No production backup, dry-run, or apply was run.
- 2026-06-08T16:33:31 main/working: User confirmed CLI access to production MongoDB. Attempting to discover production Mongo URI through CLI without printing secrets, then run backup and dry-run.
- 2026-06-08T16:35:10 main/working: Retrieved production Mongo URI metadata without printing the secret. Starting backup for academy_manager.
- 2026-06-08T16:37:55 main/working: Remote production import applied successfully. Running post-import count checks next.
- 2026-06-08T16:38:57 main/working: Post-import verification found all bundle identities, but production still has extra pre-existing academy-scoped BLNO documents under acad_blno_badminton. Cleanup would require explicit destructive MongoDB approval.
- 2026-06-08T16:49:28 main/done: Deleted stale BLNO bundle-owned production records, reran the reviewed import bundle, verified counts match, and confirmed production health.
## Verification

- No verification recorded yet.
- 2026-06-08T16:32:46: Blocked before production access: PROD_MONGO_URL missing. No Mongo write attempted.
- 2026-06-08T16:37:28: Created and downloaded production BSON JSONL backup: .local/prod-backups/academy-manager-pre-blno-2026-06-08-163719.jsonl.gz
- 2026-06-08T16:37:39: Remote production dry-run completed for /tmp/blno_mongo_import_bundle.json.
- 2026-06-08T16:37:55: Remote production apply completed using /app/backend/scripts/apply_blno_mongo.py and confirm-production acad_blno_badminton.
- 2026-06-08T16:38:40: Post-import identity verification succeeded: every document identity in the BLNO bundle was found in production.
- 2026-06-08T16:38:41: Production health smoke succeeded: GET https://api.academy.courtmastr.com/api/v2/healthz returned 2xx.
- 2026-06-08T16:38:57: Post-import counts show additive load: matched bundle docs found, missing={}, but academy-scoped counts exceed bundle counts for memberships, sessions, students, enrollments, payments, attendance, and related collections.
- 2026-06-08T16:48:03: Created and downloaded pre-cleanup production backup: .local/prod-backups/academy-manager-pre-blno-cleanup-2026-06-08-164756.jsonl.gz
- 2026-06-08T16:48:19: Stale BLNO cleanup dry-run completed against production; cleanup is limited to bundle-owned collections for acad_blno_badminton.
- 2026-06-08T16:48:44: Applied stale BLNO cleanup for bundle-owned acad_blno_badminton collections.
- 2026-06-08T16:48:57: Re-ran BLNO production import after stale-record cleanup.
- 2026-06-08T16:49:20: Post-cleanup verification succeeded: bundle identities found after cleanup and rerun.
- 2026-06-08T16:49:20: Post-cleanup production health smoke succeeded: GET /api/v2/healthz returned 2xx.
## Reusable Lessons

- None recorded yet.
