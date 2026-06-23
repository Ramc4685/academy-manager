# SaaS / DDD / BFF Architecture Review — `academy-manager`

*Date: 2026-06-17. Research-only review (no code changes were made as part of the review itself).*
*Scope: `backend/v2/` (SaaS-mode v2). Legacy `/api/*` excluded per AGENTS.md.*
*Method: evidence verified from code via five parallel review passes (architecture/boundary, security, logging, tests, product coverage).*

## Executive Verdict

- **Ship readiness (single-academy launch):** Go, with conditions. Core lifecycle (register → enroll → schedule → attend → progress → invoice → autopay → payroll) is end-to-end implemented. Conditions before launch: (1) confirm a global liveness/readiness probe exists for deploy health; (2) add refund actor attribution.
- **SaaS readiness (multi-academy):** Not yet. The tenancy *primitives* are SaaS-grade, but the **composition layer pins one academy at boot** (`default_academy_id`). You cannot correctly serve tenant #2 in one process today. Headline finding.
- **DDD maturity:** High. Clean bounded contexts, layering enforced by `import-linter` + structural tests. A handful of tactical leaks (infra classes in application/composition).
- **BFF maturity:** High. Persona-shaped (not generic CRUD), uniform auth/tenant guards, ownership checks layered on top. Main smell: a ~140-field `AdminUseCases` god-object.
- **Test confidence:** Medium. 216 backend test files, strong tenant-isolation + billing-idempotency coverage; but zero Stripe-signature-rejection tests, zero coach→admin RBAC-denial tests, zero autopay-failure tests, and a cluster of mock-only/tautological tests giving false confidence.
- **Biggest risk:** Single-tenant composition + `default_academy_id` on the live request path. In a multi-tenant deploy, constructor-injected `academy_id` (webhooks, autopay closures) trusts the boot-time academy, not the resolved request tenant → potential cross-tenant misrouting of Stripe events and autopay writes.

---

## What Is Strong

| Area | Evidence from code | Why it matters |
|---|---|---|
| Tenancy primitives | `shared/tenancy/context.py` (ContextVar, fail-closed `TenantContextUnset`), `shared/tenancy/repository.py` (`TenantScopedRepository` auto-injects `academy_id` on every find/insert/update/delete/count, ~70 repos extend it), `shared/tenancy/resolver.py` (subdomain → custom domain → internal header, never user-inferred) | The hard part of multi-tenancy (data-layer isolation) is built correctly and fail-closed |
| Membership-based identity | `contexts/identity/application/use_cases/load_auth_claims.py::LoadAuthClaims.execute` requires resolved tenant, validates active `academy_memberships`, separates `platform_roles` from academy `roles`; `shared/auth/claims.py` `has_role` vs `has_platform_role` | Matches the AGENTS.md SaaS contract; cross-tenant authority is cleanly separated |
| Layering enforced by tooling | `lint-imports` 4 contracts KEPT (domain-pure, app-not-infra, infra-not-interfaces); `v2/tests/structural` 19 pass; `test_no_raw_tenant_mongo_access.py` 5 pass | DDD boundaries are mechanically enforced, not just documented |
| RBAC at the edge | `shared/http/persona.py::require_persona` (404-on-mismatch to avoid leaking existence) on all persona routes; `require_platform_admin/operator/support` on platform routes; ownership layered (`coach/roster_routes.py::_require_assigned`, parent reads scoped by `parent_id=claims.user_id`) | Role + ownership both enforced; no generic CRUD surface |
| Billing webhook hardening | `mongo_stripe_dedup.py` insert-first lock + stale-reclaim; `handle_webhook_event.py` separates fast `accept` from `process_next`, validates livemode, rejects metadata academy mismatch | Idempotent, replay-safe webhook intake |
| Secrets via env only | `shared/config/settings.py` single source; prod validator requires Mongo/Firebase/Stripe secrets and rejects wildcard CORS (`main.py::_add_cors_middleware`) | No hardcoded keys found in v2 |
| Product breadth | 10 contexts, 4 persona BFFs, ~22 admin route modules, full coach/parent mobile surfaces, real `platform/` SaaS scaffolding (tenant lifecycle, plans, GDPR governance) | The product genuinely does its job for a single academy |

---

## Critical Findings

