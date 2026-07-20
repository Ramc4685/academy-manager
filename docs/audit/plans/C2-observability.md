# C2 — Error tracking + request correlation
Status: TODO
Size: M · Depends on: none · Tracker: ../TRACKER.md

## Problem

Production has no error tracking and no request correlation. A payment failure today produces only uncorrelated stdout JSON lines on the Fly machine.

- `backend/v2/shared/observability/tracing.py:20-29`: `configure_tracing()` does `try: from opentelemetry import trace ... except ImportError: log.info("OpenTelemetry SDK not installed; tracing disabled."); return`. OpenTelemetry is **not** in `backend/requirements.txt` (verified: no `otel`/`sentry` lines), so this is a permanent no-op in every environment.
- `backend/v2/shared/observability/logging.py:26-30`: the JSON formatter already emits `trace_id`, `span_id`, `academy_id`, `user_id`, `request_id` **if present on the log record** — but nothing anywhere populates those attributes, so they never appear.
- No Sentry SDK in backend (`backend/requirements.txt`) or frontend (`frontend/package.json`).
- Wiring points exist: `backend/v2/main.py:126` calls `configure_logging()` in the lifespan; `main.py:558` calls `configure_tracing(app)` in `create_app()`.

## Current behavior (verified)

- `main.py:558-566`: `create_app()` runs `configure_tracing(app)` (no-op), then `register_exception_handlers(app)`, then adds `_LazyTenancyMiddleware`, `InMemoryRateLimitMiddleware`, CORS.
- Settings already have OTel knobs that do nothing: `backend/v2/shared/config/settings.py:72-73` (`otel_exporter_otlp_endpoint`, `otel_sampling_ratio`) and log config at :75-76.
- Settings follow a two-tier env pattern: `env_prefix="V2_"` (`settings.py:19`) with a `model_validator` (`settings.py:112-189`) that falls back to legacy unprefixed deploy names (`if "V2_X" not in os.environ: self.x = os.environ.get("X", ...)`).
- Tenant identity is available per-request via `backend/v2/shared/tenancy` ContextVar (`current_academy_id()` — used e.g. at `backend/v2/composition/parent.py:646`).

## Proposed change

**Sentry SDK (FastAPI integration) + a small request-ID middleware. Not OTel.**

Justification: the deploy is a single Fly machine with a Cloudflare-hosted Next.js frontend and no collector infrastructure. OTel would require running/paying for an OTLP backend and gives distributed tracing across a distribution of one service. Sentry gives the actual missing capability — alerting on exceptions with stack traces, release tagging, and searchable tags — with one dependency and zero infra. The existing `tracing.py` OTel seam stays as-is (it is dormant and harmless; if a collector ever appears, installing the OTel packages activates it). Frontend: add `@sentry/nextjs` for the worker in a follow-up commit of the same PR **if** OpenNext/Cloudflare build stays green; otherwise ship backend-only and file the frontend piece separately — backend correlation is the critical gap.

Request correlation: a new ASGI middleware generates/propagates `X-Request-ID`, stores it (plus resolved user/tenant when available) in contextvars, and a `logging.Filter` copies those contextvars onto every log record — lighting up the dormant fields in `logging.py:27-30`. The same values are set as Sentry tags, so an error in Sentry links to the exact log lines.

## Implementation steps

1. **Dependency**: add to `backend/requirements.txt`: `sentry-sdk[fastapi]` (pin current release, e.g. `sentry-sdk[fastapi]==2.x`).
2. **Settings** (`backend/v2/shared/config/settings.py`): add fields
   - `sentry_dsn: str | None = Field(default=None)`
   - `sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)` (errors-first; perf tracing off by default)
   and in `apply_legacy_deploy_fallbacks` (after :186, following the existing pattern): `if "V2_SENTRY_DSN" not in os.environ: self.sentry_dsn = os.environ.get("SENTRY_DSN", self.sentry_dsn)`.
3. **New module** `backend/v2/shared/observability/request_context.py`:
   - contextvar `_request_id: ContextVar[str | None]`
   - `RequestContextMiddleware` (pure ASGI or BaseHTTPMiddleware, matching `rate_limit.py` style): read inbound `X-Request-ID` (Fly injects `Fly-Request-Id` — accept that as fallback), else `uuid4().hex`; set the contextvar; set the value on the response header `X-Request-ID`; clear on exit.
   - `class ContextLogFilter(logging.Filter)`: on each record, set `record.request_id` from the contextvar and `record.academy_id` from `current_academy_id()` (guarded by `try/except TenantContextUnset` — mirror `backend/v2/composition/coach.py:238-243`). Leave `user_id` for a follow-up unless the auth claims are already reachable from a contextvar.
