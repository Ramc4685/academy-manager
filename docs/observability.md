# Observability — Wave 1A

**Status:** Authoritative. Implemented across `backend/v2/shared/observability/`, `frontend/lib/pwa/vitals.ts`, and the dashboards described below.
**Ticket:** W1A-19
**Last reviewed:** 2026-05-16

## What we measure

### Backend (FastAPI v2)

| Signal | Where | Notes |
|---|---|---|
| Request traces | OpenTelemetry FastAPI auto-instrumentation | Head-based sampling at 10% (errors at 100%). |
| Mongo span | OpenTelemetry Motor instrumentation (lazy import) | Captures `db.collection`, `db.operation`, latency. |
| Structured JSON logs | `shared/observability/logging.py` | Every log carries `trace_id`, `span_id`, `academy_id` if set, `request_id`. |
| Trace-id response header | FastAPI middleware → `x-trace-id` | Frontend logs this in Sentry breadcrumbs and PostHog. |
| RED metrics per BFF route | OTel → OTLP → Grafana/Honeycomb (deploy-env specific) | p50/p95/p99 latency, error rate. |
| Domain event audit | `event_audit` collection (90d TTL) | Dispatcher writes one row per attempted handler call. |

**SLO (Wave 1A):**

- `GET /api/v2/coach/today` p95 < 300 ms.
- `POST /api/v2/coach/attendance` p95 < 800 ms.
- Error rate ≤ 0.5% over a 10-minute rolling window.

Breach pages oncall via the OTLP-vendor's alerting config (Grafana / Honeycomb).

### Frontend (Next.js v2)

| Signal | Where | Sink |
|---|---|---|
| LCP, FCP, CLS, INP, TTFB | `lib/pwa/vitals.ts` via `web-vitals` package | `posthog.capture("web_vital", { metric, value, rating, route, id })` |
| Install prompt shown | `useInstallPrompt` in `components/coach/install-card.tsx` | `posthog.capture("install_prompt_shown", { platform })` (added in Wave-1A post-baseline) |
| Install accepted | `appinstalled` event | `posthog.capture("install_accepted", { platform })` |
| Mutation queue stats (Wave 1B) | n/a today | Deferred. |
| Service-worker update applied | `useServiceWorkerUpdate` | `posthog.capture("sw_update_applied")` |

## Dashboards

Each persona route gets one dashboard. Wave 1A ships:

**Coach dashboard** (Grafana or PostHog):

- Card: `coach.today` p50/p95/p99 latency (last 1h, last 24h, last 7d).
- Card: error rate by code (`Coaching.*`, `Identity.*`, `Enrollment.*`).
- Card: web-vitals histogram — LCP, INP, CLS — segmented by `route`.
- Card: install-prompt-shown vs install-accepted ratio (per platform: Android / iOS-instructions).
- Card: SW-update-applied events (proves update flow works in the field).
- Card: dead-letter event count (should be 0).

## Trace-ID propagation

The backend middleware adds `x-trace-id` to every response. The frontend
records it as a Sentry breadcrumb and a PostHog event property:

```ts
// lib/api/client.ts (planned for Wave 1A polish — landed inline today)
const traceId = res.headers.get("x-trace-id");
if (traceId && window.posthog) window.posthog.register({ last_trace_id: traceId });
```

Operators clicking through a Sentry error see the trace ID and can pivot to
the OTel UI for the matching server span.

## What we don't measure (yet)

- Per-user RUM beyond Web Vitals. Add only when there's a question we
  can't answer from existing signals.
- Mutation queue length (Wave 1B).
- Service-worker cache hit rate (deferred; useful but not load-bearing).
- Per-tenant SLO breakdown (single-tenant today per ADR-0006).

## Operator runbook

- **SLO breach (latency or error rate):** Check `event_audit` for handler
  failures, check `dead_letter_events`, then OTel traces for the slow
  spans. The Mongo span typically tells you the culprit.
- **Stale install metrics:** Confirm PostHog snippet loaded on
  `frontend` (Wave 1A initially loads it from `app/layout.tsx`).
- **Dead-letter accumulating:** `python -m backend.v2.scripts.replay_event
  <event_id>` after the root cause is fixed.
