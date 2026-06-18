# Senior Architecture Review — CourtMastr Academy Manager

*Date: 2026-06-17. Read-only review — no code was changed.*
*Branch: `feat/stripe-subscription-ledger-convergence` (dirty working tree — billing convergence work in progress).*
*Method: grounded in `AGENTS.md`, `README.md`, `DEPLOYMENT.md`, `test_result.md`, `docs/adr/*`, `docs/data-ownership.md`, the active convergence plan, plus direct code inspection of `backend/v2/`, `frontend/`, and the test suites via five parallel investigation passes (DDD/boundary, billing/Stripe, frontend, tests, enrollment/coach/payout).*
*Claims are tagged **FACT** (cited) or **OPINION**.*

---

# 1. Executive Summary

**FACT.** CourtMastr Academy Manager is a hosted, multi-tenant SaaS "operating system" for racquet-sports academies (badminton/tennis), covering scheduling, enrollment, attendance, skill progression, Stripe-backed billing, coach payroll, and parent communication (`README.md:1-46`). Production runs FastAPI (Python 3.12) on Fly.io (`courtmastr-academy-api`, region `ord`) behind a Next.js 15 / React 19 PWA on Cloudflare Workers (`academy-next`), with MongoDB Atlas, Firebase Auth, Stripe (live), Resend email, and APScheduler (`README.md:55-81`).

**FACT.** The codebase is an in-progress **strangler migration**: a legacy procedural FastAPI app is being replaced workflow-by-workflow by a clean, DDD-layered `backend/v2/` (`docs/agent/architecture-rules.md:1-5`). Per `DEPLOYMENT.md:146-150`, **legacy `/api/*` auth routes are already removed and the backend boots `backend.v2.main:app` directly** — so v2 is the live runtime, not a future state.

**OPINION.** This is an unusually disciplined small-team codebase: real ADRs, an enforced data-ownership contract, import-linter layering rules in CI, a domain-event outbox, ~216 backend test files, and tenant-isolation tests. The architecture is coherent and genuinely DDD/BFF — not cargo-cult. The dominant risk is **not structure but billing convergence**: two payment models (legacy `Payment` + AR ledger) coexist by deliberate strangler design, and the work to make the ledger authoritative is mid-flight on this branch. That, plus a coach-route tenancy gap, is what stands between the app and a confident SaaS launch.

---

# 2. Product Design

## Roles

**FACT.** Three personas, enforced by route group + `usePersonaAuth(role)` on the frontend and `require_persona(...)` on every v2 route (`docs/adr/0003-bff-inside-backend.md:22-38`; frontend `lib/auth/use-persona-auth.ts`). A fourth **platform** persona exists for the SaaS control plane (`backend/v2/interfaces/platform/`).

- **Admin** (academy owner/head coach): dashboard, students, sessions, enrollments, payments/invoices, refunds, monthly generation, coach pay-rates, payouts/payroll, registrations, waivers, skill pathway, audit logs, reports. Home `/admin`.
- **Coach**: mobile-first `today` (sessions + rosters), attendance, teaching plans, skill board, student passports, offline write tray. Home `/coach/today`.
- **Parent**: dashboard, payments/invoices, autopay, Stripe billing portal, children, progress, onboarding/checkout, waivers. Home `/parent/payments`.

## Core Flows (FACT, with location)

| Flow | How it works | Evidence |
|---|---|---|
| **Registration** | Parent self-registers via Firebase Auth + v2 parent onboarding; admin still onboards new tenants | `README.md:135-137`; `identity/.../register_public_parent.py` |
| **Enrollment** | Parent checkout → Stripe `checkout.session.completed` → `PaymentSucceeded` event → `ConfirmEnrollment` reserves seat, creates Student + `Enrollment(active)`, emits `EnrollmentConfirmed` | `composition/event_handlers.py:87-98`; `enrollment/.../confirm_enrollment.py:85-152` |
| **Attendance** | Coach marks attendance idempotently on client `mutation_id`; validates occurrence, coach assignment, active enrollment | `coaching/.../mark_attendance.py:90-196` |
| **Skill pathway** | `student_progress` context: level placement, per-skill status (NOT_STARTED→IN_PROGRESS→TEST_READY→PASSED), level-up recommend/review, certificates | `student_progress/.../get_pathway_placement.py:37-80` |
| **Invoice generation** | `generate_monthly_payments()` iterates active/paused enrollments, applies first-month proration, writes **ledger invoices only** (legacy write removed) | `billing/.../mongo_payment_repo.py:417-532` |
| **Payment** | Stripe Checkout (one-time) or saved-card; webhook records `LedgerPayment` + `PaymentAllocation` against `LedgerInvoice` | `billing/.../handle_webhook_event.py` |
| **Autopay** | Subscription checkout → Stripe subscription → recurring `invoice.paid` converges to ledger; off-session PaymentIntent for admin-charge | `billing/.../charge_invoice_via_autopay.py` |
| **Stripe portal** | Parent opens hosted billing portal via `POST /parent/billing/portal` | `interfaces/parent/payment_routes.py:112` |
| **Coach payout** | `ComputeCoachPayout` by rate (per-session/per-hour/percent-of-revenue), absence-gated; `PayoutPeriod` draft→approved→paid, admin-only | `coaching/.../compute_payout.py:132-230`; `finance/.../generate_payout_period.py:43-67` |

