# Observability

**Status:** Authoritative as of 2026-09-05. Describes what is implemented in
`backend/v2/shared/observability/` (plus the frontend pieces it depends on)
and what is switched on in production. Replaces the Wave 1A document, which
described OpenTelemetry, PostHog and Honeycomb integrations that were never
built (see `docs/audit/plans/C2-observability.md`, which chose Sentry over
OTel).

Account-side facts referenced below (verified 2026-09-05):

| Thing | Value |
|---|---|
| Fly app | `courtmastr-academy-api` (health check `GET /api/v2/healthz` every 30s, 5s timeout, 60s grace) |
| Sentry org / project | `blno-badmintion` / `courtmastr-fastapi` (free plan) |
| Sentry Logs | receiving INFO+, 30-day retention, 5 GB/month cap (dropped, never billed) |
| Resend webhook | `email.bounced`, `email.complained`, `email.delivered` -> `https://api.academy.courtmastr.com/api/v2/webhooks/resend` |
| Scheduler | 9 APScheduler jobs, `SCHEDULER_TZ=America/Chicago` in prod |

## What exists in code

| Signal | Where | Notes |
|---|---|---|
| JSON logs | `observability/logging.py` | `timestamp, level, logger, message` plus `request_id`, `academy_id`, `trace_id`/`span_id` when present, and every `extra=` field the caller passes. Default level INFO, format `json` (`LOG_LEVEL` / `LOG_FORMAT`). Uvicorn's own handlers are removed and its loggers propagate to the root handler; `uvicorn.access` is silenced because the app writes its own access line. Third-party loggers are pinned at WARNING (see the logger table below). |
| Request correlation | `observability/request_context.py` | Accepts `X-Request-ID` or `Fly-Request-Id`, else mints a UUID; echoes it on the response; stamps `request_id` and `academy_id` on every log record in the request. See "Request-id flow" for the browser -> proxy -> API path. |
| Per-request access line | `observability/request_context.py` (`backend.v2.http.request`) | One JSON line per request with method, path, status, `duration_ms`, `request_id`, `academy_id`. `/api/v2/healthz` is logged at DEBUG so the 30s Fly probe does not flood INFO. |
| Unhandled 500s | `shared/http/errors.py` | A catch-all handler logs one JSON error line with the traceback and `request_id`, then re-raises so Starlette still returns 500 and Sentry still captures it. `DomainError` keeps its own 4xx mapping. |
| Error tracking | `observability/errors.py`, `ops_alerts.py` | Sentry SDK with `send_default_pii=False`, tagged with `request_id` and `academy_id`, `environment` from settings and `release` from `V2_SENTRY_RELEASE` / `SENTRY_RELEASE` / Fly's `FLY_IMAGE_REF` (CI also creates the release `courtmastr-fastapi@<sha>` on deploy, see "Releases"). Captures request exceptions, APScheduler job errors/misses, outbox dispatcher loop failures (throttled 1/10/every-100), and Resend credential rejection at boot. No-op until `SENTRY_DSN` is set. |
| Sentry Logs | `observability/errors.py` `_keep_log` | With a DSN set and `SENTRY_LOGS_ENABLED` (default on), INFO+ records from the JSON pipeline are also forwarded to Sentry Logs. `_keep_log` is the quota guard: DEBUG never leaves the box, `uvicorn.access` and healthz lines are dropped. |
| Sentry Crons | `main.py` scheduler wiring, `V2_SENTRY_CRON_JOBS` | Opt-in dead-man switch for scheduler jobs. Jobs named in the comma-separated allowlist (default `generate_monthly_invoices`) send Sentry Crons check-ins (`in_progress` -> `ok`/`error`) around each run, so a job that never runs raises a "missed check-in" issue in Sentry. Jobs not in the allowlist are unchanged. See "Cron monitors". |
| Health | `observability/health.py`, `GET /api/v2/healthz` | Mongo ping (2s), scheduler running + job count, outbox dispatcher running. Returns 503 only for restart-fixable faults. Reports per-job `last_tick_age_seconds` / `last_run_age_seconds` from `ops_job_runs` and a per-job `stale: true` flag when the age exceeds the job's expected interval; stale is informational and never fails the check (a restart cannot make a monthly job run). Nested results use `ok:` not `status:` so the smoke grep cannot be spoofed. |
| Job heartbeats | `observability/ops_digest.py` `record_job_run`, `seed_job_heartbeats` | Every leased scheduler job writes `last_tick_at` and totals to `ops_job_runs`. At boot every registered job without a document is seeded with the boot time (`$setOnInsert`, never moves a real heartbeat), so "stale" means "no tick for a full window since boot" and the first digest after a deploy or in a fresh database does not list the jobs whose first tick is still ahead. Surfaced on healthz and in the daily digest's stale-job section. |
| Daily ops digest | `ops_digest.py`, `main.py` (07:00 scheduler TZ, job `send_ops_digest`) | Emails `OPS_ALERT_EMAIL` quarantined Stripe webhooks, dead-letter events, dunning terminals, failed digest sends, last invoice run, and a "stale jobs" section listing any scheduler job whose heartbeat is older than its interval. Skipped until `OPS_ALERT_EMAIL` is set. |
| Email bounces / complaints | `interfaces/email_webhook_routes.py` | Resend webhook ingestion feeding the suppression list. 404s until `RESEND_WEBHOOK_SECRET` is set and the webhook is created in Resend. |
| Forensic stores | `event_audit` (400-day TTL since migration 0166), `dead_letter_events`, `stripe_webhook_events`, platform audit log | Pull-only. Visible through the admin billing-health page. The TTL was raised from 90 to 400 days so a yearly billing dispute still has its trail. |
| Frontend errors | `app/error.tsx`, `app/global-error.tsx`, `lib/query/mutation-errors.ts` | Error toasts carry `Reference: xxxxxxxx` (the first 8 chars of the request id echoed by the API) so a parent can read it back to us. `@sentry/browser` initialises only when `NEXT_PUBLIC_SENTRY_DSN` is set at build time; without it the frontend still only `console.error`s. `lib/pwa/vitals.ts` sends Web Vitals to Sentry as `web_vitals.<name>` distribution metrics via `lib/observability/sentry.ts` `recordVital` (same DSN gate; without it they only log to the console in dev). Cloudflare Workers Logs are enabled in `wrangler.jsonc` (free plan: 3-day retention). |
| BFF proxy request ids | `frontend/app/api/v2/[...path]/route.ts` | The Next.js proxy mints an `X-Request-ID` per upstream call when the browser did not send one, forwards it to the API, and copies the API's echoed header back onto the browser response. |
| Tracing | `observability/tracing.py` | Permanent no-op: the OpenTelemetry packages are not installed. Deliberate at this scale. |

