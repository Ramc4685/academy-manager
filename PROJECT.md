# PROJECT.md — CourtMastr Academy Manager

*A one-time deep knowledge transfer, written 2026-07-07 from a full fresh exploration of the codebase. Read this before touching anything. Operational commands and rules live in CLAUDE.md/AGENTS.md; known weaknesses live in GAPS.md.*

---

## 1. What this is

CourtMastr Academy Manager is a hosted, multi-tenant SaaS platform for racquet-sports academies (badminton, tennis). It replaces the spreadsheets, WhatsApp groups, and manual receipts an academy typically runs on with one role-aware system:

- **Admins/owners** manage programs, sessions, enrollments, invoices, payouts, reports, and settings.
- **Coaches** get a mobile-first PWA for daily rosters, attendance check-in, lesson plans, and student skill progress.
- **Parents** get a self-serve portal: schedules, payments (Stripe), attendance, progress, absence/makeup/trial requests, self-cancel.
- **Platform** (CourtMastr staff) routes exist behind a flag for tenant lifecycle, governance, and platform billing.

It is proprietary (Marvy Labs), production-live at `academy.courtmastr.com` / `api.academy.courtmastr.com`. The current production deployment runs in **single-academy mode** for one real tenant, BLNO Badminton (`PRIMARY_ACADEMY_ID=acad_blno_badminton`), while the codebase is being built out to full SaaS multi-tenancy. That tension — "SaaS-shaped code, single-tenant production" — explains most of the odd things you'll find.

## 2. Tech stack and why

| Layer | Tech | Why (inferred) |
|---|---|---|
| Backend API | FastAPI + Uvicorn, Python 3.12 | Async-first, Pydantic-native; the DDD/use-case style maps cleanly onto FastAPI dependency injection. |
| Database | MongoDB (Atlas prod, Docker/local dev) via Motor | Document model fits per-academy aggregates; no ORM. Tenancy enforced in a repository base class, not the DB. |
| Auth | Firebase Authentication (Google + email/password) | Offloads credential handling; server verifies ID tokens with revocation checks. Legacy password auth was removed. |
| Payments | Stripe: Checkout Sessions, PaymentIntents, Connect destination charges, Accounts v2 | Full payments stack without PCI scope; Connect lets each academy receive funds while the platform orchestrates. |
| Email | Resend | Simple transactional email; hard-blocked outside production. |
| Scheduler | APScheduler (in-process) | Cron/interval jobs (webhook drain, dunning, digests) without extra infra — assumes a single Fly machine. |
| Frontend | Next.js 15 App Router + React 19, Tailwind v4, TanStack Query v5, Serwist PWA | In practice a client-rendered SPA (nearly every page is `"use client"`); App Router chosen for the deployment story, not RSC. |
| Frontend hosting | Cloudflare Workers via OpenNext (`academy-next` worker) | Edge global delivery + wildcard `*.courtmastr.com` routes = per-tenant subdomains for SaaS. |
| Backend hosting | Fly.io app `courtmastr-academy-api`, region `ord`, 1 machine | Cheap, simple; single-machine assumption is baked into the scheduler/outbox design. |
| CI/CD | GitHub Actions (`.github/workflows/production.yml`), manual production approval gate | One control plane: validate → approve → deploy backend (Fly) + frontend (Cloudflare) → smoke. |

## 3. Architecture

### 3.1 The big picture

```
Browser / PWA
   │
   ▼
Cloudflare Worker "academy-next" (Next.js via OpenNext)
   │  routes: academy.courtmastr.com/*  and  *.courtmastr.com/*  (tenant subdomains)
   │
   ├─ same-origin /api/v2/[...path] catch-all proxy (frontend/app/api/v2/[...path]/route.ts)
   │      rewrites identity header/cookie → Authorization for upstream
   ▼
FastAPI  backend.v2.main:app  on Fly.io          ← THE ONLY BACKEND
   │  all routes under /api/v2/*
   │  TenancyMiddleware: resolve tenant → load auth claims → set ContextVar
   │
   ├─ interfaces/  (persona BFF routers: admin, coach, parent, platform, /me, /registration)
   ├─ contexts/    (10 DDD contexts: billing, enrollment, identity, coaching, finance,
   │               communications, curriculum, student_progress, onboarding, platform)
   ├─ composition/ (wiring in main.py lifespan + composition/{admin,coach,parent}.py)
   └─ shared/      (tenancy, auth, events/outbox, config, http)
   │
   ▼
MongoDB ── Firebase Auth ── Stripe ── Resend
```

