# Observability

**Status:** Authoritative as of 2026-09-03. Describes what is implemented in
`backend/v2/shared/observability/` and what is switched on in production.
Replaces the Wave 1A document, which described OpenTelemetry, PostHog and
Honeycomb integrations that were never built (see
`docs/audit/plans/C2-observability.md`, which chose Sentry over OTel).

## What exists in code

| Signal | Where | Notes |
|---|---|---|
| JSON logs | `observability/logging.py` | `timestamp, level, logger, message` plus `request_id`, `academy_id`, `trace_id`/`span_id` when present, and every `extra=` field the caller passes. Default level INFO, format `json` (`LOG_LEVEL` / `LOG_FORMAT`). |
| Request correlation | `observability/request_context.py` | Accepts `X-Request-ID` or `Fly-Request-Id`, else mints a UUID; echoes it on the response; stamps `request_id` and `academy_id` on every log record in the request. |
| Per-request access line | `observability/request_context.py` | One JSON line per request with method, path, status, `duration_ms`, `request_id`, `academy_id`. `/api/v2/healthz` is logged at DEBUG so the 30s Fly probe does not flood INFO. |
| Unhandled 500s | `shared/http/errors.py` | A catch-all handler logs one JSON error line with the traceback and `request_id`, then re-raises so Starlette still returns 500 and Sentry still captures it. `DomainError` keeps its own 4xx mapping. |
| Error tracking | `observability/errors.py`, `ops_alerts.py` | Sentry SDK with `send_default_pii=False`, tagged with `request_id` and `academy_id`, `environment` from settings and `release` from `SENTRY_RELEASE` or Fly's `FLY_IMAGE_REF`. Captures request exceptions, APScheduler job errors/misses, outbox dispatcher loop failures (throttled 1/10/every-100), and Resend credential rejection at boot. **No-op until `SENTRY_DSN` is set.** |
| Health | `observability/health.py`, `GET /api/v2/healthz` | Mongo ping (2s), scheduler running + job count, outbox dispatcher running. Returns 503 only for restart-fixable faults. Reports per-job `last_tick_age_seconds` / `last_run_age_seconds` from `ops_job_runs` as informational. Nested results use `ok:` not `status:` so the smoke grep cannot be spoofed. |
| Job heartbeats | `observability/ops_digest.py` `record_job_run` | Every leased scheduler job writes `last_tick_at` and totals to `ops_job_runs`. Surfaced on healthz; nothing external consumes them yet. |
| Daily ops digest | `ops_digest.py`, `main.py` (07:00 scheduler TZ) | Emails the owner quarantined Stripe webhooks, dead-letter events, dunning terminals, failed digest sends, last invoice run. **Skipped until `OPS_ALERT_EMAIL` is set.** |
| Email bounces / complaints | `interfaces/email_webhook_routes.py` | Resend webhook ingestion feeding the suppression list. **404s until `RESEND_WEBHOOK_SECRET` is set and the webhook is created in Resend.** |
| Forensic stores | `event_audit` (90-day TTL), `dead_letter_events`, `stripe_webhook_events`, platform audit log | Pull-only. Visible through the admin billing-health page. |
| Frontend | `app/error.tsx`, `app/global-error.tsx`, `lib/query/mutation-errors.ts` | `console.error` and a toast only. `lib/pwa/vitals.ts` posts Web Vitals to `window.posthog` if present; PostHog is not installed, so vitals go nowhere. Cloudflare Workers Logs are enabled in `wrangler.jsonc` (free plan: 3-day retention). |
| Tracing | `observability/tracing.py` | Permanent no-op: the OpenTelemetry packages are not installed. Deliberate at this scale. |

## What is switched on in production

As of 2026-09-03: JSON logs to Fly's stdout (about 7 days retention, not
shipped anywhere), the Fly health probe (restarts the machine on 503), and the
post-deploy smoke in CI. Fly's built-in machine and HTTP metrics are collected
and viewable on fly-metrics.net with no alert rules configured.

Not switched on, each a single Fly secret away:

```bash
fly secrets set -a courtmastr-academy-api \
  SENTRY_DSN=... \
  OPS_ALERT_EMAIL=... \
  RESEND_WEBHOOK_SECRET=...
```

There is no external uptime monitor and no dead-man switch on the scheduled
jobs. See the 2026-09-02 delivery audit for the recommended free stack
(Sentry Developer, Better Stack uptime + heartbeats, Fly log shipper to Axiom).

## Log field reference

Every line: `timestamp`, `level`, `logger`, `message`. When in a request:
`request_id`, `academy_id`. On errors: `exception` (formatted traceback).
Caller-supplied `extra=` keys are merged as-is; reserved keys are never
overwritten. Non-JSON values are stringified.

Do not log recipient email addresses; log ids. The two remaining call sites
that log an email (`interfaces/admin/directory_routes.py`, login-invite
failures) are the known exception.

## Where to look when something is wrong

1. `fly logs -a courtmastr-academy-api` and grep the `request_id` echoed in
   the response header the user saw.
2. `GET /api/v2/healthz` for job ages; a job whose `last_tick_age_seconds`
   exceeds its interval is stalled.
3. Admin billing-health page for quarantined Stripe events.
4. `stripe events list --live` for the payment side (needs `stripe login`).
5. Fly dashboard metrics for 5xx rate and memory.

## Incidents

Write one note per production incident in `docs/incidents/` using the
template there. Eight incidents from June to September 2026 predate this
rule and are recorded only in session memory.
