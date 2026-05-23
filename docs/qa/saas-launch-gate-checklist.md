# SaaS Launch Gate Checklist

Date: 2026-05-22

Status: Wave 12 documentation and test scaffolding only. Final launch-gate
verification is blocked until Wave 10 and Wave 11 branches are merged into the
candidate branch and the local/prod-like stack is smoke-tested end to end.

## Route And Tenant Enforcement

| Gate | Status | Evidence / next check |
| --- | --- | --- |
| SaaS route enforcement | Scaffolded | `scripts/smoke/saas_readiness_smoke.sh` checks v2 health, legacy `/api/health` 410, frontend legacy `/api/*` static leaks, and frontend route matrix v2-only calls. |
| Legacy `/api/*` blocked | Scaffolded | Full HTTP smoke must run with `V2_ENABLED=1` and `V2_SAAS_MODE=true`. |
| Unknown tenant rejected | Scaffolded | Smoke checks unknown tenant host at `/api/v2/me`, with and without auth when `AUTH_TOKEN` is provided. |
| Tenant host required | Scaffolded | Smoke rejects authenticated `/api/v2/me` without tenant host/header; frontend proxy also rejects auth-only `/api/v2/me`. |
| Explicit tenant resolution | Blocked for final signoff | Requires beta tenant DNS/subdomain/custom-domain records after Wave 10/11 merge. |
| Frontend proxy preserves `Authorization` | Scaffolded | Tenant frontend `/api/v2/me` smoke expects 200 with seeded `AUTH_TOKEN`. |
| Frontend proxy preserves tenant host | Scaffolded | Tenant frontend `/api/v2/me` smoke depends on proxy `x-forwarded-host` preservation. |
| `/api/v2/me` through frontend proxy | Scaffolded | `TENANT_FRONTEND_URL` + `AUTH_TOKEN` path in smoke. |

## Product And Domain Gates

| Gate | Status | Evidence / next check |
| --- | --- | --- |
| Membership auth | Blocked for final signoff | Must verify active membership, inactive membership rejection, and platform role separation against merged candidate. |
| No `default_academy_id` SaaS path | Scaffolded | Static smoke scans `backend/v2/interfaces`, `backend/v2/shared/auth`, and `backend/v2/shared/tenancy`. |
| Occurrence attendance | Blocked by Wave 10/11 merge | Run backend v2 tests and coach attendance smoke after merge. |
| Enrollment events | Blocked by Wave 10/11 merge | Verify event/audit persistence and route behavior after merge. |
| Billing ledger/idempotency | Blocked by Wave 10/11 merge | Replay focused billing/idempotency tests and SaaS smoke after merge. |
| Coach payout occurrence basis | Blocked by Wave 10/11 merge | Verify payout computation is occurrence-based, not schedule-template-based. |
| Platform billing | Blocked by Wave 10/11 merge | Verify platform billing persistence/routes and Stripe-safe local/test config. |
| Governance/support | Blocked by Wave 10/11 merge | Verify export/support-access routes, persistence, audit, and disabled impersonation policy. |
| Platform audit | Blocked by Wave 10/11 merge | Verify platform/admin actions write durable audit rows. |

## Local Verification Gates

| Gate | Status | Command |
| --- | --- | --- |
| Local SaaS stack startup | Pending | `scripts/dev/saas_staging.sh up` |
| BLNO tenant seed | Pending | `backend/.venv/bin/python scripts/dev/seed_saas_staging.py --slug blno --domain blno.localhost --display-name "BLNO Badminton Academy" --owner-email admin@blno-badminton.dev --owner-name "BLNO Admin"` |
| BLNO demo seed | Not present | `scripts/dev/seed_blno_demo_data.py` is absent in this branch. |
| SaaS readiness smoke | Pending | `scripts/dev/saas_staging.sh smoke --slug blno --domain blno.localhost --display-name "BLNO Badminton Academy" --owner-email admin@blno-badminton.dev --owner-name "BLNO Admin"` |
| Playwright route matrix | Scaffolded | `cd frontend && NEXT_PUBLIC_E2E_AUTH_BYPASS=1 PLAYWRIGHT_PORT=3107 pnpm exec playwright test e2e/specs/saas-launch-route-matrix.spec.ts --project=chromium-mobile --workers=1 --trace=off --output=/tmp/academy-wave12-pw-results` |
| Backend v2 verification | Pending | `cd backend && source .venv/bin/activate && pytest v2/tests -q` |
| Frontend typecheck/build | Pending | `cd frontend && pnpm typecheck && pnpm build` |
| Diff hygiene | Pending | `git diff --check` |

## Launch Rule

Do not mark Wave 12 launch gates complete from this branch alone. Re-run this
checklist after Wave 10 and Wave 11 branches are merged, using local emulator
credentials only. Do not deploy and do not use real secrets during local gate
verification.
