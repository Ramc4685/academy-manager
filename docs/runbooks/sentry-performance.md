# Sentry performance tracing (#749)

## What code now does

- `backend/v2/shared/config/settings.py` defaults
  `sentry_traces_sample_rate` to `0.1` in `env=prod` when neither
  `V2_SENTRY_TRACES_SAMPLE_RATE` nor `SENTRY_TRACES_SAMPLE_RATE` is set.
  Test/dev/CI keep the errors-first `0.0` default; an explicit env var
  still wins. Override the rate without a code change via:

  ```bash
  fly secrets set V2_SENTRY_TRACES_SAMPLE_RATE=0.2 -a <backend-app>
  ```

- `backend/v2/shared/observability/errors.py` already registers
  `StarletteIntegration` + `FastApiIntegration`, so once the sample rate
  is non-zero, HTTP request transactions start flowing with no other
  change.
- `backend/v2/shared/observability/ops_alerts.py`'s `cron_checkin` now
  also opens a `sentry_sdk.start_transaction(op="scheduler.job", name=job_id)`
  span around the job body (previously only the Sentry Crons check-in
  was recorded — cron/APScheduler jobs never produced a Performance
  transaction). This only fires for job ids in `settings.sentry_cron_jobs`,
  matching the existing Crons opt-in list.
- Frontend tracing (`frontend/.../sentry.ts`) already sets
  `tracesSampleRate: 0.2` with `browserTracingIntegration`, and the CSP
  already allows the Sentry ingest host. If frontend traces are still
  absent after this ships, that is not explainable from this repo's
  code — check browser extensions/ad blockers on the machine used to
  reproduce, and the project's ingestion/sampling settings in the
  Sentry UI, before assuming a code regression.

## Manual follow-up (cannot be done from code)

Sentry dashboards are not managed as code in this repo. After this
change ships and traces start arriving, create these two widgets by
hand in the Sentry project's Performance dashboard:

1. **p95 latency by transaction** — a table/graph widget grouped by
   `transaction`, measuring `p95(transaction.duration)`, filtered to
   `transaction.op:http.server`, so regressions on a specific route are
   visible at a glance.
2. **Cron job duration / failure rate** — a widget filtered to
   `transaction.op:scheduler.job`, showing `p95(transaction.duration)`
   and count of transactions with a non-`ok` status, so a job that
   silently got slower or started failing shows up without waiting for
   the ops digest's stale-job check.

Confirm the org's Sentry plan quota can absorb the added event volume
(10% of prod HTTP requests plus every opted-in cron run) before raising
the sample rate further.
