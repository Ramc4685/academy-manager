# Scheduled index drift audit workflow

## What changed

- Added `.github/workflows/index-drift-audit.yml`. It runs `backend/scripts/index_drift_audit.py` every Monday at 06:00 UTC, and on demand from Actions. It compares production's live Mongo indexes with the ones the migrations create. It only reads the database and fails on missing indexes, changed indexes, or unexpected unique indexes.
- The run is gated on the `PROD_MONGO_READONLY_URI` secret. Without it, the run finishes green and the summary says "skipped". The live index dump artifact is kept for 1 day, because the repo is public.
- Added the runbook `docs/runbooks/index-drift-audit.md`.

## Deploy notes

- No migrations. No app deploy is needed; this is CI only.
- Owner steps (optional; the workflow is a no-op until they are done):
  1. Create a Mongo user with only the `read` role on the production database.
  2. Add its connection string as the Actions secret `PROD_MONGO_READONLY_URI`. Optionally, set the Actions variable `PROD_MONGO_DB_NAME` (the default is `academy_manager`).
  3. Allow GitHub-hosted runners in Atlas network access. If that is not acceptable, leave the secret unset.

## Risk / rollback

- Low risk. The workflow never writes to the database and changes no application code. The run summary and artifact are public, but they contain only index metadata, never documents or credentials.
- Rollback: delete the workflow file, or remove the `PROD_MONGO_READONLY_URI` secret to make it a no-op.

PR: #944