| Finding | Evidence | Business problem | Risk | Priority |
|---|---|---|---|---|
| **Composition roots + webhook handler are single-tenant; constructor-injected `academy_id` ignores the resolved request tenant** | `main.py:132,224,229,231`, `_runtime_academy_id` (`main.py:439-445`); `contexts/billing/.../handle_webhook_event.py:73,93,105,164`; `composition/coach.py:206,224,324,344` (`TODO: academy_id is baked in at startup`) | Cannot serve a 2nd tenant correctly; webhooks can't fan out per tenant | Cross-tenant misrouting of Stripe events / autopay writes in any multi-tenant deploy | **Critical** (SaaS blocker) |
| **`default_academy_id` is still on the live request path via composition** — violates AGENTS.md line 102 | `composition/admin.py:1121,1124,1415`; `composition/coach.py:206,224,324,332,352`; `main.py:445,592` | Silent wrong-tenant fallback if `saas_mode`/`single_academy` guards misconfigure | Wrong-tenant data access | **Critical for SaaS** (acceptable only while `saas_mode=False`) |
| **Refunds are not attributable to an admin actor** | `interfaces/admin/billing_routes.py:299-312` discards `_claims`; `contexts/billing/.../issue_refund.py:30-36,104-127` — `IssueRefundCommand` has no actor; `PaymentRefunded` event has no `actor_id`. Contrast `mark_payment_paid` which passes `actor_id=claims.user_id` (`billing_routes.py:246`) | Money movement to a customer can't be tied to who issued it | Dispute/fraud/insider-abuse forensics impossible; compliance gap | **High** |
| **No Stripe webhook signature-rejection test; rejection isn't even logged** | Tests pass literal `"test_signature"` (`contract/test_stripe_webhook_fixture_replay.py`); `InvalidWebhookSignature` propagates to `shared/http/errors.py:28-38` which **logs nothing** | Forged/failing webhooks invisible; regression in signature check wouldn't fail CI | Silent acceptance of tampered events; no audit trail of forgery attempts | **High** |
| **Correlation context wired into the log formatter but never populated** | `shared/observability/logging.py:27-30` emits `academy_id/user_id/request_id` fields; no `setLogRecordFactory`/filter/middleware ever sets them; tenant ContextVar never bridged to logging; no request-id middleware | Cannot pivot prod logs by tenant/user/request | Production incident triage on a billing dispute is near-impossible | **High** |
| **Scheduler `extra=` dicts silently dropped + job-level failures unobservable** | `main.py:258,286,339` log `extra=totals` but the JSON formatter ignores arbitrary `extra`; APScheduler setup (`main.py:341-375`) registers no `EVENT_JOB_ERROR` listener; digest failures (`send_coach_daily_digest.py:99-124`) write Mongo but emit no log | "A coach didn't get their digest / a job didn't run" — no log evidence | Silent background-job failures in billing/comms | **High** |

---

## SaaS Standard Review (pass / partial / fail)

| Category | Verdict | Evidence |
|---|---|---|
| Tenant-aware design | **PASS** | `TenantScopedRepository` threads `current_academy_id()` into every query/doc |
| Tenant isolation (data layer) | **PASS** | Non-base repos either filter `academy_id` explicitly or are intentional cross-tenant platform/global collections; `test_no_raw_tenant_mongo_access.py` enforces the allowlist |
| Tenant-safe data access | **PASS** | Repos scope by tenant via base class; app code never touches `academy_id` directly |
| Role-based access control | **PASS** | `require_persona` + `require_platform_*` + ownership checks |
| Auditability | **PARTIAL** | Platform actions audited (`platform_audit_events`); academy-admin audit only *reads* `audit_logs` (`admin/audit_routes.py`) — most mutations (refunds, role changes, price overrides, payout approvals) emit no audit record |
| Billing readiness | **PASS (w/ latent debt)** | Stripe gateway port + fake, Connect, dedup/idempotency, ledger + payments. Latent dual Payment-vs-AR-ledger model on one collection is a correctness risk (known convergence debt), not an isolation risk |
| Operational observability | **PARTIAL/FAIL** | Structured JSON logs, no secret leakage; but dead correlation fields, dropped scheduler counters, quiet rejection/failure paths, no per-request access log |
| Secure config handling | **PASS** | env-only `Settings`; prod validator; wildcard CORS rejected |
| Extensible domain model | **PASS** | `academy_id` on tenant docs; global `users` + `academy_memberships` + `platform_roles`; `academy_domains` for custom-domain resolution |
| Reusable product architecture | **PARTIAL** | Primitives reusable; **composition wiring is single-tenant** (the blocker) |
| Production support readiness | **PARTIAL** | Logs can't be pivoted by tenant; no global `/healthz` found in BFF routers (per-tenant `/tenants/{id}/health` exists) |
| No hardcoded academy-only logic | **PARTIAL** | No `blno`/`BLNO`/`Courtmaster` literals in v2 source; but `default_academy_id`/`V2_DEFAULT_ACADEMY_ID` wired into composition |
| No one-off patchwork | **PARTIAL** | Inline ad-hoc repo classes in `composition/parent.py:195-229`; pricing/date rules in composition closures |