## Logger levels

| Logger | Level | Why |
|---|---|---|
| root (everything under `backend.v2.*`) | `LOG_LEVEL`, default INFO | Application logs. INFO+ also goes to Sentry Logs. |
| `backend.v2.http.request` | INFO; `/api/v2/healthz` lines at DEBUG | One access line per request. The Fly probe fires 2,880 times a day. |
| `backend.v2.scheduler` | INFO | Job start/finish/error lines with `job_id`. |
| `uvicorn`, `uvicorn.error` | INFO, propagate to root | Startup, shutdown and "Exception in ASGI application" tracebacks in the same JSON shape as app logs. |
| `uvicorn.access` | silenced (no handler, dropped by `_keep_log` as belt-and-braces) | Duplicate of `backend.v2.http.request` without `request_id`/`academy_id`. |
| third-party (`pymongo`, `motor`, `httpx`, `httpcore`, `apscheduler`, `stripe`, `urllib3`, and the rest of the list in `observability/logging.py`) | WARNING | Their INFO/DEBUG is connection-pool chatter that would eat the 5 GB Sentry Logs budget. |
| `sentry_sdk` | WARNING | The SDK's own transport noise. |

Sentry event levels: an `ERROR` log record or an unhandled exception becomes a
Sentry *issue*; INFO and WARNING records become breadcrumbs on that issue and
lines in Sentry Logs. Nothing below INFO leaves the machine.

## Request-id flow

```text
browser                       Next.js BFF proxy (Cloudflare)              FastAPI (Fly)
-------                       -----------------------------              -------------
fetch /api/v2/...   ------->  app/api/v2/[...path]/route.ts
                              X-Request-ID = incoming header
                                            or crypto.randomUUID()
                              forward to API ------------------------->  RequestContextMiddleware
                                                                          accepts X-Request-ID
                                                                          (else Fly-Request-Id, else uuid4)
                                                                          contextvar -> every log line,
                                                                          Sentry tag request_id
                              <----------------------------------------  response echoes X-Request-ID
toast "Reference: 1a2b3c4d"   <-- response echoes X-Request-ID
```