---

# 3. Architecture Map

```
┌─────────────────────────────────────────────────────────────────────────┐
│ FRONTEND ROUTES (Next.js App Router, frontend/app/)                       │
│   (admin)/admin/*      (coach)/coach/*      (parent)/parent/*             │
│   (marketing)/login,register   (shared)/calendar,messages                 │
└───────────────┬───────────────────────────────────────────────────────────┘
                │  apiFetch<T>()  +  Firebase ID token  +  X-Academy-Id
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ SAME-ORIGIN PROXY   frontend/app/api/v2/[...path]/route.ts                 │
│   forwards to BFF_API_ORIGIN, bridges identity cookie/header              │
└───────────────┬───────────────────────────────────────────────────────────┘
                ▼  /api/v2/<persona>/*
┌─────────────────────────────────────────────────────────────────────────┐
│ BFF / INTERFACE LAYER  backend/v2/interfaces/<persona>/                    │
│   admin/ (24 route files)   coach/   parent/   platform/   me, registration│
│   require_persona(...) guards • persona-shaped view DTOs • NO Mongo here   │
├─────────────────────────────────────────────────────────────────────────┤
│ COMPOSITION ROOTS  backend/v2/composition/{admin,parent,coach,...}.py      │
│   wire use cases → repos + Stripe gateway; main.py mounts app.state.*      │
├─────────────────────────────────────────────────────────────────────────┤
│ APPLICATION (use cases + ports.py)   DOMAIN (pure aggregates/events)       │
│   contexts/: billing, enrollment, coaching, identity, finance,            │
│              communications, curriculum, onboarding, student_progress,    │
│              platform{audit,billing,governance}                            │
├─────────────────────────────────────────────────────────────────────────┤
│ INFRASTRUCTURE  Mongo repos • StripeGateway • Firebase Admin • Resend      │
└───────────────┬───────────────────────┬───────────────────┬──────────────┘
                ▼                       ▼                   ▼
        MongoDB (Atlas)          Stripe (live)        Firebase / Resend
   invoices, ledger_payments,   Webhook → /api/v2/parent/webhooks/stripe
   payment_allocations, payments,
   subscriptions, enrollments,        ┌───────────────────────────────────┐
   sessions, attendance, payouts,     │ WEBHOOK PROCESSOR (2-phase)        │
   outbox_events, ...                 │  accept() store durable → 200      │
                                      │  process_next() business writes    │
   ┌──────────────────────────────┐  └───────────────────────────────────┘
   │ DOMAIN EVENT OUTBOX           │
   │ shared/events: MongoOutbox →  │  ┌───────────────────────────────────┐
   │ EventDispatcher (retry, DLQ,  │  │ BACKGROUND JOBS (APScheduler, main.py)│
   │ event_handler_runs, audit)    │  │  • process_scheduled_resumes (2am) │
   └──────────────────────────────┘  │  • process_stripe_webhook_events 60s│
                                      │  • send_coach_daily_digests hourly │
                                      │  (monthly invoice gen = manual only)│
                                      └───────────────────────────────────┘
```

**FACT.** The BFF is a structural layer inside the single FastAPI process, persona-first directory layout, with documented lift-out criteria (`docs/adr/0003-bff-inside-backend.md`). **FACT.** Frontend reaches the BFF through a same-origin Next proxy (`frontend/app/api/v2/[...path]/route.ts`), keeping the Firebase token handling server-side.

---

# 4. DDD Review

**FACT.** Nine contexts under `backend/v2/contexts/` plus a nested `platform/{audit,billing,governance}` control plane; each has `domain/ application/{ports.py,use_cases/} infrastructure/`. Cross-context state change is event-only; reads go through ports (`docs/data-ownership.md:44-51`).