4. **New module** `backend/v2/shared/observability/errors.py`: `configure_error_tracking(settings)` — if `settings.sentry_dsn`: `sentry_sdk.init(dsn=..., environment=settings.env, traces_sample_rate=settings.sentry_traces_sample_rate, integrations=[FastApiIntegration(), ...defaults])`. Import guarded like `tracing.py:20-29` so tests/dev without the package still boot.
5. **Wire it** in `backend/v2/main.py`:
   - `configure_error_tracking(get_settings())` at the top of `create_app()` (before middleware, :551-558 region).
   - `app.add_middleware(RequestContextMiddleware)` added **after** `_LazyTenancyMiddleware` in code order at :564 so it runs outermost... note Starlette ordering: last-added runs first. Add it last so request-id exists before tenancy/rate-limit run and appears on 429/401 responses too.
   - In the middleware (or a small Sentry `before_send`/scope hook), call `sentry_sdk.get_isolation_scope().set_tag("request_id", rid)` and set `academy_id` tag once tenancy resolves (cheap: set both tags inside `ContextLogFilter`'s sibling helper invoked from the middleware after `call_next` starts, or use a Sentry event processor reading the contextvars — prefer the event processor: registered once in `configure_error_tracking`, reads both contextvars at event time).
   - In `configure_logging()` (`logging.py:36-49`) attach `ContextLogFilter` to the handler.
6. **Frontend (optional, same PR if green)**: `pnpm add @sentry/nextjs` in `frontend/`, `instrumentation.ts` per Sentry Next.js/OpenNext docs, DSN via `NEXT_PUBLIC_SENTRY_DSN`. The BFF proxy (`frontend/app/api/v2/[...path]/route.ts:21`) already copies inbound headers through, so a request-ID generated by the backend flows back; optionally have the proxy set `X-Request-ID` if absent so browser→worker→backend share one id.
7. **Env/deploy**: set `V2_SENTRY_DSN` (staging + prod) via `fly secrets set`; document in the release note. No value ⇒ Sentry disabled ⇒ current behavior (safe default for dev/test/CI).

## Files to change

- `backend/requirements.txt`
- `backend/v2/shared/config/settings.py`
- `backend/v2/shared/observability/request_context.py` (new)
- `backend/v2/shared/observability/errors.py` (new)
- `backend/v2/shared/observability/__init__.py` (export new symbols)
- `backend/v2/shared/observability/logging.py` (attach filter)
- `backend/v2/main.py` (wire init + middleware)
- Frontend (optional): `frontend/package.json`, `frontend/instrumentation.ts`, `frontend/app/api/v2/[...path]/route.ts`

## Tests & verification

New tests (`backend/v2/tests/unit/test_request_context.py` + extend interface tests):

- Middleware generates a request id when absent and echoes inbound `X-Request-ID`.
- Response carries `X-Request-ID`.
- `ContextLogFilter` stamps `request_id` and, inside `tenant_scope(...)`, `academy_id` onto records; JSON formatter output contains both.
- Sentry init is skipped when `sentry_dsn` is None (no import error when package present but DSN unset).

Commands:

```bash
cd backend && pytest v2/tests -q
cd backend && ruff check v2 && lint-imports --config pyproject.toml
```

**Definition of done (staging):** trigger a deliberate 500 in staging (e.g. temporary debug route or a known failing path); the event appears in Sentry with `environment=staging`, tags `request_id` and `academy_id`, and the same `request_id` is greppable in Fly logs (`fly logs | grep <rid>`).

Log via `scripts/dev/test_result.py log` per AGENTS.md.

## Risks / rollback

- **BaseHTTPMiddleware + streaming**: adding another BaseHTTPMiddleware can interfere with streaming responses; the API returns JSON only, and `rate_limit.py` already uses BaseHTTPMiddleware, so the pattern is established. Use pure ASGI if any issue appears.
- **PII in Sentry**: default `send_default_pii=False` (do not enable); events carry ids/tags, not payloads.
- **Sentry SDK overhead/outage**: SDK is fail-open (drops events, never blocks requests). DSN unset disables everything.
- Rollback: unset `V2_SENTRY_DSN` (instant, no deploy) or revert the PR; no schema/data changes.

## PR checklist

- [ ] Release note in docs/release-notes/ (per AGENTS.md)
- [ ] TRACKER.md status updated
- [ ] This plan's Status line flipped to DONE