**Critical fact #1: there is no legacy backend.** The old FastAPI app (`backend/server.py`, `backend/routers/`, `backend/services/`) was deleted wholesale in commit `7228e5de` ("Remove legacy backend runtime (#120)", May 2026). The `backend/routers/` and `backend/services/` directories still exist on disk but contain **only orphaned `.pyc` bytecode** — do not reason from them. Everything outside `backend/v2/` is now config (`Dockerfile`, `fly.toml`) and standalone operational scripts (`backend/scripts/`: seeding, BLNO data import, legacy-payment migration, launch-readiness audit). When code or docs say "legacy," they usually mean either (a) the deleted app (history only), or (b) *single-tenant compatibility adapters inside v2* like `_LegacyUserMembershipAdapter` — a confusing overload.

### 3.2 Backend v2: Clean-Architecture-Lite DDD

Each context is `contexts/<name>/{domain,application,infrastructure}/`. Layering is machine-enforced:

- **import-linter** contracts in `backend/pyproject.toml` (`[tool.importlinter]`): domain is pure; application never imports infrastructure; interfaces reach domain only transitively through application. Governed by ADR-0005.
- **Structural pytest tests** enforce the rest: no cross-context imports (`backend/v2/tests/structural/test_layering.py`), no raw academy_id literals (ADR-0006), no raw tenant Mongo access (`test_no_raw_tenant_mongo_access.py`), production wiring (`test_saas_production_wiring.py`).

`application/ports.py` holds Protocols; `application/use_cases/` holds one class per use case; `infrastructure/` holds Mongo repos and gateways. Interfaces are **persona-shaped BFF routes** (never generic CRUD): `interfaces/{admin,coach,parent,platform}/` each aggregate per-resource route files under a router with `require_persona(...)` — which returns **404, not 403**, on wrong persona so route existence isn't leaked (see `docs/security-matrix.md`, the authoritative persona × action matrix with mandatory negative tests).

Routes read pre-composed use cases from `request.app.state.{admin,coach,parent}` — wired once in `main.py`'s `_lifespan` (the composition root, ~800 lines) and `composition/{admin,coach,parent}.py`.

**Cross-context communication** is via a durable event outbox (`shared/events/`): events written to `outbox_events` in the aggregate write, an `EventDispatcher` polls/claims/dispatches with exponential backoff and a dead-letter collection, deduped per `(event_id, handler)`. Handlers live in `composition/event_handlers.py` (e.g. PaymentSucceeded → onboarding transition; CapacityExceeded → auto-refund; EnrollmentCancelled → waitlist promotion).

### 3.3 Multi-tenancy (the load-bearing subsystem)

- **Resolution** (`shared/tenancy/resolver.py`, ADR-0007): subdomain → custom domain (`academy_domains` collection) → approved internal header. Never inferred from the user; never falls back to `default_academy_id` in SaaS paths.
- **`TenancyMiddleware`** (`shared/auth/middleware.py`) resolves the tenant, verifies the Firebase bearer token (accepted from `Authorization`, `x-courtmastr-auth`, or `x-courtmastr-identity`), loads `AuthClaims` (global user + **active `AcademyMembership`** for the resolved academy + platform roles), and sets a **ContextVar** with the academy id.
- **`TenantScopedRepository`** (`shared/tenancy/repository.py`) is the base class for every tenant-owned repo: `_scoped()` injects `academy_id = current_academy_id()` into every filter and insert. Application code never sees academy_id.
- **Identity model** (`contexts/identity/domain/models.py`): global `User` (no tenancy) + `AcademyMembership` (per-academy roles admin/coach/parent) + `PlatformRole`. `MongoMembershipRepository` deliberately does *not* extend TenantScopedRepository because it runs before the ContextVar is set.
- **Two regimes coexist**: `saas_mode` (real resolver + memberships) vs. single-academy production (`APP_TENANCY_MODE=single_academy`, `_LegacyUserMembershipAdapter` synthesizing memberships from plain users). Config resolution is two-tier: `V2_`-prefixed env vars with fallback to legacy un-prefixed names (`MONGO_URL`, `STRIPE_API_KEY`, …) via a model_validator in `shared/config/settings.py`.

**Known pitfall (the closure lesson):** composition-time closures that capture `academy_id` at boot are wrong in a multi-tenant process. Some coach write paths still bake in `default_academy_id` (explicit TODO at `backend/v2/composition/coach.py:371`); the parent self-cancel fee path was already fixed to read `current_academy_id()` at request time (`composition/parent.py:645`). Any new code must read tenant from the ContextVar at execution time, never from a boot-time closure.