| Context | Purpose | Main aggregates | Key use cases | Collections | External deps | Score |
|---|---|---|---|---|---|---|
| **billing** | Payments, subscriptions, invoices/ledger, Stripe, refunds, webhooks | `LedgerInvoice`, `InvoiceLine`, `LedgerPayment`, `PaymentAllocation`, `CreditLedgerEntry`, legacy `Payment`, `Subscription`, `Product` | `handle_webhook_event`, `charge_invoice_via_autopay`, `send_invoice`, `start_checkout`, `issue_refund`, `record_manual_payment` | `invoices`, `invoice_lines`, `ledger_payments`, `payment_allocations`, `payments`, `subscriptions`, `stripe_invoice_processing` | Stripe | **Partial** (dual-model transition by design) |
| **enrollment** | Sessions, students, enrollments, waitlist, occurrences, pause/resume | `Session`, `SessionOccurrence`, `Student`, `Enrollment`, `RosterEntry` | `confirm_enrollment`, `promote_from_waitlist`, `generate_session_occurrences`, `get_session_roster` | `enrollments`, `sessions`, `students`, `waitlist` | — | **Good** |
| **coaching** | Attendance, payroll attendance, feedback, skill notes, payout compute, rates | `Attendance`, `CoachAttendance`, `CoachRate`, `PayoutStatement`, `SessionFeedback` | `mark_attendance`, `mark_coach_attendance`, `compute_payout`, `manage_coach_rates`, `generate_daily_teaching_plan` | `attendance`, `lesson_plans`, `progress_notes` | — | **Good** |
| **finance** | Payout periods, payroll, reporting/analytics snapshots | `PayoutPeriod`, `PayoutAuditLog`, reporting snapshots | `generate_payout_period`, `approve_payout_period`, `bulk_payroll`, `compute_reporting_snapshots` | `payout_periods`, `payout_period_lines`, `expenses` | — | **Good** |
| **identity** | Global users, memberships, platform roles, auth claims, Stripe Connect | `User`, `AcademyMembership`, `PlatformRole`, `Role` | `load_auth_claims`, `register_public_parent`, `bootstrap_academy` | `users`, `academy_memberships`, `platform_roles` | Firebase | **Good** |
| **student_progress** | Skill board, passport, level-up, placements, certificates | `StudentLevelProgress`, `StudentSkillProgress`, `LevelUpRecommendation`, `Certificate` | `update_skill_status`, `place_student`, `review_level_up`, `get_passport` | skill/level/cert repos | — | **Good** |
| **curriculum** | Programs, levels, skills, lesson cards, pathway | program/level/skill/criteria/lesson-card aggregates | `manage_*`, `get_pathway`, `seed_curriculum` | curriculum collections | — | **Good** |
| **communications** | Campaigns, coach daily digest, delivery logs | campaign/audience models | `send_campaign`, `send_coach_daily_digest` | `messages`, `announcements` | Resend | **Partial** (thin module, no aggregate per `docs/data-ownership.md:33`) |
| **onboarding** | Applications, waivers, signatures | application/waiver/signature | `manage_application`, `admin_waivers`, `waiver_signatures` | `waivers` (lives in Enrollment) | — | **Good** |
| **platform** | Tenant lifecycle, audit, platform billing, governance/export | tenant lifecycle, governance | `tenant_lifecycle`, `manage_platform_billing`, export/deletion | tenant control-plane | — | **Partial** (launch-gated, see §10) |

**FACT — layering is mechanically enforced.** `import-linter` runs four `forbidden` contracts in `backend/pyproject.toml:60-107`; a fresh run reported **4 contracts kept, 0 broken** (652 files, 1796 deps), and structural pytest is **19 passed**. No cross-context imports, no domain importing Stripe/Mongo/FastAPI/Firebase, no interface→infrastructure imports were found.

**OPINION / FACT (boundary leak).** One genuine violation: `interfaces/platform/governance_routes.py:20` imports `...platform.governance.domain.models.GovernanceActor` directly. The linter misses it because the wildcard `contexts.*.domain` matches only one path segment, so all nested `platform/*` sub-contexts are unguarded by every contract. Low blast radius (a request DTO), but it proves the contract has a coverage hole.

---

# 5. BFF Review

**FACT — APIs are persona/workflow-shaped, not generic CRUD.** Every handler depends on a composed use-case bundle and calls a use case; no Mongo in handlers. Examples:
- Coach: `GET /coach/today` → `CoachTodayResponse` (sessions + fanned-out rosters, `today_routes.py:35`); `POST /coach/attendance` idempotent on `mutation_id` (`attendance_routes.py:36`).
- Parent: `GET /parent/invoices`, `GET /parent/invoices/{id}` (line items), `POST /parent/enrollments/quote`, `POST /parent/checkout/start`, `POST /parent/autopay/start`, `POST /parent/billing/portal` (`payment_routes.py:45-112`).
- Admin: `GET /dashboard/attention` → `AdminAttentionList` (`dashboard_routes.py:22`).

**FACT — closest thing to generic CRUD** is the admin directory (`directory_routes.py:47-168`: list/get/create/patch users + role). **OPINION:** acceptable — it is role-filtered, tenant-scoped, and routed through use cases, not raw collection CRUD.

**OPINION — does any API expose the domain too directly?** No domain aggregates are serialized straight to HTTP; persona `views.py` DTOs sit between application results and the wire (`docs/adr/0003-bff-inside-backend.md:18-20`). The platform governance route's direct domain import (§4) is the only seam where domain types reach the interface layer.

