# chore-observability-hardening

PR: #644

## What changed
- Backend JSON logs now carry every `extra=` field callers pass (job ids,
  health check detail, webhook quarantine reasons). Reserved keys are
  protected and non-JSON values are stringified.
- One JSON log line per request with method, route, status, `duration_ms`,
  `request_id` and `academy_id`; the Fly health probe is logged at DEBUG.
  uvicorn's plain-text access log is disabled (`--no-access-log`).
- Unhandled exceptions log one JSON error line with the traceback and the
  request id, then re-raise, so the 500 response and Sentry capture are
  unchanged.
- Sentry is initialised with a `release` from `SENTRY_RELEASE` or Fly's
  `FLY_IMAGE_REF`, so regressions across deploys are attributable.
- The post-deploy smoke checks CORS, HTML and BFF health on every
  `TENANT_FRONTEND_URLS` origin; CI passes `blno-academy.courtmastr.com`.
- `fly.toml`: `kill_timeout = "30s"` and health `grace_period = "60s"`.
- Removed the Size limit and Lighthouse CI steps (no config, missing
  secret), the two legacy Cloudflare cleanup steps on every frontend
  deploy, and the retired `edge/` Worker source.
- `docs/observability.md` rewritten to match reality; `docs/ci-cd.md` and
  `AGENTS.md` corrected on mypy, required checks, coverage and test count.

## Deploy notes
Backend deploys normally. After deploy, `fly logs` should show one JSON
line per request with `duration_ms`. Log volume per request roughly
doubles versus before (one structured line replaces uvicorn's text line,
plus an error line on 500s); Fly retention is unaffected. No new secrets
are required; Sentry stays inert until `SENTRY_DSN` is set.

## Risk / rollback
Low. The request-log middleware is pure ASGI and re-raises on failure; the
catch-all handler re-raises so status codes are unchanged. If the log
volume or the duplicate traceback on 500s (ours plus uvicorn's) is
unwanted, revert this PR; nothing else depends on it. The removed
Cloudflare cleanup steps have been no-ops since 2026-05-18.