### 3.4 Billing (the most intricate subsystem)

All in `contexts/billing/`. Two worldviews coexist mid-strangler-fig (ADR-0011, ADR-0012):

- **Legacy `Payment`** aggregate → `payments` collection. Flat, one amount, one status.
- **AR ledger** (target model): `LedgerInvoice` + `InvoiceLine` (`invoices`/`invoice_lines`), `LedgerPayment` + `PaymentAllocation` (`ledger_payments`/`payment_allocations`), overpayment credits (`account_credit_ledger`), `payment_attempts` (audit-only telemetry, never financial truth).

Money-truth invariants, actually enforced in code:

1. **The app ledger owns invoices; Stripe owns collection.** Invoice totals are always derived (`recompute_totals`); callers never set them.
2. **Redirects never prove payment.** Checkout return URLs write nothing; all ledger writes happen in webhook handlers (or reconciliation).
3. **Webhooks are verified, deduped, and drained async.** Signature check against platform + Connect secrets → insert-first dedup lock (`stripe_webhook_events`) → 200 immediately → a 60s scheduler job claims and processes, with backoff and quarantine. Handlers **re-fetch live Stripe state** rather than trusting the delivered payload.
4. **Idempotency everywhere** via deterministic keys (`autopay-pi:{pi}`, `invoice-checkout:{cs}`, …); allocation uses a compare-and-swap on `(status, balance_due_cents)` and rolls back on conflict.
5. **Fail closed.** Unknown/mismatched Connect accounts, livemode mismatches, and academy/parent/currency mismatches quarantine the event. Autopay refuses to charge unless the enrollment's autopay status is `active`.
6. **Destination charges** route funds to the academy's connected account (`on_behalf_of` + `transfer_data.destination`, `application_fee_amount=0` — the platform takes no Stripe fee; monetization is out-of-band). A **temporary, admin-togglable `allow_platform_charge_fallback`** lets checkout charge the platform account when the connected account isn't activated (the 2026-07 production 502 workaround).

The Stripe SDK is only ever imported in `infrastructure/stripe_gateway.py` (anti-corruption layer); tests fake the `StripeGateway` Protocol.

Separately, `contexts/platform/billing/` models what *CourtMastr charges academies* (plans, tenant subscriptions) — do not confuse it with parent tuition.

### 3.5 Frontend

Single Next.js app, four route groups: `(marketing)`, `(admin)` (~37 pages, desktop), `(coach)` and `(parent)` (mobile-first, bottom tabs), `(shared)` (`/calendar`, `/messages`). Auth guards are **client-side only** (`lib/auth/use-persona-auth.ts`; no middleware.ts): Firebase auth state → `GET /me` → role check → redirect. Data fetching is TanStack Query v5 with centralized query keys (`lib/query/keys.ts`); forms are plain controlled state (no form library). The design system is "Rally" (`components/ds/`) over a custom Tailwind palette. PWA via Serwist: coach today/sessions GETs cached SWR, attendance writes NetworkOnly; offline *write* queue (Wave 1B) is scaffolded but intentionally inert.

The frontend never talks to the backend cross-origin from the browser: it calls same-origin `/api/v2/*`, and the catch-all proxy route forwards to `BFF_API_ORIGIN`, translating a custom identity header/cookie (`X-CourtMastr-Identity` / `__cm_identity`) into `Authorization` upstream.

### 3.6 Migrations

`backend/v2/migrations/` — 56 numbered modules (`0001`–`0145`, sparse), each exporting `version` + `async up(db)`; a registry collection (`v2_migrations`) tracks applied versions; run on boot when `V2_RUN_MIGRATIONS_ON_BOOT=true` (prod does). Migrations are the **only** sanctioned way to create indexes/validators. Beware: duplicate numeric prefixes exist (two `0070_*`, two `0145_*`) and one module's version string is bare `"0070"`.

## 4. Key design decisions and their reasoning

