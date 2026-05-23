# SaaS v2 Production Readiness

Date: 2026-05-23

Status: Wave 12 launch-candidate verification after Wave 10 and Wave 11 merge.
Static SaaS checks, backend v2 verification, frontend typecheck/lint/build,
and the Playwright route matrix passed. Full local/prod-like SaaS HTTP smoke is
still blocked in this environment because Docker is unavailable and no local
public Firebase Web API key is exported for the frontend emulator build.

Scope:

- v2-only SaaS deployment configuration.
- Tenant routing, membership auth, billing, email, observability, governance,
  backup/recovery, CI, and smoke-test launch gates.
- Non-destructive readiness checks only. This document does not authorize a
  production deploy, real-secret use, production migration, or destructive data
  operation.

## Readiness Command

Use this command against a local or prod-like environment started with
`V2_ENABLED=1` and `V2_SAAS_MODE=true`:

```bash
scripts/smoke/saas_readiness_smoke.sh
```

Static-only checks can run without a live backend:

```bash
scripts/smoke/saas_readiness_smoke.sh --static-only
```

Optional internal-header smoke:

```bash
INTERNAL_TENANT_HEADER_NAME=X-Internal-Academy-Id \
INTERNAL_TENANT_HEADER_VALUE=tenant_smoke \
scripts/smoke/saas_readiness_smoke.sh
```

Only add `AUTH_TOKEN` when using a local emulator or test tenant token. Do not
paste production Firebase tokens into shell history.

## Launch Gate Checklist

| Area | Status | Gate |
| --- | --- | --- |
| SaaS mode config | PASS | `V2_SAAS_MODE`, `V2_ALLOWED_INTERNAL_TENANT_HEADER`, v2 Mongo/Firebase/Stripe fallbacks, and frontend `/api/v2` base are documented and test-covered. |
| v2-only route enforcement | PASS | `SaasLegacyRouteGuard` returns 410 for legacy `/api/*` in SaaS mode; frontend SaaS source check fails legacy calls. |
| Tenant routing | TODO | Resolver exists for subdomain, custom domain, and approved internal header. Launch still needs real beta tenant/domain records and suspended-tenant smoke in a prod-like SaaS environment. |
| Auth readiness | PASS | Membership claims, active/inactive membership rejection tests, and real Mongo membership/platform-role repository wiring are present for SaaS mode. |
| Billing/payment safety | BACKEND VERIFIED, SMOKE PENDING | Parent billing idempotency, platform billing, Wave 11 payment correctness, and full backend v2 tests passed. Launch still needs Stripe test/live runbook signoff and prod-like HTTP smoke. |
| Email/SMS safety | BACKEND VERIFIED, SMOKE PENDING | Legacy email safety and selected dues reminder backend/UI paths are present. Tenant-scoped reminder delivery still needs prod-like smoke. SMS remains not applicable until a provider exists. |
| Observability | PARTIAL | v2 structured logging, tracing, outbox/event audit, platform/admin audit context, and full backend v2 tests passed. Launch still needs alert rules and tenant-safe log-field review. |
| Data governance | BACKEND VERIFIED, SMOKE PENDING | Governance persistence/routes and full backend v2 tests passed. Launch still needs export artifact/storage runbook proof in prod-like staging. |
| Backup/recovery | TODO | Mongo backup expectations are documented; launch needs restore-drill evidence and tenant export path once governance is wired. |
| CI and smoke tests | PARTIAL PASS | GitHub CI passed on Wave 11 PRs; local static smoke/backend/frontend/Playwright gate passed on the merged candidate. Full SaaS HTTP smoke still needs Docker/prod-like staging. |
| Production deploy | NOT APPLICABLE | Wave 7 scaffolding does not deploy and does not mutate production data. |

Wave 12 launch-candidate addendum:

