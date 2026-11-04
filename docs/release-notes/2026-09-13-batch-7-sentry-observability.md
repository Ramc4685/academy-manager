# batch-7-sentry-observability

PR: #810

## What changed

- Fixes #753 — Frontend Sentry init tagged local dev traffic as `environment=production` in the shared prod Sentry project. `sentry.ts` defaulted `environment` to `"production"` when `NEXT_PUBLIC_APP_ENV` was unset, and `initSentry()` had no localhost guard, so any dev machine pointed at the staging/prod DSN posted real browser events into the prod project labeled production. The environment default is now `"development"`, and `initSentry()` skips loading the SDK entirely on `localhost` / `127.0.0.1` / `*.localhost` hostnames unless `NEXT_PUBLIC_SENTRY_FORCE_LOCAL=1` is set. The existing `setSentryUser` call added by #800 in this file is untouched.
- Fixes #754 — `reportApiFailure` fingerprinted every API-route network failure separately (per path/outcome), so a single flaky-network incident opened one Sentry issue per route instead of one issue total. Network-kind failures are now fingerprinted into a single route-agnostic bucket (`["api-network-failure"]`) at `warning` severity, while `api.path`/`api.method` tags are kept on the event for triage. Added `addBreadcrumb()` to `sentry.ts` and a `level` field on `CaptureContext` (applied via `scope.setLevel`). `apiFetch`'s catch handler now checks `navigator.onLine === false` and records a breadcrumb instead of calling `reportApiFailure` when the request never reached the network (not actionable). Timeout (`AbortError`) and server-error (5xx) handling are unchanged.

## Deploy notes

No migrations. No new required env vars — `NEXT_PUBLIC_SENTRY_FORCE_LOCAL` is an optional opt-in for a developer who deliberately wants local events to reach Sentry; `NEXT_PUBLIC_APP_ENV` behavior is unchanged for staging/prod deploys where it is always set explicitly.

## Risk / rollback

Both changes are frontend-only and reduce Sentry noise/mistagging without changing user-facing behavior: the localhost guard only affects unset-env dev machines, and the network-failure fingerprint change only affects how existing network errors are grouped/reported, not whether real 5xx/timeout errors are captured. If anything regresses, revert this PR's merge commit.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
