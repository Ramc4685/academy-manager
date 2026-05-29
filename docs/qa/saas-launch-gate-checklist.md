# SaaS Launch Gate Checklist

Date: 2026-05-23

Status: Wave 12 final candidate verification after Wave 10 and Wave 11 merges.
Static SaaS checks, backend v2 tests, frontend typecheck/lint/build, and the
Playwright route matrix passed. Full Docker SaaS staging smoke is still blocked
locally because Docker is unavailable in this environment and no local public
Firebase Web API key is exported for the frontend emulator build.

## Route And Tenant Enforcement

| Gate | Status | Evidence / next check |
| --- | --- | --- |
| SaaS route enforcement | Static PASS, HTTP blocked | `scripts/smoke/saas_readiness_smoke.sh --static-only` passed. Full HTTP smoke still needs Docker SaaS staging or prod-like stack. |
| Legacy `/api/*` removed | Backend test PASS, HTTP blocked | Full backend v2 suite passed; full HTTP smoke must confirm old `/api/*` paths return normal 404 while `/api/v2/*` works. |
| Unknown tenant rejected | Backend test PASS, HTTP blocked | Backend tenant tests passed through full v2 suite; full smoke remains blocked locally. |
| Tenant host required | Backend test PASS, HTTP blocked | Backend tenant tests passed through full v2 suite; frontend proxy smoke remains blocked locally. |
| Explicit tenant resolution | Partial PASS | Backend resolver coverage passed; real beta tenant DNS/subdomain/custom-domain records still need staging verification. |
| Frontend proxy preserves `Authorization` | Scaffold PASS, HTTP blocked | Playwright route matrix passed; authenticated frontend proxy smoke still needs seeded SaaS stack. |
| Frontend proxy preserves tenant host | Scaffold PASS, HTTP blocked | Playwright route matrix passed; tenant-host preservation still needs seeded SaaS stack. |
| `/api/v2/me` through frontend proxy | HTTP blocked | Requires seeded tenant, Firebase emulator token, and running frontend/backend stack. |

## Product And Domain Gates

| Gate | Status | Evidence / next check |
| --- | --- | --- |
| Membership auth | Backend PASS, smoke blocked | Full backend v2 suite passed after Wave 10/11 merge; prod-like smoke still pending. |
| No `default_academy_id` SaaS path | PASS | Static smoke passed. |
| Occurrence attendance | Backend PASS | Full backend v2 suite passed after Wave 10/11 merge. |
| Enrollment events | Backend PASS | Full backend v2 suite passed after Wave 11 lifecycle merge. |
| Billing ledger/idempotency | Backend PASS | Full backend v2 suite passed after Wave 11 payment merge. |
| Coach payout occurrence basis | Backend PASS | Full backend v2 suite passed; manual route smoke still pending. |
| Platform billing | Backend PASS, smoke blocked | Full backend v2 suite passed; Stripe-safe local/prod-like smoke still pending. |
| Governance/support | Backend PASS, smoke blocked | Full backend v2 suite passed; export/support route smoke still pending. |
| Platform audit | Backend PASS, smoke blocked | Full backend v2 suite passed; durable audit verification in prod-like stack still pending. |

## Local Verification Gates

| Gate | Status | Command |
| --- | --- | --- |
| Local SaaS stack startup | Blocked locally | Docker is unavailable in this environment and `NEXT_PUBLIC_FIREBASE_API_KEY` is not exported. |
| BLNO tenant seed | Blocked locally | Depends on local SaaS staging stack/Firebase emulator; run once Docker and a local public Firebase Web API key are available. |
| BLNO demo seed | Not present | `scripts/dev/seed_blno_demo_data.py` is absent in this branch. |
| SaaS readiness smoke | Static PASS, full blocked | `scripts/smoke/saas_readiness_smoke.sh --static-only` passed; full staging smoke remains blocked locally. |
| Playwright route matrix | PASS | `cd frontend && NEXT_PUBLIC_E2E_AUTH_BYPASS=1 PLAYWRIGHT_PORT=3107 pnpm exec playwright test e2e/specs/saas-launch-route-matrix.spec.ts --project=chromium-mobile --workers=1 --trace=off --output=/tmp/academy-wave12-pw-results` returned 17 passed. |
| Backend v2 verification | PASS | `cd backend && /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/python -m pytest v2/tests --override-ini="testpaths=v2/tests" -q` returned 548 passed. |
| Backend mypy | Blocked | `mypy --config-file pyproject.toml v2` fails with duplicate module names for `v2.contexts.billing.application.use_cases.admin_payment_ops` and `backend.v2.contexts.billing.application.use_cases.admin_payment_ops`. |
| Frontend typecheck/build | PASS | `cd frontend && pnpm typecheck && pnpm lint && pnpm build` passed. |
| Diff hygiene | PASS | `git diff --check` passed. |

## Launch Rule

Do not deploy from this checklist. Before onboarding a second academy or
enabling SaaS mode outside local test, rerun the full Docker/prod-like SaaS
smoke with local emulator credentials or approved staging credentials only.