**FACT — page→API dependency (frontend):**
- Admin dashboard → `listAdminSessions`, `listAdminPayments`, `getRevenue`, `listAdminAttention`.
- Coach today → `getCoachToday(date)` (StaleWhileRevalidate cached, offline-read capable).
- Parent payments → `listParentPayments`, enrollments, credits, `startAutopay`, `openBillingPortal` (refetch on autopay return with `staleTime:0`).

**FACT — persona need divergence is real and reflected in code:** coach is the only persona with offline query persistence (localStorage, `coach.*` keys, 24h) and an IndexedDB write queue (`lib/offline/`), because coaches work courtside. Admin/parent queries are always-fresh. PWA service worker (`app/sw.ts`) caches coach reads SWR; all auth-scoped API is `NetworkOnly`.

---

# 6. Billing / Invoicing Design

## Source-of-truth model (FACT)

- **Invoice source of truth:** `LedgerInvoice` (`billing/domain/ledger.py:21-48`). Financial status enum is `draft|open|partially_paid|paid|void`; **delivery is a separate axis** (`delivery_status`, `sent_at`, `last_sent_at`) — sending never changes financial status (`docs/adr/0012-ledger-invoice-as-source-of-truth.md:30-37`; enforced in `send_invoice.py`). Totals are always derived from lines via `recompute_totals` (`ledger.py:189-215`).
- **Payment source of truth:** `LedgerPayment` + `PaymentAllocation` (`ledger.py:67-95`). Allocation is pure (`allocate_payment_to_invoice`, `ledger.py:107-186`); overpayment → `CreditLedgerEntry`.
- **Legacy `Payment`** (`models.py:47-65`) is retained as a **transition-only read projection**, still written after the ledger write during webhook processing; deletion is deferred to Phase 5 (`docs/adr/0011-billing-ledger-payment-storage.md`, `docs/adr/0012-ledger-invoice-as-source-of-truth.md:54-56`). The two aggregates now live in **separate collections** (`payments` vs `ledger_payments`) per ADR-0011.

## Stripe object mapping (FACT)

| Stripe object | App mapping |
|---|---|
| **Customer** | located by `metadata{academy_id,parent_id}` via `get_default_payment_method()` (`stripe_gateway.py:323-348`) |
| **Checkout Session** | one-time (`create_checkout_session`), subscription (`create_subscription_checkout_session`), invoice pay-link (`create_invoice_checkout_session`, accepts `idempotency_key`) |
| **Subscription** | local `Subscription` row links `stripe_subscription_id` ↔ `enrollment_id`; resolved on `invoice.paid` via `invoice.subscription` or `invoice.parent.subscription_details.subscription` |
| **Invoice** | converged to a `LedgerInvoice` keyed by `stripe_invoice_id` (unique partial index) |
| **PaymentIntent** | autopay off-session PI, idempotency `autopay-{invoice_id}`; ledger payment `autopay-pi:{pi_id}`, allocation `autopay-alloc:{pi_id}` |

## Webhook handling, idempotency, recovery (FACT)

- **2-phase processing:** `accept()` stores the event durably and returns 200 fast; APScheduler `process_stripe_webhook_events` (every 60s, `main.py`) drains via `process_next()` with a 300s lock — exactly the at-least-once/retryable design the convergence plan targets.
- **Idempotency keys:** ledger payment `stripe-invoice-payment:{stripe_invoice_id}`, allocation `stripe-invoice-allocation:{stripe_invoice_id}`. **Unique indexes** exist on `payment_allocations(academy_id, idempotency_key)` and `stripe_invoice_processing(academy_id, business_key)` (migration `0130`). **FACT/RISK:** `ledger_payments` and `invoices` are **not** uniquely indexed on idempotency key — exactly-once relies on check-before-insert in the repo (`mongo_billing_ledger_repo.py:80`), leaving a concurrency race window.
- **Recovery points (Task 10):** implemented — `SUBSCRIPTION_INVOICE_RECOVERY_POINTS` and `MongoStripeInvoiceProcessingRepository.record_recovery_point()` checkpoint each step (`received → subscription_resolved → ledger_invoice_synced → ledger_payment_recorded → ledger_allocated → legacy_projection_saved → processed | quarantined`).
- **Tenant safety:** academy/parent mismatch → `_QuarantineStripeEvent` (no silent processing) (`handle_webhook_event.py`).
- **Duplicate-obligation policy:** an already-paid local invoice matched by a *different* Stripe invoice is **quarantined for manual review**, not double-allocated (the launch-safe choice from the plan).

## Reconciliation / failure recovery (FACT)

- **Recovery checkpoints + quarantine** are implemented. **The planned standalone reconciliation use case `reconcile_stripe_subscription_invoice.py` (Task 11) does NOT exist** (grep returned zero). There is no operator-facing "compare local ledger vs Stripe" diagnostic route yet.
- **OPINION:** recovery-point state is good but partial-failure *resume* logic and a reconciliation report are the remaining correctness gaps before high-volume autopay.