---

## DDD Review

**Bounded contexts** (billing, coaching, communications, curriculum, enrollment, finance, identity, onboarding, platform, student_progress) are clear and self-contained; structural test confirms no cross-context imports; domain stays pure. Business rules predominantly live in `application/use_cases`, not routes.

**Tactical violations:**
- **Infrastructure inside composition** — `composition/parent.py:195-229` defines `_EnrollmentAutopayState` / `_EnrollmentBillingIdentity` issuing raw `db["enrollments"].update_one/find_one` with closure-captured `academy_id`. They filter by tenant (isolation holds) but bypass `TenantScopedRepository` and the tenant-literal guard.
- **Infra classes in the application layer** — `contexts/billing/application/use_cases/finance.py` declares `MongoExpenseRepository` / `MongoPayoutRepository`. The linter misses it only because `TenantScopedRepository` lives in `shared/`. Layering smell the linter can't catch.
- **`shared/` scope creep** — `shared/comms/messages.py` holds a full `MongoMessageRepository` + `CommsService`; a business context's infra living in cross-cutting space.
- **Business rules in composition closures** — `composition/parent.py:1004 _session_amount_cents` (hardcoded `2500` fallback), `_start_date_to_datetime` encode billing/scheduling rules in the composition root.

No false-positive cross-context imports; aggregates and use cases are otherwise meaningful.

---

## BFF Review

- **Admin** — persona-shaped, workflow-oriented (payout/payroll/registration-review/reports); guards per-route. Smell: `interfaces/admin/deps.py:139-277` `AdminUseCases` ~140-field god-object — maintainability/repurposing drag, easy to wire an unguarded use case unnoticed (not a data-leak; guards are per-route).
- **Coach** — `coach/today`, `coach/sessions/{id}/roster`, attendance, notes, skill board; ownership enforced via `_require_assigned`. Clean.
- **Parent** — invoices/payments/autopay/progress/waivers; reads self-scoped by `parent_id`. Clean. **Gap:** no parent-initiated messaging endpoint (broadcast-recipient only).
- **Auth + tenant context** — uniform across personas via `require_persona` + ContextVar. Two tenant-resolution caveats (security): internal tenant header trusted verbatim without existence validation (`shared/tenancy/resolver.py:141-152`); tenant resolved from client-influenceable `x-forwarded-host` (`main.py:530-538`) — both rely on the edge proxy overwriting/stripping headers; **confirm Fly/Cloudflare guarantees this.**

---

## Logging Review

**Useful logs that exist:** autopay charge lifecycle (`charge_invoice_via_autopay.py:163,178,194,236` — invoice, pi, decline_code, balance), autopay webhook reconciliation (`handle_webhook_event.py:594,613`), webhook dedup/idempotency (`:112,167,309`), auth/tenant resolution failures (`middleware.py:99,126,156` — logs error *code* not token, good), event-dispatcher failures (`dispatcher.py:88` with traceback), invoice send flow (`send_invoice.py`).

**Weak logs:** autopay/webhook logs lack tenant + actor context; scheduler summaries pass `extra=totals` that the formatter **drops** (the counts you need in an incident vanish); several `warning` logs of bare `%s` exceptions with no entity id / traceback; `InvoiceLineAdded` logged at INFO with full event object (noise).

**Missing logs (each = a real support scenario):**
- Rejected webhook signature → **no log at all** (forgery/delivery-failure invisible).
- Central `DomainError` handler (`errors.py:28-38`) logs nothing → all 4xx across personas invisible.
- Webhook processing failure path marks Mongo but emits no log/traceback.
- Per-coach digest failures silent → "a coach didn't get their email" unanswerable.
- No per-request access log (tenant/user/latency/status); no request-id correlation.
- Manual payments / refunds have no logging at all.

