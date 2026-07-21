# c2-observability

## Current State

Status: active

## Problem

Audit C2: no error tracking, no request correlation — tracing.py no-ops (OTel not installed) and the request_id/academy_id JSON log fields are never populated.

## Changed Files

- None recorded yet.

## Log

- 2026-07-20T16:05:00 main/NA: Task ledger created.
- 2026-07-20T16:05:00 main/working: Sentry SDK (fastapi integration) gated on V2_SENTRY_DSN (legacy SENTRY_DSN fallback); RequestContextMiddleware propagates/generates X-Request-ID (Fly-Request-Id accepted); ContextLogFilter stamps request_id/academy_id on JSON logs; before_send tags same values on Sentry events. OTel seam untouched.
## Verification

- No verification recorded yet.
- 2026-07-20T16:05:30: pytest v2/tests -n auto: 2524 passed. ruff check v2: clean. lint-imports: 5 contracts kept. mypy -p backend.v2 | mypy-baseline filter: 0 new violations (baseline not grown). New unit tests: 9 passed (v2/tests/unit/test_request_context.py). Staging done-criterion (error visible in Sentry with request_id+academy_id tags) pending V2_SENTRY_DSN secret + deploy.
## Reusable Lessons

- None recorded yet.