1. **Strangler fig, then amputation.** v2 was built alongside the legacy app behind edge routing; once parity was reached, the legacy runtime was deleted outright rather than left to rot. The same pattern is mid-flight *inside* billing (legacy `Payment` → AR ledger, delete-last).
2. **Persona BFF over generic REST.** Each persona gets routes shaped for its screens. This keeps authorization coarse and auditable (the security matrix) and keeps business truth in the backend.
3. **Tenancy by ContextVar + repository base class, not by DB.** Cheap and uniform, but purely conventional — hence the structural tests that ban raw Mongo access and academy_id literals. Treat those tests as load-bearing.
4. **404-on-wrong-persona.** Deliberate information-hiding; don't "fix" it to 403.
5. **Webhook-owned money truth with receive-fast/drain-async.** Stripe events are accepted quickly and processed by a scheduler with quarantine, because payment processing must never be dropped, duplicated, or trusted from a redirect.
6. **Single-machine simplicity accepted on purpose.** In-process APScheduler, in-memory rate limiting, outbox dispatcher without leader election — all fine at one Fly machine, all documented hazards at two.
7. **Feature flags as launch gates**, not experiments: `ENABLE_PLATFORM_ROUTES`, `ENABLE_OWNER_ROLE`, `ENABLE_STUDENT_LOGIN` are off in production; whole personas are held back.
8. **Heavyweight verification culture.** Pre-push mirrors CI (7 checks), an audit-inventory manifest test forces every new route to be registered for audit coverage, and a launch-readiness audit harness (`scripts/dev/audit_inventory_*.py`, `saas_staging.sh audit-*`) gates tenant launches.

## 5. Critical paths — what's load-bearing

**Handle with maximum care (money/auth/tenancy):**
- `backend/v2/shared/tenancy/` (context, resolver, repository) and `shared/auth/middleware.py` — every request's tenant + identity flows through here.
- `contexts/identity/application/use_cases/load_auth_claims.py` — token verification, email-verification enforcement, membership check.
- `contexts/billing/application/use_cases/handle_webhook_event.py` and `infrastructure/stripe_gateway.py`, `mongo_stripe_dedup.py`, `mongo_billing_ledger_repo.py` — the money truth.
- `contexts/billing/domain/ledger.py` — pure allocation math and invoice invariants.
- `backend/v2/main.py` — the composition root; a mistake here mis-wires everything.
- `backend/v2/migrations/` — runs against production data on boot.
- `frontend/app/api/v2/[...path]/route.ts` + `frontend/lib/api/proxy-headers.ts` — the auth bridge.

**Change with normal care:** context use cases, interface route files, frontend pages/components, the Rally DS.

**Safe to change casually:** docs (except `docs/security-matrix.md` and ADRs), seed scripts, `docs/test-results/`, marketing pages.

**Do not touch without reading history:** `backend/scripts/archive_legacy_payments.py` (destructive, manual, Phase 5 of payment retirement), anything under `.worktrees/` or `.claude/worktrees/` (parallel in-flight branches, not canonical source).

## 6. Things that will trip up a newcomer

1. **`backend/routers/` and `backend/services/` are ghosts** — `.pyc` only; the source was deleted. The real app is `backend.v2.main:app`.
2. **"legacy" is overloaded** — deleted app vs. single-tenant adapters inside v2 vs. legacy `Payment` model inside billing. Three different things.
3. **Almost every frontend page is `"use client"`** despite App Router — expect SPA mental model, not RSC.
4. **The Stripe webhook lives on the parent router** (`/api/v2/parent/webhooks/stripe`) with signature-as-auth, and events are *processed* by a scheduler job, not in the request.
5. **Env config is two-tier**: `V2_FOO` falls back to `FOO`. Grep both names before concluding a variable is unused.
6. **Migration `0128` is imported via `importlib`** (module name starts with a digit) — not greppable as a normal import.
7. **E2E tests run under `NEXT_PUBLIC_E2E_AUTH_BYPASS=1`** with a fake Firebase user — real auth is never exercised end-to-end.
8. **Coverage gate covers only `v2/shared`** (70%); contexts/interfaces have many tests but no enforced floor. mypy is advisory in CI.
9. **`AdminUseCases` (`interfaces/admin/deps.py`) is a ~180-field service locator** mostly typed `object | None` — don't expect the type checker to help you on the admin surface.
10. **`docs/` has ~290 markdown files.** The authoritative ones: `docs/security-matrix.md`, `docs/adr/`, `docs/agent/*`, `docs/testing.md`. Most of the rest is historical ledger/retro material.
11. **PYTHONPATH quirk:** backend modules are addressed `backend.v2.*`; run from repo root (Docker sets `PYTHONPATH=/app:/app/backend`).
12. **Seeding is idempotent-by-count** (checks whether `academies` is empty) — a partially seeded DB silently skips reseeding.