**Sensitive data:** essentially clean — IDs not secrets; raw Stripe payloads stored in Mongo, not logged. One minor item: `admin/directory_routes.py:132` logs a user email on bulk-invite failure (PII in logs, low severity).

---

## Reuse / Repurpose Review

**The SaaS machinery is built but not engaged.** Tenancy primitives, membership auth, resolver, and `TenantScopedRepository` are SaaS-ready. The blocker is **purely composition/wiring**:
- Composition roots compose parent/coach/admin BFFs **once at boot** bound to `runtime_academy_id` (`primary_academy_id` or `settings.default_academy_id`) → single-tenant singletons.
- Stripe webhook processors built as a **one-entry map** keyed by the boot academy (`main.py:231`); the handler runs everything inside `tenant_scope(self._academy_id)`.
- Reads/writes through repositories *are* request-tenant-scoped (middleware sets the ContextVar correctly). The gap is **use cases that receive `academy_id` as a constructor argument** (webhooks, autopay closures, public-parent register at `main.py:168`) — they use the static boot value, which only equals the request tenant in single-tenant deployments.

**No naming blockers** (`blno`/`courtmaster` confined to docs/seed/local env). **Data model supports multiple tenants.** Fix is to move to per-request (or per-resolved-tenant) composition and pass `current_academy_id()` instead of a static value before onboarding tenant #2.

---

## Test Review

**Inventory:** 216 backend test files (~1,307 test fns, ~46.8k LOC) across interface/application/contract/unit/structural/seed; 11 frontend node tests; ~15 e2e specs.

**Strong tests:** tenant isolation across all CRUD paths (`contract/test_saas_tenant_isolation.py:32-128`), cross-tenant + academy-switch e2e (`e2e/specs/saas-tenant-isolation.spec.ts`), billing idempotency + overpayment credit allocation (`contract/test_billing_idempotency.py`), Stripe webhook fixture replay (10+ event types), attendance race/unique-index (`contract/test_attendance_race.py`), mark-attendance rejection paths, coach payout computation (`application/test_coach_payout.py`).