### Sequence Diagram A — Parent starts autopay

```
Parent        Frontend         BFF (parent)        Stripe            Webhook proc        Ledger(Mongo)
  │ click autopay  │                │                 │                  │                  │
  │───────────────►│ POST /parent/autopay/start        │                  │                  │
  │                │───────────────►│ create_subscription_checkout_session │                 │
  │                │                │────────────────►│ (session+sub)     │                  │
  │                │◄───────────────│ checkout_url     │                  │                  │
  │◄───────────────│ redirect       │                 │                  │                  │
  │ pay (4242…) ───────────────────────────────────► Stripe hosted        │                  │
  │                │                │                 │ checkout.session.completed ─────────►│ accept() store, 200
  │                │                │                 │ invoice.paid ─────────────────────► │ accept() store, 200
  │                │                │                 │                  │ process_next():   │
  │                │                │                 │                  │  resolve sub→enrollment identity
  │                │                │                 │                  │  find/create LedgerInvoice (stripe_invoice_id)
  │                │                │                 │                  │  record LedgerPayment (idem) ─────►│
  │                │                │                 │                  │  allocate → balance_due=0, status=paid►│
  │                │                │                 │                  │  write legacy Payment projection  │
  │ open /parent/payments (refetch staleTime:0) ◄──── autopay active, invoice paid, one history row
```

### Sequence Diagram B — Monthly invoice generation → payment → failure → recovery

```
Admin/Job        Billing use case            Ledger(Mongo)         Stripe              Webhook proc
  │ POST /admin/billing/generate-monthly (MANUAL — no cron)
  │───────────────►│ generate_monthly_payments()                    │                    │
  │                │ for each active/paused enrollment:             │                    │
  │                │   resolve charge (first-month proration)        │                    │
  │                │   create LedgerInvoice(open) idem=monthly-ledger-{enr}-{period} ───►│
  │                │   (billing_invoice_keys unique guards re-run)   │                    │
  │ Autopay attempt (admin "charge" or recurring Stripe cycle):     │                    │
  │   charge_invoice_via_autopay: re-read fresh invoice → chargeable?│                    │
  │   create off-session PaymentIntent (idem autopay-{invoice})──────────────────────────►│
  │   SUCCESS: invoice.paid / pi.succeeded ──────────────────────────────────────────────► accept→process
  │            record LedgerPayment + allocate → status=paid, balance=0
  │   FAILURE (decline): result.success=false, decline_code, INVOICE STATUS UNCHANGED (stays open)
  │   RECOVERY: manual SendInvoice (hosted pay-link) OR re-charge; quarantine on duplicate-obligation
  │   (No automatic dunning/retry escalation job — see §9 gaps)
```

---

# 7. Data Model Review

**FACT — ownership is contractual** (`docs/data-ownership.md`): one writer per collection, cross-context writes only via events.

| Collection | Owner | Notes / risk |
|---|---|---|
| `users`, `academy_memberships`, `platform_roles` | Identity | ADR-0007 membership model **implemented** (`mongo_membership_repo.py:33-34`) |
| `enrollments`, `sessions`, `students`, `waitlist` | Enrollment | |
| `attendance` | Coaching | unique `(academy_id, session_id, student_id)` |
| `invoices`, `invoice_lines` | Billing | LedgerInvoice canonical |
| `ledger_payments` | Billing | split from `payments` per ADR-0011 |
| `payment_allocations` | Billing | unique `(academy_id, idempotency_key)` |
| `payments` | Billing | **legacy projection — duplicate document shape** (transition) |
| `subscriptions` | Billing | |
| `payouts`/`payout_periods`/`payout_period_lines` | Finance | unique natural key |
| `stripe_invoice_processing` | Billing | NEW — recovery points, unique `(academy_id, business_key)` |
| `outbox_events`, `event_handler_runs`, `dead_letter_events`, `event_audit` | shared/events | crosscutting |

**Shared/duplicate shapes (FACT):** `payments` (legacy `Payment`) and `ledger_payments` (`LedgerPayment`) are deliberately separate now; the original co-located-collection hazard that motivated ADR-0011 is resolved. Parent/admin read models must dedupe legacy vs ledger rows (Task 6 — see §9).

**Indexes (FACT):** every index leads with `academy_id` (`docs/data-ownership.md:64`). Migration `0130` adds: `invoices(academy_id,stripe_invoice_id)` unique-partial, `invoices(academy_id,enrollment_id,period,status)`, `ledger_payments(academy_id,stripe_invoice_id)` partial, `payment_allocations(academy_id,idempotency_key)` unique. **Missing/weak (FACT):** no unique index on `ledger_payments`/`invoices` idempotency key (race window, §6). **OPINION:** `invoices(academy_id,stripe_invoice_id)` unique-partial is the correct nullable-unique pattern; the open risk is the non-unique ledger-payment dedupe under concurrency.

