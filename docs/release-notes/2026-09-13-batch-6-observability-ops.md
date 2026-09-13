# batch-6-observability-ops

PR: #0

## What changed

- Fixes #749 — Backend Sentry performance tracing was always off in prod: `sentry_traces_sample_rate` had no env-based fallback (unlike `sentry_dsn`/`sentry_logs_enabled`), and nothing in the repo set `V2_SENTRY_TRACES_SAMPLE_RATE`, so `sentry_sdk.init` always got `traces_sample_rate=0.0`. The rate now defaults to `0.1` only when `env=="prod"` and no explicit `V2_SENTRY_TRACES_SAMPLE_RATE`/`SENTRY_TRACES_SAMPLE_RATE` is set (test/dev/CI keep `0.0`; an explicit env var still wins). Also closed a second gap: scheduled/cron jobs never produced a Sentry Performance transaction (only Crons check-ins) — `cron_checkin` now wraps the job body in `sentry_sdk.start_transaction(op="scheduler.job", name=job_id)`, best-effort with a `nullcontext` fallback if the SDK call fails. Added `docs/runbooks/sentry-performance.md` documenting the two Performance dashboard widgets that must be created manually in the Sentry UI (p95 latency by transaction, cron job duration/failure rate) since dashboards aren't code. Frontend tracing (`sentry.ts` `tracesSampleRate=0.2` + `browserTracingIntegration`) and the CSP ingest-host allowance were already correct; the runbook states that any remaining frontend trace gap is not explainable from this repo's code.
- Fixes #611 — Added a read-only tenant host preflight so a new academy host can no longer launch half-registered. `backend/scripts/tenant_host_preflight.py` takes `--host` and reports four gates PASS/FAIL/MANUAL: host resolves to a tenant (via the real `TenantResolver` over Mongo), Google OAuth client origins/redirect (always MANUAL — no API exists — with the exact console steps and `https://<host>/__/auth/handler`), Firebase authorized domains (read via the Identity Toolkit admin API with `x-goog-user-project`, degrading to MANUAL on any credential/permission/API failure so ops never sees a false FAIL), and tenant redirect origins (via the production `TenantOriginsResolver`, verified `academy_domains` only). Exit code is driven only by the two conclusively-checkable gates. Supports a text checklist plus `--json`. Nothing writes: no Mongo mutations, no console changes, and `shared/tenancy`/`shared/auth` are untouched — the script calls their existing public helpers. Added `docs/runbooks/tenant-host-onboarding.md` with per-gate symptoms, the same console step text, and an onboarding checklist; a unit test asserts the runbook still documents every gate heading so doc and script cannot silently drift.
- Also fixes a mypy `no-any-return` finding introduced by the #749 cron transaction wrapper (`_job_transaction` returned `Any` because `sentry_sdk` is typed `Any`) by casting the `start_transaction` call to `AbstractContextManager[Any]`.

## Deploy notes

No migrations. No new required env vars — `V2_SENTRY_TRACES_SAMPLE_RATE` / `SENTRY_TRACES_SAMPLE_RATE` remain optional overrides of the new prod default (0.1). `tenant_host_preflight.py` is an ops script run manually (or from CI) before onboarding a new academy host; it is not wired into any deploy or boot path.

## Risk / rollback

Both changes are additive and low-risk: the Sentry sample-rate default only takes effect in `env=="prod"` and only raises Sentry Performance event volume (bounded by the sample rate), and the cron transaction wrapper is wrapped in a try/except with a `nullcontext` fallback so a Sentry SDK failure cannot break a scheduled job. The preflight script performs no writes. If anything regresses, revert this PR's merge commit.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
