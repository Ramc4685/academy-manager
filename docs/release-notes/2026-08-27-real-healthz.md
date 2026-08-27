# real-healthz

PR: #TBD

## What changed
`/api/v2/healthz` now reports real liveness instead of returning
`{"status":"ok"}` unconditionally. It pings Mongo (2s timeout, inside Fly's 5s
check budget), asserts the APScheduler instance is running, and asserts the
event dispatcher's poll loop is alive; any of those failing returns 503 so Fly
restarts the machine. The body also carries per-job heartbeat ages from
`ops_job_runs` for an external uptime monitor — reported only, never used to
fail the check.

## Deploy notes
None. No migrations, no env vars, no Fly config change — the existing
`[[http_service.checks]]` block already polls this path every 30s.

## Risk / rollback
The endpoint can now return 503, which makes Fly restart the machine. That is
the point, but it is also the risk: a false negative costs a restart. Two
guards keep it narrow — only faults a restart can actually fix return 503 (a
stale job heartbeat does not), and a component that was never wired counts as
healthy rather than failing, so a differently-assembled app cannot boot-loop.
Uvicorn does not serve requests until lifespan startup completes, so the
production app always has all three components wired before the first check.

The healthy response still contains `"status":"ok"` for
`scripts/smoke/production_smoke.sh`. Nested check results deliberately use
`ok: true` rather than a nested `status` key, so a degraded body cannot
satisfy the smoke script's substring grep; a unit test pins that.

Revert the PR to return to the unconditional 200.
