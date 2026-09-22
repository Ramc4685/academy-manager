# fix-ci-e2e-webserver-hang

PR: #TBD

## What changed

- Every CI run since 2026-09-21 21:51Z has failed the same way: the Frontend E2E Chromium job runs all 385 tests green, never prints its summary, and is cancelled at the 12-minute job timeout, which fails the CI Gate on every branch. No code change caused it. The only difference from the last green run is pnpm: CI installs the newest 11.x, and 11.27.1 (published 2026-09-20) changed `pnpm run` so that, with no controlling terminal, the script is started in its own process group. Playwright starts the e2e dev server with `pnpm dev`, ends the run by killing the server's process group, and then waits for the server's output pipe to close. With pnpm 11.27.1 the `next dev` process sits in a different group, survives the kill, keeps the pipe open, and Playwright waits forever. Reproduced locally: the same spec exits in 7 seconds under pnpm 11.27.0 and hangs under 11.27.1, leaving `next dev` orphaned.
- Playwright now starts `next dev` directly instead of through `pnpm dev`, so the server is in the group Playwright kills regardless of pnpm's behaviour. The flags are the same as the `dev` script's. `pnpm dev` itself is unchanged for people.

## Deploy notes

None. CI and local e2e only; no application code, migrations or env vars.

## Risk / rollback

Low. The e2e dev server is started with the same `next` binary and flags as before, only without pnpm in between. Verified locally under pnpm 11.27.1 (the version that hangs): the run exits cleanly and leaves no dev-server process behind. If anything regresses, revert this PR's merge commit; pinning pnpm to 11.27.0 in the workflow is the alternative stopgap.