**Risky fallback (FACT):** `identity/.../mongo_user_repo.py:215` queries with `academy_id or self._default_academy_id` — a falsy academy_id silently falls back to the default tenant (latent cross-tenant read).

---

# 8. Frontend Design Review

**FACT — stack:** Next.js 15 App Router, React 19, TanStack Query v5 (`staleTime` 5min, `gcTime` 1h, no retry on 4xx), Firebase Web SDK, Serwist PWA. Typed persona API clients in `lib/api/{admin,coach,parent}.ts` are **hand-declared** — `pnpm generate:api` (OpenAPI→TS) exists but the generated file is a `.gitkeep` placeholder.

| Page | Role | Purpose | APIs | State | Loading/Error/Empty | Missing UX |
|---|---|---|---|---|---|---|
| `/admin` | Admin | KPIs, attention, revenue, recent payments | 4 admin queries | React Query | Skeletons; empty states present; **no error boundary** (degrades) | explicit error surface on KPI failure |
| `/admin/payments` | Admin | status, discount, mark-paid, refund, monthly gen | admin billing | RQ + mutations | table skeleton, dialog errors | end-to-end ledger confirmation in UI |
| `/coach/today` | Coach | sessions+roster for date | `getCoachToday` | RQ + **localStorage persist** | full L/E/E (retry button, "Refreshing…") | — (strongest page) |
| `/parent/payments` | Parent | enrollments, autopay, portal, pause | parent billing | RQ, refetch on return | portal/autopay error messages, skeletons | dunning/failed-payment recovery UX |
| `/parent/dashboard` | Parent | family hero, 8 concurrent queries | many optional | RQ graceful-degrade | core blocks on children; optional errors → IssueStrip | — |

**FACT — auth:** Firebase modular sign-in (email/Google, popup vs redirect by UA), session-cookie + `X-CourtMastr-Identity` bridge to BFF, role-based redirect via `usePersonaAuth`. Mobile Google sign-in uses a first-party `/__/auth/*` proxy (`DEPLOYMENT.md:54-87`).

**FACT — PWA/offline:** coach reads SWR-cached; **coach attendance writes are `NetworkOnly` today** (Wave 1A) — the IndexedDB queue + sync orchestrator (`lib/offline/`, 5-attempt backoff, 4xx→needs-review tray) is built but full offline-write integration is Wave 1B. Admin/parent are not offline-capable by design (`docs/agent/frontend-rules.md:50-56`).

**OPINION:** Frontend correctly keeps business truth on the backend (`docs/agent/frontend-rules.md:33-35`). Two debts worth tracking: the 51KB hand-maintained admin client (drift risk vs backend DTOs) and missing failed-payment recovery UX for parents.

---

# 9. Testing Review

**FACT — structure:** ~216 backend test files: unit (36, fakes), application (54, fakes), contract (40, **real Mongo** + Stripe fixture replay), interface (58, HTTP/persona), infrastructure (6), structural (1, raw-Mongo guard). 16 Playwright E2E specs.

| Business flow | Status | Evidence / assertion quality |
|---|---|---|
| Webhook `invoice.paid` → ledger | **Covered (strong)** | `test_billing_idempotency.py:151-161` real Mongo: `balance_due_cents==0`, `status=="paid"`, credit count==1; fixture replay `test_stripe_webhook_fixture_replay.py` |
| Autopay charge | **Covered (very strong)** | `test_charge_autopay_use_case.py`: declines, exceptions, idempotency `autopay-pi:…`, **no-Stripe-call counters**, stale-balance re-read |
| Send invoice | **Covered (very strong)** | `test_send_invoice_use_case.py`: `not stripe.called` on zero/paid/void; delivery vs financial separation |
| Admin billing read | **Covered (medium)** | `test_admin_billing.py`: persona/refund OK but shallow on persistence |
| Parent payment dedupe | **Covered** | `test_parent_invoice_routes.py` + idempotency contract; cross-parent 404 |
| Tenant isolation | **Covered (very strong)** | composition + contract (`test_saas_tenant_isolation.py`) + E2E + `test_no_raw_tenant_mongo_access.py` |
| Enrollment / attendance | **Covered (strong)** | lifecycle, race, occurrence uniqueness |
| Coach payout | **Covered (strong, no E2E)** | `test_coach_payout.py` (28KB) multi-scenario |
| Monthly invoice generation | **Partial** | per-step tests; **no end-to-end Mongo test** student→enroll→generate→ledger |
| Skill pathway state machine | **Partial** | domain logic + queries; "mastered→next unlocked" transition not integration-tested |

