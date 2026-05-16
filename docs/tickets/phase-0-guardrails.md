# Phase 0 — Architecture Guardrails

**Goal:** Ship the contracts (ADRs + policy docs) and the empty-but-runnable v2 skeleton (backend + frontend + edge routing + CI) before any Wave 1A code is written.

**Exit gate (from plan):** ADRs merged. `backend/v2/main.py` boots. `frontend-next` builds. Edge route prototype demonstrated end-to-end.

**Estimate:** ~1 week.

**Ticket ID convention:** `P0-NN`. Estimates in ideal hours.

---

## Docs & ADRs

### P0-01 — ADR-0001: FastAPI + MongoDB stay
- **Type:** Doc / ADR
- **Depends on:** —
- **Estimate:** 1h
- **Description:** Write `docs/adr/0001-fastapi-mongodb-stays.md`. Explicitly reject TS/Postgres rewrite. Cite team familiarity, existing migration scripts, Stripe webhook stability, and Mongo's fit for the current document shapes.
- **Acceptance:**
  - File exists at `docs/adr/0001-fastapi-mongodb-stays.md` with Status/Context/Decision/Consequences sections.
  - Lists three alternatives considered (TS+Postgres, Go+Postgres, Python+Postgres) with rejection reasons.
  - Approved and merged to main before P0-11 begins.

### P0-02 — ADR-0002: Next.js 15 App Router replaces CRA
- **Type:** Doc / ADR
- **Depends on:** —
- **Estimate:** 1h
- **Description:** Write `docs/adr/0002-nextjs-app-router.md`. Justify Next.js over staying on CRA and over Vite-only. Cover RSC for admin, file-routing for persona groups, built-in image optimization, PWA tooling maturity.
- **Acceptance:** ADR merged. Alternatives (CRA+PWA layer, Vite+React Router 7, Remix) listed with rejection reasons.

### P0-03 — ADR-0003: BFF lives inside the backend (one process)
- **Type:** Doc / ADR
- **Depends on:** —
- **Estimate:** 1h
- **Description:** Document why persona separation is structural (route packages) rather than deployed (three BFFs). Cover the lift-out path if/when needed.
- **Acceptance:** ADR merged with "lift-out trigger" criteria listed.

### P0-04 — ADR-0004: PWA over native, Capacitor deferred
- **Type:** Doc / ADR
- **Depends on:** —
- **Estimate:** 1h
- **Description:** Bound mobile scope. Document the triggers that would justify Capacitor (push notifications, app store presence, deep OS integration).
- **Acceptance:** ADR merged.

### P0-05 — ADR-0005: Clean-architecture-lite monolith
- **Type:** Doc / ADR
- **Depends on:** —
- **Estimate:** 1h
- **Description:** Document the four-layer rule (domain → application → infrastructure / interfaces). Explicitly reject microservices and event sourcing. List the import-linter rules that will enforce layering.
- **Acceptance:** ADR merged. Layer diagram included.

### P0-06 — ADR-0006: Tenant-ready, single-tenant shipped
- **Type:** Doc / ADR
- **Depends on:** —
- **Estimate:** 1.5h
- **Description:** Resolve the tenancy contradiction. Document: `academy_id` on every collection, repo-base-class enforcement, env-sourced `DEFAULT_ACADEMY_ID`, auth claim carrying it, tenant-isolation test per repo.
- **Acceptance:** ADR merged. References the lint rule that bans `academy_id` literals outside `shared/tenancy/` and `infrastructure/`.

### P0-07 — Security matrix doc
- **Type:** Doc
- **Depends on:** —
- **Estimate:** 2h
- **Description:** Author `docs/security-matrix.md` from the plan's §0.5 table. Each row links to the BFF route(s) it constrains. Negative-test requirement called out.
- **Acceptance:**
  - File exists; every action × persona cell has an explicit Yes / No / Conditional value.
  - "404 not 403" convention documented.
  - Linked from `README.md` and `docs/adr/0005-*.md`.

### P0-08 — Data ownership map doc
- **Type:** Doc
- **Depends on:** —
- **Estimate:** 1.5h
- **Description:** Author `docs/data-ownership.md` from plan §0.4. Lists owning context, readers, and the rule that cross-context state changes go through domain events.
- **Acceptance:** File exists, every collection touched in Wave 1A appears in the table.

### P0-09 — Event rules doc
- **Type:** Doc
- **Depends on:** —
- **Estimate:** 2h
- **Description:** Author `docs/event-rules.md` from plan §0.8. Naming, schema versioning, outbox guarantee, idempotent handlers, retry, poison messages, audit retention.
- **Acceptance:** File exists. Referenced by code under `backend/v2/shared/events/`.

### P0-10 — Offline conflict policy doc
- **Type:** Doc
- **Depends on:** —
- **Estimate:** 1.5h
- **Description:** Author `docs/offline-policy.md` from plan §0.9. Allowed/disallowed offline ops, six conflict cases with server responses, sync protocol.
- **Acceptance:** File exists. Wave 1B implementation will pin to this.

---

## Backend Skeleton