| Gate | Status | Required evidence before launch |
| --- | --- | --- |
| SaaS route enforcement | STATIC PASS, HTTP PENDING | Static smoke passed; full run still needs SaaS-mode local/prod-like stack. |
| Membership auth | BACKEND PASS, SMOKE PENDING | Full backend v2 suite passed after Wave 10/11 merge. |
| Explicit tenant resolution | BACKEND PASS, SMOKE PENDING | Backend tenant tests passed through the full suite; real tenant host/custom-domain/internal-header smoke remains pending. |
| No `default_academy_id` SaaS path | PASS | Static smoke passed. |
| Occurrence attendance | BACKEND PASS | Full backend v2 suite passed. |
| Enrollment events | BACKEND PASS | Wave 11 lifecycle tests and full backend v2 suite passed. |
| Billing ledger/idempotency | BACKEND PASS | Wave 11 payment tests and full backend v2 suite passed. |
| Coach payout occurrence basis | BACKEND PASS, SMOKE PENDING | Full backend v2 suite passed; manual prod-like route smoke remains pending. |
| Platform billing | BACKEND PASS, SMOKE PENDING | Full backend v2 suite passed; Stripe-safe local/prod-like smoke remains pending. |
| Governance/support | BACKEND PASS, SMOKE PENDING | Full backend v2 suite passed; export/support route smoke remains pending. |
| Platform audit | BACKEND PASS, SMOKE PENDING | Full backend v2 suite passed; prod-like durable audit check remains pending. |
| Local smoke | BLOCKED LOCALLY | Docker is unavailable and no local public Firebase Web API key is exported. |
| Full backend/frontend verification | PARTIAL PASS | Backend ruff/format and 548 v2 tests passed; frontend typecheck/lint/build passed; Playwright route matrix passed 17/17. Backend mypy remains blocked by the existing duplicate module-name failure for `admin_payment_ops.py`. |

Current production config note:

- `backend/fly.toml` enables `V2_ENABLED=1` but does not enable
  `V2_SAAS_MODE`. That is correct until the remaining platform billing and
  governance blockers are cleared.
- `backend/fly.toml` health-checks `/api/v2/healthz`, so enabling SaaS mode
  will not break Fly health checks through the legacy route guard.

## Configuration Gates

Backend production or prod-like SaaS env must set:

```bash
APP_ENV=production
V2_ENABLED=1
V2_SAAS_MODE=true
V2_MONGO_URL=mongodb+srv://...
V2_MONGO_DB=academy_manager
FIREBASE_AUTH_ENABLED=true
FIREBASE_PROJECT_ID=academy-courtmastr
FRONTEND_URL=https://academy.courtmastr.com
CORS_ORIGINS=https://academy.courtmastr.com
STRIPE_API_KEY=sk_live_...      # live only in production
STRIPE_WEBHOOK_SECRET=whsec_...
RESEND_API_KEY=re_...
EMAIL_DELIVERY_ENABLED=false    # until sender/domain and mailbox checks pass
```

Optional internal jobs/platform tooling:

```bash
V2_ALLOWED_INTERNAL_TENANT_HEADER=X-Internal-Academy-Id
```

Rules:

- `V2_ALLOWED_INTERNAL_TENANT_HEADER` must be unset unless an approved internal
  caller path exists.
- `V2_DEFAULT_ACADEMY_ID` is allowed only for local/non-SaaS compatibility. It
  is not a valid SaaS tenant source.
- `CORS_ORIGINS` must be explicit. Do not use `*` with cookie auth.
- Stripe test keys belong in local/staging only. Live keys belong only in
  production secret storage.
- Resend live email stays disabled until the production email gate is signed.

Frontend production build must set:

```bash
BFF_API_ORIGIN=https://api.academy.courtmastr.com
NEXT_PUBLIC_API_BASE=/api/v2
NEXT_PUBLIC_FIREBASE_API_KEY=<firebase web api key>
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=academy-courtmastr.firebaseapp.com
NEXT_PUBLIC_FIREBASE_PROJECT_ID=academy-courtmastr
```

## v2-Only Route Enforcement

Automated checks:

- `backend/v2/tests/interface/test_saas_routing.py`
- `scripts/smoke/saas_readiness_smoke.sh --static-only`
- `frontend/e2e/fixtures/tenant-isolation.ts`

Launch gate:

- `/api/v2/*` responds through the v2 app.
- Legacy `/api/*` returns 410 with `V2_SAAS_MODE=true`.
- Canonical SaaS frontend pages do not call legacy `/api/*`.

Operational exception:

- Existing non-SaaS production smoke still checks legacy `/api/health` and the
  current legacy Stripe webhook path. SaaS launch must either update that smoke
  profile or keep those checks explicitly outside the SaaS-mode gate.

## Tenant Routing

Resolution order:

1. Subdomain.
2. Verified custom domain.
3. Approved internal header, only when configured.

Expected behavior:

- Unknown tenant returns no claims and protected routes reject.
- Suspended, cancelled, or deletion-requested tenant returns a non-servable
  response before tenant-scoped route handlers run.
- Tenant is never inferred from user identity alone.

Remaining launch checks:

- Real `academies.slug` and custom-domain records must exist in the target env.
- Suspended tenant behavior must be smoke-tested after tenant lifecycle is
  merged and backed by persistent data.

## Auth Readiness

Required:

