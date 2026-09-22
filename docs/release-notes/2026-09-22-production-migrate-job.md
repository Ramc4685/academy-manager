# production-migrate-job

PR: #920

## What changed

- Production migrations are applied by the deploy pipeline, not on boot. A new **Migrate Production** job in `.github/workflows/production.yml` runs after the Production Approval gate: it builds and pushes the backend image once (`registry.fly.io/courtmastr-academy-api:migrate-<sha12>`), runs `python -m backend.v2.migrations --dry-run` on a throwaway machine using that exact image, and fails the workflow (skipping Deploy Backend) when the dry run exits non-zero or its exit code cannot be read. The throwaway machine has a deterministic name (`migrate-dry-run-<run id>-<attempt>`); the cleanup trap is armed before it is created and finds it by name through `flyctl machine list --json` when the id cannot be parsed from flyctl's text output, so a parse failure cannot leak a machine. The exit code is read from the same JSON (`exit` event), with the text status table as the fallback.
- **Deploy Backend** deploys the same image with `flyctl deploy --image <ref>`. The apply is `backend/fly.toml`'s new `[deploy] release_command = "python -m backend.v2.migrations"`, which Fly runs on the new image before any app machine is replaced and which aborts the deploy on non-zero exit, leaving the old machine serving.
- `fly.toml` now sets `V2_RUN_MIGRATIONS_ON_BOOT = "false"`; the Docker image gained a `python -m backend.v2.migrations` CLI (`backend/v2/migrations/cli.py`, `__main__.py`) with `--dry-run`, an overall timeout, and non-zero exit codes on failure (1) and timeout (2). Runbook: `docs/runbooks/migrations-rollout.md`.

## Deploy notes

- **The first run of this workflow must be supervised by the owner at the Production Approval gate.** Approve, then watch Migrate Production and Deploy Backend per `docs/runbooks/migrations-rollout.md`.
- Expected dry-run output today (migrations 0173-0190 were applied by hand, nothing is pending):
  ```
  migrations event=start db='academy_manager' dry_run=True
  migrations event=pending_before count=0 versions=[]
  migrations event=dry_run applied=[] note='nothing written'
  ```
  followed by `exit_code=0` in the machine status and `Migrations dry run passed on <image>`. Deploy Backend then prints the release command running with `event=applied count=0` and `event=pending_after count=0`.
- No new migration ships in this PR. `deploy-backend`'s Fly deploy now takes a few minutes longer (release command machine start + no-op run).
- **After the first green run and smoke**, remove the Fly secret that duplicates the `fly.toml` value so the file is the single source of truth: `fly secrets unset V2_RUN_MIGRATIONS_ON_BOOT -a courtmastr-academy-api` (restarts the machine once; do it outside class hours), then delete the "remove the secret" note from `fly.toml`.

## Risk / rollback

- Medium: this is the first change to how production migrations run since boot-time application was disabled by the Fly secret. The dry run touches nothing (registry read only, no lease); the apply reuses the existing lease + registry runner unchanged. A failed dry run leaves production untouched; a failed apply aborts the Fly deploy with the previous machine still serving.
- A stuck migrations lease (15 min TTL) shows as `Migrations lease held by another machine; waiting 2.0s` repeating and a timeout (exit 2) after 20 min; the runbook covers waiting it out or clearing `scheduler_leases` `_id: v2_boot_migrations`.
- Rollback of the code: from `backend/`, `flyctl deploy --image registry.fly.io/courtmastr-academy-api:migrate-<previous sha12> --ha=false -a courtmastr-academy-api` (the release command re-runs and finds nothing pending). Rollback of the mechanism: revert this PR's merge commit; boot stays migration-free until the Fly secret is removed and `fly.toml` set back to `"true"`.
