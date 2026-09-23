# Index drift audit (scheduled)

`.github/workflows/index-drift-audit.yml` runs
`backend/scripts/index_drift_audit.py` every Monday at 06:00 UTC and on demand
(Actions > Index Drift Audit > Run workflow). It compares the indexes that
exist in production with the indexes the migrations in
`backend/v2/migrations` create. It only reads data and never changes the
database.

## How it runs

1. **dump**: connects with `PROD_MONGO_READONLY_URI`, runs
   `index_drift_audit.py --dump > live.json`, and uploads `live.json` as the
   `index-drift-live` artifact (kept 7 days).
2. **check**: downloads `live.json`, installs `backend/requirements-dev.txt`
   (it needs `mongomock`), and runs `index_drift_audit.py --check live.json`.
   The job fails when the script exits non-zero. The JSON report appears in the
   job log and in the run summary.

## The secret (owner only)

| Name | Kind | Value |
| --- | --- | --- |
| `PROD_MONGO_READONLY_URI` | Actions **secret** | Connection string for a dedicated audit user |
| `PROD_MONGO_DB_NAME` | Actions **variable** (optional) | Database name; defaults to `academy_manager` (same as `backend/fly.toml`) |

- The Mongo user must have **only the `read` role** on the production
  database. Do not give it `readWrite`, `dbAdmin` or any cluster role. The
  script needs only `listCollections` and `listIndexes`, and `read` covers
  both.
- The URI reaches the script only through the `MONGO_URL` environment
  variable. It is never passed as an argument or echoed, and GitHub masks
  the secret value in logs.
- If the secret is not set, the workflow still passes. The run summary says
  `skipped: PROD_MONGO_READONLY_URI not set` and the check job is skipped.
- Atlas network access must allow GitHub-hosted runners. If that is not
  acceptable, leave the secret unset and run the two commands from the script
  docstring by hand.
- The repo is public, so any signed-in GitHub user can see the run summary
  and download the artifact. Both contain only collection names, index names,
  keys and partial filters. They never contain documents or credentials.

## Reading a failure

The report has four lists. The first three can fail the run.

- **missing**: a migration creates this index but the live collection does
  not have it. Usually a migration was never applied in production. Apply it
  through the production migrate job (`docs/runbooks/migrations-rollout.md`).
  Never create the index by hand.
- **changed**: an index with the same name exists but its key, `unique` flag
  or partial filter is different. Compare the migration with the dump in the
  artifact. Fix it with a new migration that drops and rebuilds the index.
- **unexpected unique**: a unique index that no migration creates and that
  `KNOWN_LEGACY_UNIQUE` in the script does not explain. These can block writes,
  as happened in #835. The owner decides whether to drop it, through a
  migration, or to accept it. To accept it, add an entry to
  `KNOWN_LEGACY_UNIQUE` that says why it is harmless.
- Unexpected **non-unique** indexes are listed but never fail the run.

A collection that Mongo has not created yet is reported but does not fail the
run.

If the dump job fails before the check runs, it is a connection or auth
problem (wrong URI, network allow-list, or the user lacks `read`). The job log
shows the driver error. The URI itself is masked.
