# migrate-job-fly-builder

PR: #922

## What changed

- The `migrate-production` job introduced in #920 now builds the backend image with the Fly remote builder (`--depot=false`) instead of Depot, and retries the dry-run machine launch four times before failing.
- Why: the first supervised run (2026-09-23) pushed a Depot-built image whose manifest the VM host could not fetch, so the dry run failed with "failed to get manifest ... not found" and the backend deploy was skipped. Fly-builder images are pullable by both `flyctl machine run` and `flyctl deploy --image`.
- `docs/runbooks/migrations-rollout.md` records what was seen and why.

## Deploy notes

- This is still the first supervised run of the migrate job. Approve at the Production Approval gate and watch Migrate Production: expected `pending_before count=0`, `exit_code=0`, then Deploy Backend runs the release command with `applied count=0`.
- The frontend is currently one release ahead of the backend (the previous run deployed the frontend before the migrate job failed). This run brings the backend level; until then the Staff list still shows parent accounts under "All staff".
- After a green run and smoke: `fly secrets unset V2_RUN_MIGRATIONS_ON_BOOT -a courtmastr-academy-api`, outside class hours.

## Risk / rollback

Low. Workflow-only change plus a runbook note; no application code. If the Fly builder is unavailable the build step fails before anything touches production and the deploy is skipped again. Rollback is reverting this commit; the previous image label remains deployable with `flyctl deploy --image`.
