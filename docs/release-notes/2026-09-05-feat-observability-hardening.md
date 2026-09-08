# feat-observability-hardening

PR: #661

## What changed
Implements the 2026-09-05 logging/observability audit.

- `observability/logging.py`: `configure_logging()` no longer re-enables
  `uvicorn.access` (it undid `--no-access-log`, logging every request twice and
  the 30 s health probe at INFO); APScheduler, Stripe, pymongo, httpx/httpcore
  and urllib3 are held at WARNING unless `LOG_LEVEL=DEBUG`.
- `main.py`: the nine lease wrappers collapse into `_run_leased_job`, which
  writes an `ops_job_runs` heartbeat for every job (only the invoice job did
  before), wraps allowlisted jobs in Sentry Crons check-ins
  (`V2_SENTRY_CRON_JOBS`, default `generate_monthly_invoices`), and seeds
  heartbeats at boot. The daily ops digest gains a stale-jobs section that flips
  the subject to "attention needed"; `/api/v2/healthz` reports `stale` per job
  (informational, never a 503).
- `.github/workflows/production.yml`: backend deploy passes
  `SENTRY_RELEASE=courtmastr-fastapi@<sha>`; new `sentry-release` job after
  smoke, skipped until `SENTRY_AUTH_TOKEN` exists; frontend build receives
  `NEXT_PUBLIC_SENTRY_DSN` / `NEXT_PUBLIC_SENTRY_RELEASE`.
- Frontend: BFF proxy mints and echoes `X-Request-ID`; `ApiError.requestId`;
  error toasts show `Reference: xxxxxxxx`; `@sentry/browser` 10.73.0 loaded
  only when `NEXT_PUBLIC_SENTRY_DSN` is set, with URL/breadcrumb query
  scrubbing; Web Vitals go to Sentry instead of the never-installed PostHog;
  CSP `connect-src` allows the Sentry ingest host.
- Migration `0166_event_audit_ttl_400_days`: `event_audit` TTL 90 → 400 days.
- `docs/observability.md` rewritten; `scripts/ops/sentry_alerts.sh` (dry-run
  by default) and `scripts/ops/uptime.md` added; `DEPLOYMENT.md` updated.

## Deploy notes
Migration 0166 applies on boot (`V2_RUN_MIGRATIONS_ON_BOOT=true`); `event_audit`
grows ~4.4× over a year. No account changes happen by themselves. To finish:
add the `SENTRY_AUTH_TOKEN` repo secret (`project:releases`, `org:read`), run
`scripts/ops/sentry_alerts.sh --apply`, create the uptime monitor per
`scripts/ops/uptime.md`, optionally create the `courtmastr-frontend` Sentry
project and set the `NEXT_PUBLIC_SENTRY_DSN` repo variable.

## Risk / rollback
Low. Logging changes only affect levels/propagation; the job wrapper keeps the
lease semantics and adds a post-body heartbeat; all Sentry additions are gated
on secrets/env that are unset until the owner acts. Rollback is reverting the
merge; the TTL change reverses with another `collMod`.