### P0-11 — Backend v2 skeleton (shared/ only)
- **Type:** Backend / Infra
- **Depends on:** P0-01, P0-05, P0-06
- **Estimate:** 6h
- **Description:** Create `backend/v2/` with `shared/{auth,events,idempotency,tenancy,observability,config,http}/` directories (empty modules), `main.py` composition root, `migrations/` runner, and `pyproject.toml` additions (`import-linter`, `pytest-asyncio`, `httpx`, `pydantic-settings`, `opentelemetry-*`). **No `contexts/` folders yet** — those land per-wave.
- **Acceptance:**
  - `backend/v2/main.py` boots, serves `GET /api/v2/healthz` returning `{"status": "ok"}`.
  - Mounted from `backend/server.py` alongside legacy under `/api/v2`.
  - `pytest backend/v2/tests/` passes (with one health test).
  - `import-linter` config in `pyproject.toml` defining the layer contract; runs in CI but has no rules to violate yet because contexts don't exist.

### P0-12 — TenantScopedRepository base class + lint rule
- **Type:** Backend / Infra
- **Depends on:** P0-06, P0-11
- **Estimate:** 4h
- **Description:** Implement `shared/tenancy/repository.py` with a `TenantScopedRepository` base class that:
  - Reads `academy_id` from a `ContextVar` set by auth middleware.
  - Injects `{"academy_id": <id>}` into every `find`, `find_one`, `update_*`, `delete_*`, and into every inserted document.
  - Raises if `academy_id` is unset.
  - Custom `import-linter` rule forbids `academy_id` string literals outside `shared/tenancy/` and `*/infrastructure/`.
- **Acceptance:**
  - Unit tests: query with wrong `academy_id` returns nothing even when documents exist; insert without scope raises.
  - Lint rule blocks a planted violation in a test PR.

### P0-13 — Outbox + dispatcher + dead-letter + audit
- **Type:** Backend / Infra
- **Depends on:** P0-09, P0-11, P0-12
- **Estimate:** 8h
- **Description:** Implement `shared/events/` per plan §0.8:
  - `outbox_events` collection write inside the same Mongo transaction as the aggregate change (helper that wraps a transactional context).
  - Background poller (asyncio task) publishes to in-process handlers.
  - Per-handler idempotency on `(event_id, handler_name)` via `event_handler_runs`.
  - Retry with exponential backoff (1, 4, 16, 64, 256s); after 5 failures move to `dead_letter_events`.
  - `event_audit` collection with 90-day TTL.
  - CLI tool `backend/v2/scripts/replay_event.py` to requeue a dead-letter event.
- **Acceptance:**
  - Integration test: simulated handler that fails 3× then succeeds — outbox marks processed, audit has 4 rows, dead-letter empty.
  - Integration test: handler that fails 5× — dead-letter receives event, audit complete.
  - Replay CLI requeues and audit shows resumed processing.

### P0-14 — Idempotency decorator + Mongo store
- **Type:** Backend / Infra
- **Depends on:** P0-11
- **Estimate:** 3h
- **Description:** Implement `shared/idempotency/`:
  - `@idempotent(key_from=callable)` decorator usable on async use-case methods.
  - `idempotency_keys` collection with unique index on `key`, TTL 7 days.
  - Stored result returned on duplicate calls.
- **Acceptance:**
  - Unit test: same key called twice → underlying function runs once; both calls return the same result.
  - Index created on boot via migration.

### P0-15 — OpenTelemetry + structured logging
- **Type:** Backend / Infra
- **Depends on:** P0-11
- **Estimate:** 4h
- **Description:** Wire OpenTelemetry FastAPI instrumentation + Mongo (motor) instrumentation. Head-based sampling 10%, errors 100%. Structured JSON logs with `trace_id`, `span_id`, `academy_id`, `user_id`, `request_id`. Trace ID returned in response header `x-trace-id`.
- **Acceptance:**
  - A request through `/api/v2/healthz` produces one trace, one span, one log line with `trace_id`.
  - OTLP exporter configurable via env (no-op in tests).

### P0-16 — Boot-time migration runner
- **Type:** Backend / Infra
- **Depends on:** P0-11
- **Estimate:** 2h
- **Description:** `backend/v2/migrations/` runner that executes ordered, idempotent migration scripts on app boot (gated by env var `V2_RUN_MIGRATIONS=1`). Records applied versions in `v2_migrations` collection.
- **Acceptance:**
  - Two seed migrations (`0001_idempotency_keys.py` creating the unique+TTL index; `0002_outbox_events.py` creating the poller index) run successfully twice without error.

---

## Frontend Skeleton

### P0-17 — frontend-next scaffold (marketing + login only)
- **Type:** Frontend / Infra
- **Depends on:** P0-02
- **Estimate:** 6h
- **Description:** Create `frontend-next/` with Next.js 15 App Router. Implement only:
  - `app/(marketing)/page.tsx` (placeholder landing).
  - `app/(marketing)/login/page.tsx` with Firebase Auth (modular imports — `firebase/auth` only).
  - `lib/auth/firebase.ts`, `lib/api/client.ts` (auth header injector, retry, dedup).
  - `lib/query/` TanStack Query provider.
  - shadcn/Radix base components (button, input, card) — minimal.
  - Tailwind config + design tokens (one source of truth for colors, spacing, touch-target min 44pt).
  - `next.config.ts` with image config and security headers.
  - **No coach/parent/admin route groups yet** — those land per-wave.
