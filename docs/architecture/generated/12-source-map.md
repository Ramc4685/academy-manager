# 12 — Source Map

**Confidence: High**

Component → responsibility → primary files → dependencies → confidence. Use this as the
index from architecture concept to code.

| Component | Responsibility | Primary files | Dependencies | Notes | Confidence |
|---|---|---|---|---|---|
| App composition root | Build app, middleware, scheduler, DI wiring | `backend/v2/main.py` | all contexts, shared | Lifespan = composition + scheduler + tenant wiring | High |
| Settings | Env config + legacy fallbacks + prod validation | `backend/v2/shared/config/settings.py` | — | `V2_*` precedence; wildcard CORS forbidden | High |
| Tenancy middleware | Resolve tenant + load auth claims per request | `backend/v2/shared/auth/middleware.py`, `shared/tenancy/resolver.py` | identity, settings | SaaS vs single-academy branches | High |
| Auth claims | Verify token, resolve user/roles | `contexts/identity/application/use_cases/load_auth_claims.py` | firebase adapter, user/membership repos | email-verify enforcement | High |
| Firebase adapter | Verify Firebase ID tokens | `contexts/identity/infrastructure/firebase_admin_adapter.py`, `firebase_token_verifier.py` | firebase-admin | `check_revoked=True` | High |
| Persona guard | Route-level role enforcement | `backend/v2/shared/http/persona.py` | claims | 404 on missing role | High |
| Admin BFF | Admin persona routes | `backend/v2/interfaces/admin/*` | `composition/admin.py` | sessions, billing, payroll, registration, waivers | High |
| Coach BFF | Coach persona routes | `backend/v2/interfaces/coach/*` | `composition/coach.py` | today, attendance, teaching plan | High |
| Parent BFF | Parent persona routes + Stripe webhook | `backend/v2/interfaces/parent/*` | `composition/parent.py` | checkout, autopay, webhooks | High |
| Billing domain | Invoice/payment/ledger rules | `contexts/billing/domain/{models.py,ledger.py}` | — | allocation idempotency, void rules | High |
| Billing repos | Mongo persistence for billing | `contexts/billing/infrastructure/{mongo_payment_repo,mongo_billing_ledger_repo,mongo_stripe_dedup}.py` | Motor | dual model; orphan key lock | High |
| Stripe gateway | Stripe API wrapper | `contexts/billing/infrastructure/stripe_gateway.py` | stripe SDK | Real vs Fake gateway | High |
| Webhook handler | Process Stripe events into ledger | `contexts/billing/application/use_cases/handle_webhook_event.py` | dedup, ledger, gateway | large central module | High |
| Enrollment | Students, sessions, occurrences, enrollments | `contexts/enrollment/*` | identity | occurrence-based model | High |
| Onboarding | Applications + waivers | `contexts/onboarding/*` | enrollment, identity | acceptances vs signatures gap | High |
| Coaching | Attendance, feedback, rates | `contexts/coaching/*` | enrollment | occurrence-based attendance | High |
| Finance | Payouts, expenses, snapshots | `contexts/finance/*` | coaching, enrollment | versioned coach rates | Medium |
| Curriculum / progress | Programs/levels/skills + student progress | `contexts/curriculum/*`, `contexts/student_progress/*` | — | strong domain shape | High |
| Communications | Campaigns, deliveries, coach digests | `contexts/communications/*` | coaching, identity | Resend port + stub | High |
| Platform | Tenant lifecycle, audit, governance, platform billing | `contexts/platform/*` | identity | disabled in prod | Medium |
| Event infra | Outbox, dispatcher, dedup | `backend/v2/shared/{events,idempotency}/*` | Motor | dead-letter/replay collections | High |
| Migrations | Index/validator setup on boot | `backend/v2/migrations/runner.py`, `0132_launch_indexes_and_validators.py` | Motor | `_migration_registry` | High |
| Scheduler jobs | Resumes, webhook drain, digests | `backend/v2/main.py` (lifespan) | composition | in-process APScheduler | High |
| Frontend app | Persona UIs + route groups | `frontend/app/(admin|coach|parent|marketing|shared)/*` | lib/api, lib/auth | client-side role guards | High |
| Frontend API client | Token + tenant headers, dedup | `frontend/lib/api/client.ts`, `me.ts`, `admin.ts`, `coach.ts`, `parent.ts` | firebase | identity bridge | High |
| BFF proxy route | Same-origin forward to backend | `frontend/app/api/v2/[...path]/route.ts`, `lib/api/proxy-headers.ts` | BFF_API_ORIGIN | strips identity before forward | High |
| Frontend auth | Firebase Web SDK + persona guard | `frontend/lib/auth/{firebase,auth-domain,use-persona-auth}.ts` | firebase | first-party auth proxy | High |
| Backend deploy | Fly app + container | `backend/fly.toml`, `backend/Dockerfile` | — | region ord, :8001 | High |
| Frontend deploy | Cloudflare Worker | `frontend/wrangler.jsonc` | opennextjs-cloudflare | `academy-next` | High |
| CI/CD | Checks + gated deploy | `.github/workflows/production.yml` | Fly/Cloudflare tokens | production-approval gate | High |
| Local stack | Dev orchestration | `scripts/local_test_stack.sh`, `docker-compose*.yml` | mongo, firebase emulator | ports 27017/9099/8001/3001 | High |
| Test architecture | Backend + frontend + e2e | `backend/v2/tests/{unit,application,contract,interface}`, `frontend/e2e/specs/*`, `*.node-test.mjs` | pytest, playwright, node:test | cov gate >=70 | High |

## Test architecture (summary)

- **Backend**: `pytest v2/tests` split into `unit/`, `application/`, `contract/` (Mongo repo contracts), `interface/` (route tests); coverage gate `>=70` on `v2/shared`.
- **Frontend**: node test runner for `lib/api/*.node-test.mjs` + `lib/auth/*.node-test.mjs`; `pnpm typecheck`; `pnpm lint`.
- **E2E**: Playwright (`frontend/e2e/specs/*.spec.ts`) on `chromium-mobile` and `webkit-mobile`.
- Pre-push mirror: `scripts/dev/pre-push-checks.sh`.

## Confidence rubric

- **High**: all major components traced to specific files; main flows verified from code; no major gaps.
- **Medium**: core structure confirmed; some sub-components/runtime behavior need verification; 1–2 gaps.
- **Low**: major components inferred; >2 gaps; important runtime behavior unclear.

## Sources inspected

- All files referenced in docs 01–11.