- Firebase token verification in production.
- Active `academy_memberships` row for the resolved tenant.
- Inactive membership rejected.
- Academy roles scoped to membership.
- Platform roles checked separately from academy roles.
- No `default_academy_id` in SaaS request paths.

Current status:

- In SaaS mode, `backend/v2/main.py` wires `MongoMembershipRepository` into
  `LoadAuthClaims` for academy membership and platform-role loading.
- In non-SaaS mode, temporary legacy adapters remain to preserve existing local
  and single-tenant compatibility.
- `POST /api/v2/platform/academies/bootstrap` is composed with
  `MongoTenantBootstrapStore`.

## Billing And Payment Safety

Required:

- Stripe live keys only in production secret storage.
- Stripe test keys only in local/staging.
- Webhook signature secret configured for the active endpoint.
- Webhook event idempotency verified by fixture replay.
- Invoice and allocation idempotency verified.
- No real Stripe calls in local tests; fake gateway remains default without
  complete Stripe config.

Current checks:

- `backend/v2/tests/contract/test_stripe_event_dedup.py`
- `backend/v2/tests/contract/test_billing_idempotency.py`
- `backend/v2/tests/application/test_webhook_handler.py`
- `backend/v2/tests/application/test_platform_billing.py`

Wave 6 blockers:

- Platform billing persistence/routes are not fully wired in the production BFF.
- Canonical SaaS Stripe webhook path needs final ops signoff before beta.

## Email And SMS Safety

Required:

- No real email from local/test.
- Production email requires `APP_ENV=production`, Resend secret, verified sender
  domain, and explicit delivery enablement.
- Dues/reminder generation must be tenant-scoped and idempotent.
- SMS stays hidden/disabled until a provider and policy exist.

Status:

- Email safety is documented for legacy production.
- v2 tenant-scoped reminder delivery needs a focused Wave 7/Wave 6 integration
  check before launch.

## Observability

Required before beta:

- JSON structured logs in production.
- `request_id`, trace/span IDs, and safe tenant `academy_id` included where
  available.
- No PII in structured log fields.
- Event/outbox audit visible for failed handlers and manual replays.
- Platform/admin actions write audit rows.
- Alerts for failed Stripe webhooks, payment lag, event dead letters, auth
  error spikes, and tenant status check failures.

Current files:

- `backend/v2/shared/observability/logging.py`
- `backend/v2/shared/observability/tracing.py`
- `backend/v2/shared/events/dispatcher.py`
- `docs/observability.md`

## Data Governance

Required before beta:

- Tenant export request path.
- Tenant deletion request path, beginning with review and soft delete only.
- Student data deletion request path.
- Retention policy.
- PII redaction defaults.
- Support access grant and audit.
- No runtime impersonation without approval, session scoping, visible banner,
  action restrictions, and expiry.

Current files:

- `docs/requirements/2026-05-22-saas-data-governance-and-support-access.md`
- `backend/v2/contexts/platform/governance/`
- `backend/v2/tests/application/test_tenant_governance.py`

Wave 6 blockers:

- Mongo persistence repositories are not wired.
- Platform BFF routes are not exposed.
- Export artifact generation worker does not exist.
- Support impersonation runtime is intentionally disabled.

## Backup And Recovery

Required before beta:

- MongoDB managed backups enabled.
- Restore drill completed into a non-production database.
- Tenant export path verified after governance persistence lands.
- No destructive restore command run against production.

Restore assumptions:

- Shared MongoDB remains the tenancy model.
- Restores are environment-level or restore-drill scoped until tenant export is
  implemented.
- Per-tenant hard deletion is not a launch feature.

## Verification Matrix

Backend:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/interface/test_saas_routing.py -q
pytest v2/tests/interface/test_tenant_resolution.py -q
pytest v2/tests/contract/test_saas_tenant_isolation.py -q
pytest v2/tests/test_no_raw_tenant_mongo_access.py -q
```

Frontend:

```bash
cd frontend
pnpm typecheck
pnpm build
```

Global:

```bash
scripts/smoke/saas_readiness_smoke.sh --static-only
git diff --check
git status --short --branch
```

Prod-like smoke, after starting the local stack with SaaS env:

```bash
API_URL=http://127.0.0.1:8001 \
FRONTEND_URL=http://localhost:3001 \
scripts/smoke/saas_readiness_smoke.sh
```

## Signoff Rule

Wave 7 may be marked ready only when every launch gate is `PASS` or explicitly
`NOT APPLICABLE`, every `BLOCKED BY WAVE 6` item has been reclassified with
evidence, and the verification matrix has been run against the intended beta
environment.