- **Acceptance:**
  - `pnpm build` clean.
  - Login form works against Firebase, lands on a placeholder `/post-login` page.
  - Lighthouse on `/login` ≥ 95 PWA-eligibility (manifest+SW will follow in P0-18).
  - `pnpm typecheck` and `pnpm lint` pass.

### P0-18 — PWA shell (manifest, service worker, install prompt plumbing)
- **Type:** Frontend / Infra
- **Depends on:** P0-04, P0-17
- **Estimate:** 6h
- **Description:** Add Serwist:
  - `public/manifest.webmanifest` with icons (180, 192, 256, 512, maskable) — placeholder icons OK for Phase 0.
  - `public/splash/` for iOS.
  - Serwist service worker with cache strategies stubbed (cache-first for static, network-only for everything else for now — real read caching lands in Wave 1A).
  - `lib/pwa/install-prompt.ts` capturing `beforeinstallprompt` and exposing a `useInstallPrompt()` hook.
  - `lib/pwa/update-flow.ts` with skip-waiting behind explicit user "Refresh" prompt.
- **Acceptance:**
  - Lighthouse PWA ≥ 90 on `/login` route, including installable check.
  - Install verified manually on real Android Chrome and iOS Safari (placeholder icons accepted).
  - Service worker only loads on `frontend-next`; legacy CRA unaffected.

### P0-19 — openapi-typescript pipeline
- **Type:** Frontend / Infra
- **Depends on:** P0-11, P0-17
- **Estimate:** 3h
- **Description:** CI step runs `openapi-typescript` against the FastAPI v2 OpenAPI JSON and writes `frontend-next/lib/api/generated/v2.d.ts`. Generated file committed. PR fails if regenerated output differs from committed file (catches drift).
- **Acceptance:**
  - `pnpm generate:api` produces `lib/api/generated/v2.d.ts`.
  - CI job `frontend-next/generate-api` fails on drift.

---

## Edge Routing

### P0-20 — Cloudflare edge routing prototype
- **Type:** Ops / Infra
- **Depends on:** P0-11, P0-17
- **Estimate:** 5h
- **Description:** Cloudflare Worker (or `_routes.json`) that:
  - Routes `/v2/*` and selected `/api/v2/*` to `frontend-next` / backend v2.
  - Falls through everything else to legacy.
  - Env-var-controlled per-path flip table (`ROUTE_COACH_TODAY=v2|legacy`) so cutovers are config-only.
  - 410 Gone path for future legacy disablement (Wave 4A).
- **Acceptance:**
  - End-to-end demo: a `/v2/login` request hits frontend-next; flipping a flag back to `legacy` returns the CRA login. No app-code changes required to flip.
  - Documented in `docs/edge-routing.md` with a runbook for cutover/rollback.

---

## CI / Quality Gates

### P0-21 — CI workflows: v2 backend + frontend
- **Type:** Ops / CI
- **Depends on:** P0-11, P0-17
- **Estimate:** 4h
- **Description:** Two GH Actions workflows:
  - `.github/workflows/v2-backend.yml`: ruff, mypy, import-linter, pytest with coverage gate (≥80% for `shared/`).
  - `.github/workflows/v2-frontend.yml`: typecheck, lint, build, generate-api drift check, size-limit (informational in Phase 0), Lighthouse CI (informational in Phase 0).
  - Both run only when their respective paths change.
- **Acceptance:** A trivial PR touching each path triggers only the relevant workflow; both green.

### P0-22 — Bundle-size + Lighthouse CI plumbing
- **Type:** Ops / CI
- **Depends on:** P0-21
- **Estimate:** 3h
- **Description:** Install `size-limit` with per-route group configs (empty thresholds for now — populated per wave after baseline). Install `@lhci/cli`, configure to run against built `frontend-next` against `/login` route. Posts PR comment with results. Marked informational until Wave 1A baselines (P0-10 policy / W1A-01).
- **Acceptance:** PR comment appears with bundle and Lighthouse numbers. No PR blocked yet.

---

## Phase 0 Exit Checklist

- [ ] P0-01 … P0-10 merged (all six ADRs + four policy docs).
- [ ] P0-11 … P0-16 merged (backend skeleton + tenancy + outbox + idempotency + telemetry + migration runner).
- [ ] P0-17 … P0-19 merged (frontend scaffold + PWA shell + OpenAPI pipeline).
- [ ] P0-20 merged (edge routing prototype demoed).
- [ ] P0-21, P0-22 merged (CI workflows running, informational gates active).
- [ ] `backend/v2/main.py` boots in prod (gated behind env flag, serving only `/healthz`).
- [ ] `frontend-next` deployed to a staging Cloudflare Pages project.
- [ ] Phase 0 retro: document any deviations from plan as ADR amendments.
