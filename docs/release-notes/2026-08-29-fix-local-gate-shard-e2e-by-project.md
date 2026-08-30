# local-gate-shard-e2e-by-project

PR: #496

## What changed
The local pre-push gate now runs one Playwright invocation per project
instead of one run covering all ~500 e2e tests. `CI=true` disables
`reuseExistingServer`, so each shard starts and tears down its own `next dev`
server, mirroring CI's one-job-per-project matrix in `production.yml`. A new
`scripts/dev/lib/e2e-projects.sh` reads the project list out of
`playwright.config.ts` so a project added to the config (and its CI job) is
never silently skipped locally. The committed hook test suite grows 5 cases
to 29.

## Deploy notes
None. Local developer tooling and its tests only; no application code and no
change to what CI runs.

## Risk / rollback
Wall time is roughly unchanged (the same tests run, split across three
servers) but the gate now pays three dev-server startups instead of one, so a
cold run costs a little more. If sharding misbehaves, revert to the single
`env CI=true pnpm e2e` line in `scripts/dev/pre-push-checks.sh`; nothing else
depends on the new helper. The parser assumes project entries are the only
`name:` keys in `playwright.config.ts` — a test asserts the real config still
yields exactly the three projects CI runs, so a config restructure fails
loudly in CI rather than quietly shrinking local coverage.