The eight-character reference in a toast is the prefix of the full id; search
Sentry Logs with `request_id:1a2b3c4d*` or Fly logs with `grep 1a2b3c4d`.
Server-rendered pages and the scheduler have no browser hop: the API mints the
id itself, and scheduler log lines carry `job_id` instead of `request_id`.

## Cron monitors

Sentry Crons check-ins are opt-in per job through `V2_SENTRY_CRON_JOBS`
(comma-separated APScheduler job ids). Default allowlist:

| Job id | Schedule (scheduler TZ) | Why it is monitored |
|---|---|---|
| `generate_monthly_invoices` | daily 03:00 (mints on the academy's cycle day) | A silent miss means no invoices, no autopay, no revenue; it is the one job whose failure is invisible on healthz within a day. |

Candidates that stay off until they prove noisy enough to matter:
`process_stripe_webhook_events` (every 60s), `reconcile_stripe_payment_intents`
(every 10m), `process_dunning_retries` (hourly), `process_scheduled_resume_actions`
and `expire_makeup_requests` (daily 02:00), `send_coach_daily_digests` and
`send_parent_daily_digests` (hourly tick, per-academy hour), `send_ops_digest`
(daily 07:00). Adding one is a Fly env change, not a deploy:

```bash
fly secrets set -a courtmastr-academy-api \
  V2_SENTRY_CRON_JOBS=generate_monthly_invoices,send_ops_digest
```

The Sentry monitor slug equals the job id. Monitors are auto-created on the
first check-in (upsert), with the schedule taken from the job's trigger; there
is nothing to click in the Sentry UI. `sentry monitor list` shows them.

## Releases

CI creates the Sentry release `courtmastr-fastapi@<git sha>` on every
production deploy using the `SENTRY_AUTH_TOKEN` repo secret, and the API tags
events with the same string via `V2_SENTRY_RELEASE`. Without the token the
step is skipped and events fall back to `FLY_IMAGE_REF`, which still separates
deploys but does not link commits. `sentry release list courtmastr-fastapi`
to check.

## What is switched on in production

As of 2026-09-05 all three application-side switches are set on the Fly app
(`SENTRY_DSN`, `OPS_ALERT_EMAIL`, `RESEND_WEBHOOK_SECRET`), so:

- Errors and INFO+ logs reach Sentry (`blno-badmintion/courtmastr-fastapi`).
  Zero issues recorded so far.
- The 07:00 ops digest emails the owner daily.
- Resend bounce/complaint/delivered events land in the suppression list.
- The Fly health probe restarts the machine on 503; the post-deploy smoke in
  CI greps healthz for `"status":"ok"`.
- Fly's built-in machine and HTTP metrics are collected and viewable on
  fly-metrics.net.

Still not switched on (see `scripts/ops/`):

- No external uptime monitor: if the Fly machine or Cloudflare route is down,
  nobody is paged. `scripts/ops/uptime.md` has the steps (Sentry Uptime
  recommended, Better Stack as the alternative).
- No Fly Grafana alert rules for 5xx rate, memory or restarts:
  `scripts/ops/uptime.md`, second half.
- Only one Sentry issue alert exists and no metric alert;
  `scripts/ops/sentry_alerts.sh --apply` creates the rest (dry-run by default).
- The `NEXT_PUBLIC_SENTRY_DSN` repo variable is not set, so browser errors
  are not reported. The `deploy-frontend` job forwards it (plus
  `NEXT_PUBLIC_APP_ENV` and `NEXT_PUBLIC_SENTRY_RELEASE`) into the Worker
  build and prints a `::notice::` with the state it built; setting the
  variable and redeploying is the whole switch. Query strings are stripped
  from event URLs, the Referer header and navigation/fetch breadcrumbs before
  send (magic-link tokens, Firebase `oobCode`s and `?email=` live there).
- `SENTRY_AUTH_TOKEN` must be present as a repo secret for the release step
  to run; check the deploy workflow's "Sentry release" step is not skipped.

## Log field reference

Every line: `timestamp`, `level`, `logger`, `message`. When in a request:
`request_id`, `academy_id`. In a scheduler job: `job_id`. On errors:
`exception` (formatted traceback). Caller-supplied `extra=` keys are merged
as-is; reserved keys are never overwritten. Non-JSON values are stringified.

Do not log recipient email addresses; log ids. The two remaining call sites
that log an email (`interfaces/admin/directory_routes.py`, login-invite
failures) are the known exception.

## Where to look when something is wrong

The `sentry` CLI (`sentry auth status` to confirm login) is the fastest path;
the Sentry UI is the same data.

1. Recent errors:

   ```bash
   sentry issue list blno-badmintion/courtmastr-fastapi --period 24h
   sentry issue view blno-badmintion/courtmastr-fastapi/<issue-id>
   sentry issue explain <issue-id>         # AI summary when you are cold
   ```

2. Logs around a reference id the user read from a toast:

   ```bash
   sentry log list blno-badmintion/courtmastr-fastapi --period 2h
   sentry log list blno-badmintion/courtmastr-fastapi --period 24h \
     -q 'request_id:1a2b3c4d*'
   sentry log list blno-badmintion/courtmastr-fastapi -q 'severity:error' --period 7d
   sentry log list blno-badmintion/courtmastr-fastapi -f    # tail, 2s poll
   ```

   Fly's stdout is the same stream with about 7 days of retention and no
   search: `fly logs -a courtmastr-academy-api --no-tail | grep <request_id>`.
   The `fly logs` live tail keeps only about 2 hours.

3. Scheduler health:

   ```bash
   curl -fsS https://api.academy.courtmastr.com/api/v2/healthz | jq .checks.scheduler
   sentry monitor list blno-badmintion   # Crons check-ins for the allowlist
   ```

   A job with `stale: true` has not ticked within its interval; the daily
   digest repeats the same list. A job in the Crons allowlist that stops
   ticking also opens a Sentry issue on its own.

4. Admin billing-health page for quarantined Stripe events;
   `stripe events list --live` for the payment side (needs `stripe login`).

5. Fly dashboard / fly-metrics.net for 5xx rate, memory and restarts.

6. Raw API when the CLI has no command for it:

   ```bash
   sentry api projects/blno-badmintion/courtmastr-fastapi/rules/ --json
   sentry api organizations/blno-badmintion/alert-rules/ --json
   ```

## Alert routing

Everything that can wake a human today, and where it goes. "Owner email"
means the Sentry account email of the single org owner (member role `owner`);
Sentry cannot email an arbitrary address, so changing the destination means
adding a member or a Slack/PagerDuty integration.

| Alert | Source | Trigger | Route |
|---|---|---|---|
| High priority issue | Sentry issue alert "Send a notification for high priority issues" (rule `10003945745`) | Sentry marks a new or existing issue high priority | Email: issue owners, fallthrough active members (= owner email) |
| New issue | Sentry issue alert "New issue" (`sentry_alerts.sh`) | first event of a new issue | Email: issue owners, fallthrough all members |
| Regression | Sentry issue alert "Regression" (`sentry_alerts.sh`) | resolved issue sees a new event | Email: same |
| High frequency | Sentry issue alert "High frequency" (`sentry_alerts.sh`) | one issue has >= 10 events in 1h | Email: same, at most once per hour per issue |
| Error rate spike | Sentry metric alert "Error rate spike" (`sentry_alerts.sh`) | `count()` of error events > 5 in a 5-minute window | Email: the owner user |
| Missed cron | Sentry Crons monitor per job in `V2_SENTRY_CRON_JOBS` | check-in missed or job errored | Opens a Sentry issue -> "New issue" / "High priority" rules above |
| Daily ops digest | `send_ops_digest` job at 07:00 America/Chicago | always (content varies); quarantined webhooks, dead letters, dunning terminals, failed digests, stale jobs | Email to `OPS_ALERT_EMAIL` via Resend |
| Machine unhealthy | Fly health check on `/api/v2/healthz` | 503 or timeout | Fly restarts the machine. No notification. |
| Deploy smoke | CI `scripts/smoke/production_smoke.sh` | healthz body lacks `"status":"ok"` | Failed workflow run; GitHub emails the pusher |
| Uptime | none yet | see `scripts/ops/uptime.md` | (Sentry Uptime -> "New issue" rule once created) |
| 5xx rate / memory / restarts | none yet | see `scripts/ops/uptime.md` | (Fly Grafana contact point -> owner email once created) |

Not alerts, but notifications people may mistake for them: Resend bounce
emails (Resend's own dashboard notifications), Stripe's failed-payment emails
to the account owner, and GitHub Dependabot mail.

## Incidents

Write one note per production incident in `docs/incidents/` using the
template in `docs/incidents/README.md`. Eight incidents from June to
September 2026 predate this rule and are recorded only in session memory.
