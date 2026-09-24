# Mongo backup and restore

Tool: `backend/scripts/backup_restore.py` (roadmap D6). It wraps the
`mongodump` / `mongorestore` steps from `DEPLOYMENT.md` ("Database Backups")
and the one-off drill in `blno-launch-ops-proof-2026-06-17.md`.

What the repository proves automatically: the `Restore Drill` workflow
(`.github/workflows/restore-drill.yml`) runs every Monday, on demand, and on PRs
that touch the script. It seeds a small tenant-scoped database on a throwaway
`mongo:8.0` container, backs it up, restores it under a different database name,
verifies counts and index names, and checks that a non-localhost target is
refused. It uses no secrets and never touches production.

What it does **not** do: back up production. There is no scheduled job against
the production database in this repository, and choosing or paying for
off-site storage is an owner decision (see "Off-site storage" below).

## Prerequisites

- MongoDB Database Tools (`mongodump`, `mongorestore`) 100.x on `PATH`.
- Python with `pymongo` (the backend virtualenv has it).
- Connection strings in **environment variables**. The script only takes the
  *name* of the variable (`--uri-env`, `--target-uri-env`), hands the URI to
  the Mongo tools through a temporary 0600 `--config` file (so it never shows
  in `ps`), and redacts credentials from every line it prints.

## Commands

```bash
# Backup: <out-dir>/<db>-<UTC stamp>.archive.gz + <archive>.manifest.json
python backend/scripts/backup_restore.py backup \
  --uri-env MONGO_URL --db "$DB_NAME" --out-dir /secure/backups

# Retention: lists archives older than 30 days; add --apply to delete them
python backend/scripts/backup_restore.py prune --out-dir /secure/backups --keep-days 30

# Restore into a DIFFERENT, EMPTY database on a scratch server
python backend/scripts/backup_restore.py restore \
  --archive /secure/backups/<db>-<stamp>.archive.gz \
  --target-uri-env SCRATCH_MONGO_URL \
  --nsFrom "$DB_NAME" --nsTo "${DB_NAME}_restore_$(date -u +%Y%m%d)"

# Verify: collection set, document counts and index names vs the manifest
python backend/scripts/backup_restore.py verify \
  --manifest /secure/backups/<db>-<stamp>.archive.gz.manifest.json \
  --target-uri-env SCRATCH_MONGO_URL --db "${DB_NAME}_restore_<yyyymmdd>"
```

Exit codes: `0` ok, `1` verification mismatch or tool failure, `2` refused or
bad input.

### The manifest

Written next to the archive at backup time: database name, UTC timestamp,
redacted source host, the archive's SHA-256 and size, and for every real
collection its document count and index names. Counts are read from the source
**before** the dump starts, so on a live database a later `verify` can differ
by the writes that landed during the dump. On a quiet database (the drill, a
maintenance window) any difference is a real failure. `restore` refuses an
archive whose SHA-256 no longer matches its manifest.

### Restore guard

`restore` refuses (exit 2) unless the target is safe:

| Condition | Default | Override |
| --- | --- | --- |
| Target host is not localhost (`localhost`, `127.0.0.1`, `::1`, `*.localhost`) | refused | `--allow-remote-target` (a scratch cluster you own) |
| Target env var is named `PROD_MONGO_*` | refused | `--i-know-this-is-prod` (owner-only) |
| Target host equals the host of any `PROD_MONGO_*` env var, or is listed in `BACKUP_RESTORE_DENY_HOSTS` (comma-separated) | refused, even with `--allow-remote-target` | `--i-know-this-is-prod` (owner-only) |
| `--nsTo` equals `--nsFrom` | refused | `--i-know-this-is-prod` (owner-only) |
| Target database already holds collections | refused | none: drop it or pick a new name |

Keep the production URI in a `PROD_MONGO_URL` variable in any shell that also
holds scratch credentials, so the host denylist is populated automatically.

## Schedule and retention

- **Production backups:** daily, off-peak (the recommendation; not automated
  here). If the Mongo provider offers managed continuous backups, use those as
  the primary and treat this script as the portable, provider-independent copy.
- **Retention:** 30 days of daily archives (`prune --keep-days 30 --apply`
  after each backup). `prune` reads the date from the file name, not the file
  time, so copying archives between machines does not reset their clock. It
  only ever touches files named `<db>-<YYYYMMDDTHHMMSSZ>.archive.gz` and their
  manifests.
- **Drill:** the CI drill runs weekly. A drill from a real production backup
  into a scratch server (procedure below) at least quarterly and before any
  risky migration.

## Off-site storage (recommendation, owner decision)

Archives hold every tenant's personal data. Keep them:

- off the app host, in a different provider/region from the database;
- encrypted at rest (bucket-level encryption at minimum; client-side
  encryption such as `age` or `gpg` before upload is better);
- in a bucket with object versioning or object lock and a lifecycle rule that
  matches the 30-day retention;
- readable only by the owner and the backup job's own credential.

Choosing and paying for the storage is out of scope for this repository.

## Drill from a real backup (quarterly)

1. Start a local scratch server: `docker run --rm -d -p 27018:27017 --name restore-drill mongo:8.0`.
2. `export SCRATCH_MONGO_URL=mongodb://localhost:27018`.
3. Copy the chosen archive **and its manifest** to the machine.
4. Run `restore` into `<db>_restore_<yyyymmdd>` (command above).
5. Run `verify`. Exit 0 is the pass. Record the date, archive name,
   collection count, document total and the verify output in the ops log.
6. Spot-check one tenant: pick one `academy_id` and compare a handful of
   collections' counts for it with production (read-only queries).
7. Tear down: `docker stop restore-drill`, then delete the local archive copy.

## Restore to production (OWNER-ONLY)

Only the owner runs this, only during a declared incident, and never from CI or
an agent session.

1. Declare the incident (`docs/incidents/README.md`) and put the app in
   maintenance: scale the Fly API to zero or block writes, so nothing writes
   while the restore runs.
2. Take a fresh `backup` of the current production database first, even if it
   is damaged. That is the undo.
3. Restore the chosen archive into a **new** database name on the production
   cluster and `verify` it against its manifest:

   ```bash
   python backend/scripts/backup_restore.py restore \
     --archive <archive> --target-uri-env PROD_MONGO_URL \
     --nsFrom <db> --nsTo <db>_restored_<yyyymmdd> --i-know-this-is-prod
   python backend/scripts/backup_restore.py verify \
     --manifest <archive>.manifest.json --target-uri-env PROD_MONGO_URL \
     --db <db>_restored_<yyyymmdd>
   ```

4. Point the app at the restored database (the `DB_NAME` / `V2_MONGO_DB` Fly
   secrets) rather than overwriting the original. The owner changes secrets.
5. Run the migrations dry run and the index drift audit
   (`backend/scripts/index_drift_audit.py`) against the restored database,
   then bring the API back and run the production smoke checks.
6. Keep the damaged database until the incident is closed, then drop it.

Writes that happened after the backup's timestamp are lost unless they are
replayed from Stripe webhooks and logs; list them in the incident record.
