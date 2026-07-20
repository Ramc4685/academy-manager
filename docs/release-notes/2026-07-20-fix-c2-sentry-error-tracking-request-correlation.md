# fix-c2-sentry-error-tracking-request-correlation

PR: #314

## What changed

Backend errors are now reported to Sentry (FastAPI integration, errors-first —
performance tracing off by default), and every request gets a correlation id: a
new `RequestContextMiddleware` propagates/generates `X-Request-ID` (accepts
Fly-Request-Id) and a log filter stamps `request_id` + `academy_id` onto every
JSON log line and Sentry event tag. Audit item C2.

## Deploy notes

- Set `V2_SENTRY_DSN` (staging + prod) via `fly secrets set V2_SENTRY_DSN=<dsn>`.
  Unset ⇒ Sentry disabled, current behavior (dev/test/CI default). Legacy
  `SENTRY_DSN` is honoured as a fallback.
- Optional: `V2_SENTRY_TRACES_SAMPLE_RATE` (default 0.0).
- New dependency `sentry-sdk[fastapi]==2.66.0` installs from requirements.txt
  during the normal image build; no migrations.

## Risk / rollback

Sentry SDK is fail-open (drops events, never blocks requests); `send_default_pii`
stays False so events carry ids/tags, not payloads. Rollback: unset
`V2_SENTRY_DSN` (instant, no deploy) or revert the PR — no schema/data changes.
