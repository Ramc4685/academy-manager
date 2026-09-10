# Enable Sentry performance tracing (frontend)

PR: #708

## What changed
- `lib/observability/sentry.ts`: added `browserTracingIntegration()` and
  raised `tracesSampleRate` from `0` to `0.2` in the browser SDK init. The
  frontend previously captured errors only; it now also samples
  navigation/fetch performance spans, matching the backend's rate.
- Companion backend change (already deployed, not part of this diff): the
  `courtmastr-academy-api` Fly app's `V2_SENTRY_TRACES_SAMPLE_RATE` secret
  was set to `0.2`, turning on the backend's existing (previously
  errors-first, tracing-off-by-default) FastAPI/Starlette tracing.

## Deploy notes
No migration in this diff. No manual env var needed for this PR — the
frontend DSN (`NEXT_PUBLIC_SENTRY_DSN`) is already a GitHub repo variable
baked in at CI build time. The backend secret was already applied directly
via `fly secrets set V2_SENTRY_TRACES_SAMPLE_RATE=0.2` ahead of this PR.

## Risk / rollback
Worst case: increased Sentry event volume (performance transactions) toward
the plan quota, or added client-side overhead from tracing instrumentation.
No data correctness or user-facing behavior risk. To roll back, revert this
PR (frontend) and/or `fly secrets set V2_SENTRY_TRACES_SAMPLE_RATE=0.0 -a courtmastr-academy-api` (backend).