**FACT — assertions are largely real, not fake:** strong examples assert exact balances, row counts (`count_documents(...)==1`), idempotency keys, outbox event names, and Stripe-call counters. Weak spots: `test_admin_billing.py:349` asserts only the id set; **all Playwright E2E stub `**/api/v2/**`**, so E2E verifies UI wiring, not real backend invariants.

**Tests that should be added (OPINION):** (1) end-to-end monthly-generation ledger test; (2) autopay decline → dunning/recovery path; (3) refund → `CreditLedgerEntry` flow; (4) partial-failure webhook *resume* (recovery-point replay) — the plan defines these (Task 10 step 3) but they are not yet present; (5) a coach-route tenancy test (see §11). **Tests that can be removed:** none obviously redundant; the stubbed E2E should be re-scoped to hit a real test backend for at least the billing-convergence path rather than deleted.

---

# 10. Production Readiness

| Area | State | Evidence |
|---|---|---|
| **Stripe** | **Mostly ready; gap = reconciliation + concurrency idempotency.** Keys gate billing (503 without), webhook 2-phase + recovery points + quarantine implemented | `DEPLOYMENT.md:92-105`; §6 |
| **Resend / email** | **Ready, safety-blocked.** Hard-blocked outside `APP_ENV=production` + `EMAIL_DELIVERY_ENABLED` | `DEPLOYMENT.md:259-266` |
| **DB migrations** | **Partial.** Numbered migrations exist (…`0130`) but `DEPLOYMENT.md:296-298` states "no versioned migration framework yet"; indexes created on startup | `DEPLOYMENT.md:296-298` |
| **Webhook replay** | **Ready.** Durable event store + 60s drain + idempotent keys + replay fixture tests | §6, §9 |
| **Logging** | **Basic.** Healthz monitored; logs to drain recommended, not proven shipped | `DEPLOYMENT.md:268-276` |
| **Audit trail** | **Implemented.** `audit_logs`, `event_audit` (90-day TTL), payout audit | `docs/data-ownership.md:39-42` |
| **Security** | **Strong.** Firebase `check_revoked=True`, server-enforced email verification, HttpOnly secure cookies, explicit CORS, atomic invite rollback | `README.md:104-121`; `DEPLOYMENT.md:144-166` |
| **Tenant** | **Membership model built; one P1 gap.** Resolver/middleware host-based, never user-inferred; **coach composition still binds `default_academy_id`** (§11) | §11 |
| **Backup/recovery** | **Documented, drill cadence defined; not proven run.** | `DEPLOYMENT.md:279-294` |
| **SaaS mode** | **Launch-gated.** `V2_SAAS_MODE` exists but `DEPLOYMENT.md:107-112` blocks enabling until Wave 6 platform outputs verified | `DEPLOYMENT.md:107-139` |

---

# 11. Risk Register

| Risk | Severity | Evidence | Business impact | Fix direction |
|---|---|---|---|---|
| Coach use cases bind `settings.default_academy_id` at startup, not request tenant | **High (P0 for SaaS)** | `composition/coach.py:220-224,332,~340,352` + in-code TODO `:344-346`; coach router mounted unconditionally | Coach attendance/roster writes scoped to wrong tenant under SaaS → cross-tenant data corruption | Resolve `request_academy_id()` from `auth_claims`; add coach tenancy test |
| No unique index on `ledger_payments`/`invoices` idempotency key | **High** | §6; `mongo_billing_ledger_repo.py:80` check-before-insert | Concurrent webhook/retry could duplicate a payment row → wrong balance | Add unique partial index; rely on `DuplicateKeyError` |
| Reconciliation use case (Task 11) not built | **Medium-High** | grep zero `reconcile_stripe_subscription_invoice.py` | No operator way to prove local ledger == Stripe after incident | Implement read-only reconcile + admin diagnostic route |
| Parent/admin read-model dedupe (Task 6) not confirmed in code | **Medium** | billing pass: not visible in composition excerpts | Parent could see duplicate legacy+ledger payment rows | Verify/finish dedupe by `stripe_invoice_id`/`pi_id` |
| Monthly invoice generation is manual-only | **Medium** | `main.py` jobs list has no monthly cron | Missed billing run = lost revenue / late invoices | Add guarded APScheduler job or document SOP |
| `recompute_totals` stale-baseline under concurrent writes | **Medium** | `ledger.py:195-197` NOTE | Wrong invoice balance under concurrent admin+webhook | Optimistic version field or derive allocated from `payment_allocations` |
| import-linter blind to nested `platform/*` contexts; one real interface→domain leak | **Low** | `governance_routes.py:20`; `pyproject.toml:102-107` | Boundary decay goes uncaught in CI | Add `contexts.platform.*.domain/infrastructure` to contracts |
| `mongo_user_repo.py:215` falsy-academy fallback | **Low-Medium** | cited | Latent cross-tenant read if empty academy_id passed | Reject empty academy_id in SaaS paths |
| No versioned migration framework | **Low-Medium** | `DEPLOYMENT.md:296-298` | Backfills risky/manual | Adopt lightweight migration runner (`v2_migrations` collection exists) |
| E2E stubs all backend calls | **Low** | §9 | Billing invariants unproven end-to-end in browser | Point one E2E path at a real test backend |

