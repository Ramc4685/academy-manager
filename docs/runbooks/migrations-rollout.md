# Migrations rollout (production)

How v2 migrations reach production, what the owner approves, and what to do
when a run fails. Applies from the PR that added the `migrate-production`
job to `.github/workflows/production.yml`.

## Shape

1. **`migrate-production` job** (after the Production Approval gate, before
   `deploy-backend`):
   - builds the backend image once with `flyctl deploy --build-only --push`
     and labels it `migrate-<sha12>`;
   - runs `python -m backend.v2.migrations --dry-run` on a throwaway machine
     of the app using that image (the machine gets the app's secrets, so
     `MONGO_URL` is available; `DB_NAME` is passed from `fly.toml`);
   - fails when the dry run exits non-zero or its exit code cannot be read
     (the step parses flyctl's text output, so a flyctl format change fails
     closed rather than letting an untested image through).
2. **`deploy-backend`** deploys the **same image** with `flyctl deploy
   --image ...`. Fly runs `backend/fly.toml`'s
   `[deploy] release_command = "python -m backend.v2.migrations"` on that
   image first and aborts the deploy when it exits non-zero, leaving the old
   machine serving. This is the apply step.
3. Boot no longer applies migrations: `V2_RUN_MIGRATIONS_ON_BOOT = "false"`
   in `fly.toml`.

Why the apply is a `release_command` and not a `flyctl machine run` in the
job: `flyctl machine run` only waits for the machine to start and never
reports the process exit code, while the release command is the Fly
mechanism that does (and that aborts the deploy on failure). The job still
gives an explicit, readable dry run on the exact image before anything
changes.

## First supervised run (owner checklist)

1. Wait for the run's **Production Approval** gate. Before approving, open
   the PR list for the deploy and note which migrations (if any) it adds.
2. Approve. Watch **Migrate Production**:
   - "Build and push backend image" prints a `::notice::` with the image
     ref, `registry.fly.io/courtmastr-academy-api:migrate-<sha12>`. Copy it;
     it is also the rollback target for the *previous* deploy next time.
   - "Dry-run pending migrations on the new image" prints the machine id,
     then the CLI output, then the machine status. Expected today (0190 is
     the latest and has been applied by hand):

     ```
     migrations event=start db='academy_manager' dry_run=True
     migrations event=pending_before count=0 versions=[]
     migrations event=dry_run applied=[] note='nothing written'
     ```

     followed by an `exit` event with `exit_code=0` in the status table and
     the line `Migrations dry run passed on <image>`. A deploy that carries
     new migrations lists them in `versions=[...]` in numeric order; that
     list should match the PRs you noted in step 1 and nothing else.
3. Watch **Deploy Backend**. Fly prints `Running <app> release_command:
   python -m backend.v2.migrations` and streams the same event lines, now
   with `event=applied count=N versions=[...]` and `event=pending_after
   count=0 versions=[]`. Then the machine update proceeds as before.
4. Wait for **Production Smoke** to pass.
5. Afterwards, remove the Fly secret that duplicates the `fly.toml` value so
   the file is the single source of truth:
   `fly secrets unset V2_RUN_MIGRATIONS_ON_BOOT -a courtmastr-academy-api`
   (this restarts the machine once; do it right after a green smoke, not
   during class hours). Then delete the "remove the secret" note from
   `fly.toml`.

## What failure looks like

- **Dry run fails** (`event=failed`, `event=registry_read_failed`, or
  `event=startup_failed`, non-zero `exit_code`): the job goes red with
  `Migrations dry run exited N; deploy-backend is skipped`. Nothing was
  written. `deploy-backend` and `smoke` are skipped; production is
  unchanged. Fix forward on `main`.
- **Apply fails** in the release command: Fly prints `Error
  release_command failed running on machine <id> with exit code N` and the
  deploy aborts; the old machine keeps serving. The log shows which
  migration raised (`Applying migration NNNN_...` followed by the
  traceback) and `event=pending_after` lists what is still outstanding.
  Migrations are applied in order and each is recorded only after its
  `up()` succeeds, so the earlier ones in the same deploy stay applied and
  the failing one plus everything after it stays pending. Fix forward with a
  new migration or a corrected one (never edit an applied one).
- **Timeout** (`event=timeout`, exit code 2): the CLI waited 20 minutes
  (`--timeout-seconds`) without finishing. The usual cause is a **stuck
  migrations lease**: a previous run crashed without releasing
  `scheduler_leases` `_id: v2_boot_migrations`, whose TTL is 15 minutes.
  The log shows `Migrations lease held by another machine; waiting 2.0s`
  repeating. Either wait for the TTL to lapse and re-run the workflow, or
  inspect the lease document (`locked_until`, `lock_owner`) and, if the
  owner machine is gone, set `locked_until` to now. A backfill that is
  genuinely slow needs a higher `--timeout-seconds` in `fly.toml` **and** a
  higher `--release-command-timeout` in `deploy-backend`.

## Rollback

Migrations are additive (indexes, validators, backfills) and idempotent; a
rollback is a code rollback, not a migration rollback:

```
cd backend   # fly.toml must be the config in use
flyctl deploy --image registry.fly.io/courtmastr-academy-api:migrate-<previous sha12> \
  --ha=false -a courtmastr-academy-api
```

The image label is `migrate-` plus the first 12 characters of the commit SHA
that was deployed; `git log --first-parent main` gives the previous one.

The release command runs again on that image and finds nothing pending
(older image, all its migrations recorded), so it is a no-op. If the newer
code's migration must not stay in place, write a new migration that undoes
it and ship it forward.

## Local use

Run from the **repo root** (the module path is `backend.v2.migrations`, so
it does not resolve from inside `backend/`):

```
backend/.venv/bin/python -m backend.v2.migrations --dry-run   # list pending
backend/.venv/bin/python -m backend.v2.migrations             # apply
backend/.venv/bin/python -m backend.v2.migrations --timeout-seconds 60
```

Reads `MONGO_URL` / `DB_NAME` (or `V2_MONGO_URL` / `V2_MONGO_DB`) through
`get_settings()` exactly like the app; unset, it targets
`mongodb://localhost:27017` / `academy_manager`. `backend/.env` is not read
from the repo root, so export what you need. Exit codes: 0 ok, 1 a migration
or the registry read failed, 2 timeout.
