# e2e-per-worktree-port

PR: #582

## What changed
Every git worktree defaulted the local e2e stack to port 3001, making
the pre-push e2e gate a one-worktree-at-a-time resource: with `CI=true`
(server reuse disabled) the webServer could not bind while another
worktree's `next dev` held 3001 and the whole suite failed as a mass
fake regression, while a plain local `pnpm e2e` silently attached to the
OTHER worktree's server and green-lit code that never ran (`#522`). The
default port is now derived per worktree by hashing the repo root path
into 3001-3999, implemented twice in lockstep —
`frontend/lib/worktree-port.ts` (used by `playwright.config.ts`) and
`scripts/dev/lib/worktree-port.sh` (used by `local_test_stack.sh`) —
with a node test asserting byte-for-byte agreement between the two.
`pre-push-checks.sh` additionally pre-flights the resolved port with
`lsof` and names the port-contention cause instead of emitting a wall of
Playwright errors.

## Deploy notes
Developer-tooling only; no runtime code paths change. Overrides still
win everywhere (`PLAYWRIGHT_PORT` for Playwright, `FRONTEND_PORT` for
`local_test_stack.sh`), and under CI `local_test_stack.sh` keeps 3001
because the real-auth workflow pins
`LOCAL_AUTH_BASE_URL: http://localhost:3001`. Local muscle memory for
"frontend is on 3001" is stale: run `scripts/local_test_stack.sh status`
to see this worktree's port.

## Risk / rollback
The derivation is deterministic, so a given worktree always gets the
same port; two paths can still hash to the same bucket (999 slots), in
which case the new pre-push pre-flight reports the collision explicitly
and either worktree can set an override. GitHub Actions e2e derives a
port too, but baseURL and webServer share the value so the absolute port
is irrelevant there. Rollback is a plain revert — no data, schema, or
deploy-order concerns.