---

# 12. Improvement Plan

**P0 — Coach tenant resolution.** Problem: coach writes use the process default academy. Evidence: `composition/coach.py:220-224,332-352`. Change: resolve tenant from `request.state.auth_claims` like `parent.py`/`admin.py` do. Benefit: closes a cross-tenant write hazard blocking SaaS. Files: `composition/coach.py`, coach use-case wiring. Test proof: a coach-route tenant-isolation test asserting writes land in the resolved academy. Priority **P0**.

**P0 — Ledger-payment idempotency at the storage layer.** Problem: dedupe is check-before-insert only. Evidence: §6, migration `0130` lacks a unique ledger-payment key. Change: unique partial index on `ledger_payments(academy_id, idempotency_key)` + `DuplicateKeyError` handling. Benefit: structural exactly-once for money. Files: new migration, `mongo_billing_ledger_repo.py`. Test proof: concurrent-replay contract test asserting count==1. Priority **P0**.

**P1 — Reconciliation use case + admin diagnostic.** Problem: no Stripe-vs-ledger audit. Evidence: Task 11 file absent. Change: implement `reconcile_stripe_subscription_invoice` (read-only) per plan §Task 11. Benefit: operators can prove/repair financial state post-incident. Files: new use case + admin route + test. Priority **P1**.

**P1 — Finish/verify read-model dedupe (Task 6).** Problem: possible duplicate payment rows in parent/admin views. Change: dedupe ledger vs legacy by provider keys. Benefit: trustworthy billing history at launch. Files: `composition/parent.py`, `enrollment/.../mongo_student_repo.py`. Test proof: "one row per subscription invoice" tests (plan Task 6 step 5). Priority **P1**.

**P1 — Monthly generation automation or SOP.** Change: guarded APScheduler monthly job (idempotent via `billing_invoice_keys`) or a documented runbook. Benefit: no missed billing cycles. Files: `main.py`, runbook. Priority **P1**.

**P2 — Concurrency-safe invoice totals.** Change: optimistic-lock version on `LedgerInvoice` or derive `allocated` from `payment_allocations`. Files: `ledger.py`, repo. Priority **P2**.

**P2 — import-linter coverage for nested platform contexts** and fix `governance_routes.py:20`. Files: `pyproject.toml`, that route. Priority **P2**.

**P2 — End-to-end monthly-generation and parent dunning tests.** Priority **P2**.

---

# 13. Final Verdict

- **Is the app design coherent?** **Yes (FACT-grounded OPINION).** Clear strangler strategy, enforced layering (import-linter 4/4 kept), a real data-ownership contract, an event outbox, and persona-shaped BFF. The structure holds.
- **Is it DDD?** **Yes, genuinely.** Pure domain, ports/adapters, use-case orchestration, event-only cross-context coupling, mechanically enforced — not nominal.
- **Is it BFF?** **Yes**, in the in-process-layer sense ADR-0003 explicitly chose; persona separation is by directory + view DTOs + auth guards, with documented lift-out criteria. Not a separate-deploy BFF, by design.
- **Is billing production-ready?** **Almost — not yet for high-volume autopay.** The ledger model, webhook 2-phase processing, recovery points, quarantine, and duplicate-charge guards are implemented and well-tested. **Blockers:** storage-level idempotency on ledger payments (P0), and the absence of a reconciliation path (P1). The dual legacy/ledger model is intentional transition debt, not a defect — but the read-model dedupe must be confirmed.
- **Must fix before launch:** (1) coach tenant resolution (P0); (2) unique ledger-payment idempotency index (P0); (3) reconciliation + read-model dedupe (P1); (4) monthly-generation automation or documented SOP (P1).
- **Can wait:** concurrency-safe totals refactor, import-linter nested-context coverage, expanded E2E/dunning tests, versioned migration framework — all real but post-launch with the SOPs above in place.

---

## Verification Notes

- **Verification performed:** Read all required docs (AGENTS, README, DEPLOYMENT, test_result, ADRs 0003/0005/0007/0011/0012, data-ownership, convergence plan); ran `git status`; five parallel read-only code investigations (import-linter run: 4 kept/0 broken, structural pytest 19 passed). No code modified.
- **Caveats:** Full `pytest v2/tests` and live Stripe staging proof (plan Task 8) were not run. Task-6 dedupe and Task-11 reconciliation states are reported from grep/excerpts — confirm by opening `composition/parent.py` `list_payments_for_parent` and a repo-wide `reconcile` search before acting. The convergence plan's checkboxes are all unchecked even though much of Tasks 2–5/10/12 is coded — treat the plan as intent and the cited files as ground truth.