**Missing coverage (critical):**
- **Stripe signature verification failure** — none (replay passes a dummy signature).
- **Coach → admin RBAC denial** — none.
- **Cross-parent IDOR** (parent A reading parent B's invoices/payments) — ownership check exists in `get_invoice_for_parent` but no regression test guards it.
- **Cross-tenant HTTP mutation denial** (admin switched academy can't PATCH old academy's student) — none.
- **Autopay failure scenarios** (subscription update fails / orphaned enrollment) — none.
- Double-enrollment prevention; concurrent payout-period close; cross-academy ledger dedup — none.

**Weak / false-confidence tests:** mock-only tests that pass even if the use case is deleted (`application/identity/test_gateway_and_roles.py:18-57` — asserts the mock, not the academy-isolation logic; `test_gateway_masks_stripe_account` asserts a hardcoded mock return); webhook-handler test calls `accept(body, "test_signature")` and never validates the signature.

**Unwanted tests safe to remove (NOT deleted — listed with reason):**
- `unit/test_ids.py:4-8` `test_new_ulid_returns_canonical_string` — asserts ULID library behavior (length/uppercase), not app logic.
- `unit/test_a1_me_response.py:19-44` (both `membership_id` tests) — tautological Pydantic serialization; the type checker already guards the field.
- `unit/test_healthz.py:51-70` `test_platform_routes_are_mounted_by_default` / `..._can_be_disabled` — assert route presence/absence in a list, not behavior.
- `application/identity/test_gateway_and_roles.py:18-57` — mock-only; replace with a contract test using a real repo before removing (it's currently the *only* nominal coverage of role-academy matching, so retire only once a real test exists).

Safe because each asserts a library/framework constant or a mock echo, not a business rule — the rule is enforced elsewhere (type system, Mongo index, or an existing contract test).

---

## Product Coverage Review

**Covered:** admin ops, coach schedule/roster/attendance/notes, parent progress/billing/payments/autopay, registration/enrollment, session scheduling, student directory, attendance, notes/progress, skill pathway/curriculum, billing, invoices, payments, payouts/payroll, waivers, audit logs, tenant settings, super-admin tenant lifecycle/GDPR.

**Partial:** parent messaging (broadcast-recipient only; no parent-initiated/two-way threads), reports (admin-only; no coach/parent analytics, no revenue/cohort/retention), operational support (per-tenant health exists; no global `/healthz` found in BFF routers; no cross-org aggregate dashboards).

**Missing features (classified):**
- **Launch blocker:** none structural. *Verify* a global liveness/readiness probe exists for deploy health (only per-tenant `/tenants/{id}/health` found).
- **Important soon:** parent↔coach/admin two-way messaging; refund/credit visibility for parents; coach-facing reporting.
- **SaaS maturity:** cross-org super-admin dashboards (MRR/churn/active tenants); self-serve tenant signup + SaaS-plan Stripe checkout (today operator-driven); general comms delivery/bounce observability; richer analytics (cohort/LTV/revenue).
- **Nice later:** parent push/SMS channels; family multi-child billing consolidation; public class catalog/store; document storage (medical forms, photos).

---

## Recommended Improvement Plan

| Priority | Business problem | Recommended change | Use / benefit | Complexity | Tests required |
|---|---|---|---|---|---|
| **P0 (SaaS blocker)** | Can't serve tenant #2; webhook/autopay trust boot academy | Move BFF composition + webhook processors to per-request / per-resolved-tenant; pass `current_academy_id()` instead of static `academy_id` into webhook & autopay use cases | Unblocks multi-academy SaaS; removes cross-tenant misrouting | High | Multi-tenant integration test: two academies in one process; webhook routed to correct tenant by metadata |
| **P0 (pre-launch)** | Refunds unattributable | Add `actor_id` to `IssueRefundCommand`/`PaymentRefunded`; thread `claims.user_id` from the route | Money-movement forensics & compliance | Low | Test: issued refund persists/attributes acting admin |
| **P1** | Forged/failing webhooks invisible & untested | Log signature rejections + processing failures; add a negative test asserting invalid signature → 400 | Detect forgery/delivery failure; prevent silent regressions | Low | Webhook signature-rejection test; processing-failure log assertion |
| **P1** | Prod logs can't be pivoted by tenant/user | Populate the already-declared `academy_id`/`user_id`/`request_id` log fields (request-id middleware + bridge tenant ContextVar to a log filter); stop dropping scheduler `extra` counters | Production support / dispute triage | Medium | Test: log record carries tenant/user/request id; scheduler counters surface |
| **P1** | RBAC boundaries unverified | Add tests: coach→admin route = 403/404; cross-parent invoice/payment read denied; admin cross-academy mutation denied | Prevent privilege-escalation & IDOR regressions | Low–Med | The three negative tests above |
| **P2** | Academy-admin audit trail incomplete | Emit a domain audit event from mutating use cases (refund, role change, price override, payout approval) | Tenant/compliance who-did-what | Medium | Test: each mutation writes an audit record |
| **P2** | Background-job failures silent | Register APScheduler `EVENT_JOB_ERROR` listener; log per-coach digest failures with reason | Catch failed billing/comms jobs | Low | Test: job error and digest failure produce a log line |
| **P2** | DDD infra leaks evade the linter | Relocate `MongoExpenseRepository`/`MongoPayoutRepository`, inline `_Enrollment*` classes, and `shared/comms` repo into `contexts/*/infrastructure/`; extend `TenantScopedRepository` | Keeps the tenant-literal tripwire effective on future edits | Medium | Existing structural tests + new no-raw-access assertions |
| **P2** | `default_academy_id` on request path | Gate composition fallback behind `saas_mode=False`; remove from SaaS request paths | Enforces AGENTS.md SaaS rule | Med (couples to P0) | Test: SaaS mode rejects default-academy fallback |
| **P3** | Parents can't message; refunds not visible parent-side | Add parent-initiated messaging endpoint + thread model; surface refunds in parent billing | Standard academy UX; reduces support load | Medium | Endpoint + ownership tests |
| **P3** | Internal tenant header / `x-forwarded-host` trust | Validate internal-tenant-header academy via `AcademyLookupPort`; confirm edge overwrites `x-forwarded-host` & strips internal header | Hardens tenant-selection primitive | Low | Test: unknown academy header rejected |

---

## Review Provenance

- Read-only review. The review itself made no code changes; this document is the only artifact produced.
- Coverage was judged from static reading (route signatures, use-case names, `import-linter` + structural-test results run read-only). "COVERED" means endpoints + use-cases exist; it does not certify runtime correctness.
- Known separate risk (project memory): latent dual Payment / AR-ledger billing model on one Mongo collection — warrants its own correctness pass.
