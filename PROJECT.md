# PROJECT.md — CourtMastr Academy Manager

*A deep knowledge transfer, first written 2026-07-07 and re-verified against `main` on 2026-11-26 (PR #1243). Read this before touching anything. If code and this file disagree, the code wins; fix this file in the same PR. Operational commands and rules live in CLAUDE.md/AGENTS.md; known weaknesses live in GAPS.md.*

---

## 1. What this is

CourtMastr Academy Manager is a hosted, multi-tenant SaaS platform for racquet-sports academies (badminton, tennis). It replaces the spreadsheets, WhatsApp groups, and manual receipts an academy typically runs on with one role-aware system:

- **Admins/owners** manage programs, sessions, enrollments, invoices, payouts, reports, and settings.
- **Coaches** get a mobile-first PWA for daily rosters, attendance check-in, lesson plans, and student skill progress.
- **Parents** get a self-serve portal: schedules, payments (Stripe), attendance, progress, absence/makeup/trial requests, self-cancel.
- **Platform** (CourtMastr staff) routes for tenant lifecycle, governance, and platform billing. They are **on** in production (`ENABLE_PLATFORM_ROUTES=true`).
- **Owner** (multi-academy rollup) and **student** self-login personas exist in code but stay off behind flags (issue #779).

Native **iOS and Android apps** wrap the deployed web app with Capacitor (`mobile/`, app id `com.courtmastr.academy`). They add push notifications (FCM) and an opt-in biometric app lock.

It is proprietary (Marvy Labs), production-live at `academy.courtmastr.com` / `api.academy.courtmastr.com`. Since PR #1212 (2026-11-18) production runs in **multi-academy SaaS mode** (`APP_TENANCY_MODE=multi_academy`, `V2_SAAS_MODE=true` in `backend/fly.toml`). The request host picks the academy. Two academies are live: BLNO Badminton (`acad_blno_badminton`, at `blno-academy.courtmastr.com`; still `PRIMARY_ACADEMY_ID`) and the **Demo Academy** (`demo-academy.courtmastr.com`), seeded for app store reviewers by `backend/scripts/seed_demo_academy.py`. BLNO is also the **house academy** (`HOUSE_ACADEMY_ID`): the one academy whose charges land on the platform Stripe account. Every other academy must charge through its own connected account. Before November most code paths were written for one tenant; leftover single-academy adapters explain many of the odd things you'll find.

## 2. Tech stack and why

| Layer | Tech | Why (inferred) |
|---|---|---|
| Backend API | FastAPI + Uvicorn, Python 3.12 | Async-first, Pydantic-native; the DDD/use-case style maps cleanly onto FastAPI dependency injection. |
| Database | MongoDB (Atlas prod, Docker/local dev) via Motor | Document model fits per-academy aggregates; no ORM. Tenancy enforced in a repository base class, not the DB. |
| Auth | Firebase Authentication (Google + email/password) | Offloads credential handling; server verifies ID tokens with revocation checks. Legacy password auth and the parent magic-link sign-in were removed (#1219). |
| Payments | Stripe (`stripe==16.1.0`): Checkout Sessions, PaymentIntents, Connect direct charges on each academy's account, Accounts v2 | Full payments stack without PCI scope; Connect lets each academy receive funds while the platform orchestrates. |
| Email | Resend | Simple transactional email; hard-blocked outside production. |
| Push | Firebase Cloud Messaging (`communications/infrastructure/fcm_push_send_port.py`) | Reaches the native apps; notifications deep-link to the exact message or class date (#1232). |
| AI | Anthropic Messages API over plain `httpx` (`contexts/ai/`), default `claude-haiku-5-5` | One port, a per-call audit (`ai_calls`) and hard monthly/daily caps. Off unless `V2_AI_ENABLED` and `V2_ANTHROPIC_API_KEY` are set; per-academy entitlement and owner-set limits on top. |
| Errors | Sentry (backend logging integration, `@sentry/browser` on the web) | ERROR logs and unhandled exceptions reach one place. |
| Scheduler | APScheduler (in-process), ~30 jobs | Cron/interval jobs (webhook drain, dunning, monthly invoices, digests, trials, win-back, referrals) without extra infra — assumes a single Fly machine. Daily jobs run on each academy's own clock. |
| Frontend | Next.js 16 App Router + React 19, Tailwind v4, TanStack Query v5, Serwist PWA | In practice a client-rendered SPA (nearly every page is `"use client"`); App Router chosen for the deployment story, not RSC. |
| Frontend hosting | Cloudflare Workers via OpenNext (`academy-next` worker) | Edge global delivery + wildcard `*.courtmastr.com` routes = per-tenant subdomains for SaaS. |
| Backend hosting | Fly.io app `courtmastr-academy-api`, region `ord`, 1 machine (`min_machines_running = 1`, no auto-stop) | Cheap, simple; single-machine assumption is baked into the scheduler/outbox design. |
| CI/CD | GitHub Actions (`.github/workflows/production.yml`, plus nightly e2e, mobile build check, index drift audit, weekly restore drill, release notes) with a manual production approval gate | One control plane: validate → approve → migrate (dry-run, then Fly `release_command`) → deploy backend (Fly) + frontend (Cloudflare) → smoke. |

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
   ├─ interfaces/  (persona BFF routers: admin, coach, parent, platform, owner, student,
   │               public pages, /me, /registration, calendar feed, email webhooks)
   ├─ contexts/    (12 DDD contexts: ai, billing, coaching, communications, crm, curriculum,
   │               enrollment, finance, identity, onboarding, platform, student_progress)
   ├─ composition/ (wiring in main.py lifespan + ~100 composition/*.py modules)
   └─ shared/      (tenancy, auth, events/outbox, config, http)
   │
   ▼
MongoDB ── Firebase Auth/FCM ── Stripe ── Resend ── Anthropic ── Sentry
```

The Capacitor apps in `mobile/` load the same deployed web app (`server.url`), so they share this whole path.

**Critical fact #1: there is no legacy backend.** The old FastAPI app (`backend/server.py`, `backend/routers/`, `backend/services/`) was deleted wholesale in commit `7228e5de` ("Remove legacy backend runtime (#120)", May 2026). The leftover `backend/routers/` and `backend/services/` bytecode directories have since been deleted too. Everything outside `backend/v2/` is now config (`Dockerfile`, `fly.toml`) and standalone operational scripts (`backend/scripts/`: seeding, Demo Academy seed, BLNO data import, legacy-payment migration, launch-readiness and data audits, multi-academy and tenant-host pre-flights, backup/restore). When code or docs say "legacy," they usually mean either (a) the deleted app (history only), or (b) *single-tenant compatibility adapters inside v2* like `_LegacyUserMembershipAdapter` — a confusing overload.

### 3.2 Backend v2: Clean-Architecture-Lite DDD

Each context is `contexts/<name>/{domain,application,infrastructure}/`. Layering is machine-enforced:

- **import-linter** contracts in `backend/pyproject.toml` (`[tool.importlinter]`): domain is pure; application never imports infrastructure; interfaces reach domain only transitively through application. Governed by ADR-0005.
- **Structural pytest tests** enforce the rest: no cross-context imports (`backend/v2/tests/structural/test_layering.py`), no raw academy_id literals (ADR-0006), no raw tenant Mongo access (`test_no_raw_tenant_mongo_access.py`), production wiring (`test_saas_production_wiring.py`).

`application/ports.py` holds Protocols; `application/use_cases/` holds one class per use case; `infrastructure/` holds Mongo repos and gateways. Interfaces are **persona-shaped BFF routes** (never generic CRUD): `interfaces/{admin,coach,parent,platform,owner,student}/` each aggregate per-resource route files under a router with `require_persona(...)` — which returns **404, not 403**, on wrong persona so route existence isn't leaked (see `docs/security-matrix.md`, the authoritative persona × action matrix with mandatory negative tests).

Routes read pre-composed use cases from `request.app.state.{admin,coach,parent}` — wired once in `main.py`'s `_lifespan` (the composition root; `main.py` is now ~3,500 lines) and `composition/` (`admin.py` ~4,500 lines, `parent.py` ~3,400, `coach.py` ~700, plus ~100 smaller per-feature modules).

**Cross-context communication** is via a durable event outbox (`shared/events/`): events written to `outbox_events` in the aggregate write, an `EventDispatcher` polls/claims/dispatches with exponential backoff and a dead-letter collection, deduped per `(event_id, handler)`. Handlers live in `composition/event_handlers.py` (e.g. PaymentSucceeded → onboarding transition; CapacityExceeded → auto-refund; EnrollmentCancelled → waitlist promotion).

### 3.3 Multi-tenancy (the load-bearing subsystem)

- **Resolution** (`shared/tenancy/resolver.py`, ADR-0007): subdomain → custom domain (`academy_domains` collection) → approved internal header. Never inferred from the user; never falls back to `default_academy_id` in SaaS paths.
- **`TenancyMiddleware`** (`shared/auth/middleware.py`) resolves the tenant, verifies the Firebase bearer token (accepted from `Authorization`, `x-courtmastr-auth`, or `x-courtmastr-identity`), loads `AuthClaims` (global user + **active `AcademyMembership`** for the resolved academy + platform roles), and sets a **ContextVar** with the academy id.
- **`TenantScopedRepository`** (`shared/tenancy/repository.py`) is the base class for every tenant-owned repo: `_scoped()` injects `academy_id = current_academy_id()` into every filter and insert. Application code never sees academy_id.
- **Identity model** (`contexts/identity/domain/models.py`): global `User` (no tenancy) + `AcademyMembership` (per-academy roles admin/coach/parent) + `PlatformRole`. `MongoMembershipRepository` deliberately does *not* extend TenantScopedRepository because it runs before the ContextVar is set.
- **Two regimes still exist in code**: `saas_mode` (real resolver + `MongoMembershipRepository`) vs. single-academy (`APP_TENANCY_MODE=single_academy`, `_LegacyUserMembershipAdapter` in `main.py` synthesizing memberships from plain users). **Production now runs the SaaS regime.** The single-academy branch survives for local dev and tests. The switch procedure and pre-flight are in `docs/runbooks/enable-multi-academy.md` (`python -m backend.scripts.multi_academy_preflight`).
- **Startup guard (issue #532):** composing the parent BFF with `saas_mode` + `multi_academy` fails closed unless `V2_ALLOW_STATIC_TENANT_PARENT_WIRING=true`. Production sets it as the recorded owner decision. What it acknowledges: `MongoUserRepository(default_academy_id=...)` still falls back to the boot academy for legacy `users` rows that carry no `academy_id`. Config resolution is two-tier: `V2_`-prefixed env vars with fallback to legacy un-prefixed names (`MONGO_URL`, `STRIPE_API_KEY`, …) via a model_validator in `shared/config/settings.py`.

**Known pitfall (the closure lesson):** composition-time closures that capture `academy_id` at boot are wrong in a multi-tenant process. The coach and parent write paths were moved onto request-time tenant providers (audit C4, #317), and the admin report and payout read models moved into context infrastructure (MT1). What remains is the `users` fallback above: the boot academy passed to `MongoUserRepository` in `composition/admin.py`, `composition/coach.py` and `main.py`. Any new code must read tenant from the ContextVar at execution time, never from a boot-time closure.

**Tenant-scope guard:** `backend/v2/tests/test_no_raw_tenant_mongo_access.py` scans all of v2, including `composition/`, and fails on a raw `db["<tenant collection>"]` call without a visible `academy_id`/`_scoped(` signal. Raw reads that carry `current_academy_id()` (common in `composition/parent.py`) pass by design. The allowlist is one transitional entry (`interfaces/admin/progress_routes.py`) plus documented by-design cross-tenant readers.

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
6. **One charge-routing rule** (`decide_charge_route` in `contexts/billing/domain/charge_route.py`) serves every charge path. The **house academy** (`HOUSE_ACADEMY_ID`, BLNO, which owns the platform Stripe account) charges on the platform account. Every other academy takes **direct charges on its own connected account** (Stripe-Account header), and only once that account is ready for charges and supports direct charges. Otherwise the charge is refused (`no_account`, `account_not_ready`, `account_platform_liable`). `allow_platform_charge_fallback` is now derived on read from `HOUSE_ACADEMY_ID` (true for the house academy only) and is read-only to admins (`infrastructure/house_academy.py`). The stored per-academy value is honoured only when `HOUSE_ACADEMY_ID` is unset (local, staging, tests). The platform fee is a per-academy `application_fee_bps` set by platform staff (`interfaces/platform/application_fee_routes.py`, `use_cases/application_fee.py`). New academies start at 100 bps (`NEW_ACADEMY_APPLICATION_FEE_BPS`); existing academies keep their stored value, 0 if none. It is sent as `application_fee_amount` only on connected-account charges.
7. **Autopay** charges on an academy-configured charge day; the first charge is the attempt-0 rung of the dunning ladder, not a separate job, so an invoice cannot be charged twice. Bank returns, missing methods and idempotency conflicts park the charge instead of retrying blindly. Family autopay can combine a family's due invoices into one payment (#1184).
8. **Credits and offers:** sibling discounts, a referral programme with held, exactly-once credits, class-cancellation credits, and per-method card processing fees (ADR-0013) are all invoice lines or credit-ledger rows, never ad-hoc totals.

The Stripe SDK is only ever imported in `infrastructure/stripe_gateway.py` (anti-corruption layer); tests fake the `StripeGateway` Protocol.

Separately, `contexts/platform/billing/` models what *CourtMastr charges academies* (plans, tenant subscriptions, cancelled at Stripe when a tenant is offboarded) — do not confuse it with parent tuition. Coach payroll (per-session rates, revenue share on invoiced tuition, atomic payout periods) lives in `contexts/finance/`.

### 3.5 Frontend

Single Next.js app with route groups `(marketing)`, `(admin)` (desktop-first, now phone-ready lists), `(coach)` and `(parent)` (mobile-first, bottom tabs), `(platform)`, `(owner)` and `(student)` (the last two flag-gated), and `(shared)` (`/calendar`, `/messages`). Auth guarding is two-layer: an **edge `frontend/middleware.ts`** (#451) settles "no session" and "wrong persona hint" from cookies before the shell paints, then the client guard (`lib/auth/use-persona-auth.ts`: Firebase auth state → `GET /me` → role check) does the rest. The backend's 404-on-wrong-persona remains the real gate. `(shared)/layout.tsx` checks only signed-in, not role. Data fetching is TanStack Query v5 with centralized query keys (`lib/query/keys.ts`); forms are plain controlled state (no form library). The design system is "Rally" (`components/ds/`) over a custom Tailwind palette (`globals.css` derives `--rally-*` from the Tailwind config). API types are generated from the backend OpenAPI snapshot (`lib/api/generated/v2.d.ts`) and CI checks them against the backend contract (#1144). PWA via Serwist: coach today/sessions GETs cached SWR. Coach **attendance writes now queue offline** (`lib/offline/attendance-queue.ts`, sync status shown to the coach since #1228); other offline writes are not queued.

The frontend never talks to the backend cross-origin from the browser: it calls same-origin `/api/v2/*`, and the catch-all proxy route forwards to `BFF_API_ORIGIN`, translating a custom identity header/cookie (`X-CourtMastr-Identity` / `__cm_identity`) into `Authorization` upstream.

### 3.6 Migrations

`backend/v2/migrations/` — ~160 numbered modules (`0001`–`0248`, sparse), each exporting `version` + `async up(db)`; a registry collection (`v2_migrations`, unique index since `0156`) tracks applied versions. **Production applies them in the deploy pipeline, not on boot:** the `migrate-production` job dry-runs them and the Fly `[deploy] release_command` applies them on the new image before traffic moves (`docs/runbooks/migrations-rollout.md`). `fly.toml` sets `V2_RUN_MIGRATIONS_ON_BOOT=false`. Migrations are the **only** sanctioned way to create indexes/validators; a weekly index drift audit workflow checks production indexes against them. Beware: duplicate numeric prefixes exist at seven numbers (`0070`, `0145`, `0156`, `0165`, `0176`, `0179` ×3, `0180`).

## 4. Key design decisions and their reasoning

1. **Strangler fig, then amputation.** v2 was built alongside the legacy app behind edge routing; once parity was reached, the legacy runtime was deleted outright rather than left to rot. The same pattern is mid-flight *inside* billing (legacy `Payment` → AR ledger, delete-last).
2. **Persona BFF over generic REST.** Each persona gets routes shaped for its screens. This keeps authorization coarse and auditable (the security matrix) and keeps business truth in the backend.
3. **Tenancy by ContextVar + repository base class, not by DB.** Cheap and uniform, but purely conventional — hence the structural tests that ban raw Mongo access and academy_id literals. Treat those tests as load-bearing.
4. **404-on-wrong-persona.** Deliberate information-hiding; don't "fix" it to 403.
5. **Webhook-owned money truth with receive-fast/drain-async.** Stripe events are accepted quickly and processed by a scheduler with quarantine, because payment processing must never be dropped, duplicated, or trusted from a redirect.
6. **Single-machine simplicity accepted on purpose.** In-process APScheduler, in-memory rate limiting, outbox dispatcher without leader election — all fine at one Fly machine, all documented hazards at two.
7. **Feature flags as launch gates**, not experiments: `ENABLE_OWNER_ROLE` and `ENABLE_STUDENT_LOGIN` are off in production, holding back whole personas; `ENABLE_PLATFORM_ROUTES` was switched on with multi-academy mode. Tenancy flags change only through a reviewed `fly.toml` PR and an approved deploy, never `fly secrets set`.
8. **Heavyweight verification culture.** Lefthook runs gitleaks, ruff and eslint on commit; `scripts/dev/install-hooks.sh` installs a light local pre-push gate (`scripts/dev/pre-push-checks.sh`, #1177); CI is the full gate. An audit-inventory manifest test forces every new route to be registered for audit coverage, and a launch-readiness audit harness (`scripts/dev/audit_inventory_*.py`, `saas_staging.sh audit-*`) gates tenant launches.

## 5. Critical paths — what's load-bearing

**Handle with maximum care (money/auth/tenancy):**
- `backend/v2/shared/tenancy/` (context, resolver, repository) and `shared/auth/middleware.py` — every request's tenant + identity flows through here.
- `contexts/identity/application/use_cases/load_auth_claims.py` — token verification, email-verification enforcement, membership check.
- `contexts/billing/application/use_cases/handle_webhook_event.py` and `infrastructure/stripe_gateway.py`, `mongo_stripe_dedup.py`, `mongo_billing_ledger_repo.py` — the money truth.
- `contexts/billing/domain/ledger.py` — pure allocation math and invoice invariants.
- `backend/v2/main.py` — the composition root; a mistake here mis-wires everything.
- `backend/v2/migrations/` — runs against production data in the deploy `release_command`.
- `backend/fly.toml` — tenancy mode, `HOUSE_ACADEMY_ID` and launch flags; changing them moves money or tenants.
- `frontend/app/api/v2/[...path]/route.ts` + `frontend/lib/api/proxy-headers.ts` — the auth bridge.

**Change with normal care:** context use cases, interface route files, frontend pages/components, the Rally DS.

**Safe to change casually:** docs (except `docs/security-matrix.md` and ADRs), seed scripts, `docs/test-results/`, marketing pages.

**Do not touch without reading history:** `backend/scripts/archive_legacy_payments.py` (destructive, manual, Phase 5 of payment retirement), anything under `.worktrees/` or `.claude/worktrees/` if a local checkout has them (parallel in-flight branches, not canonical source).

## 6. Things that will trip up a newcomer

1. **There is only one backend**, `backend.v2.main:app`. Old docs that mention `backend/routers/`, `backend/services/` or legacy `/api/*` describe the deleted app.
2. **"legacy" is overloaded** — deleted app vs. single-tenant adapters inside v2 vs. legacy `Payment` model inside billing. Three different things. Likewise "single-academy" in older docs usually describes production before #1212.
3. **Almost every frontend page is `"use client"`** despite App Router — expect SPA mental model, not RSC.
4. **The Stripe webhook lives on the parent router** (`/api/v2/parent/webhooks/stripe`) with signature-as-auth, and events are *processed* by a scheduler job, not in the request.
5. **Env config is two-tier**: `V2_FOO` falls back to `FOO`. Grep both names before concluding a variable is unused.
6. **Migration `0128` is imported via `importlib`** (module name starts with a digit) — not greppable as a normal import.
7. **Most E2E specs run under `NEXT_PUBLIC_E2E_AUTH_BYPASS=1`** with a fake Firebase user. A blocking CI step runs `real-backend-journeys.spec.ts` with real auth against a real backend (`playwright.ci-real-auth.config.ts`, #1145/#1147), covering money and attendance journeys and exact-404 cross-family reads.
8. **Coverage gate is `--cov=v2` at 86%.** mypy is blocking against a frozen baseline (`backend/mypy-baseline.txt`): only new errors fail. `backend/scripts/` and tests are still excluded from ruff.
9. **`AdminUseCases` (`interfaces/admin/deps.py`) is a ~200-field service locator** with ~65 fields still typed `object | None` — don't expect the type checker to help you on the admin surface.
10. **`docs/` has ~970 markdown files** (much of it release notes, test results and plans). The authoritative ones: `docs/security-matrix.md`, `docs/adr/`, `docs/agent/*`, `docs/testing.md`. Most of the rest is historical ledger/retro material.
11. **PYTHONPATH quirk:** backend modules are addressed `backend.v2.*`; run from repo root (Docker sets `PYTHONPATH=/app:/app/backend`).
12. **Seeding is idempotent-by-count** (checks whether `academies` is empty) — a partially seeded DB silently skips reseeding.
