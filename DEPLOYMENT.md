# Deployment Baseline

This app is ready to run in a containerized staging environment once real secrets, origins, email, Stripe, monitoring, and backups are configured.

## Required Production Environment

Backend:

```bash
APP_ENV=production
MONGO_URL=mongodb+srv://...
DB_NAME=academy_manager
JWT_SECRET=<64+ random hex chars>
ADMIN_EMAIL=<owner admin email>
# ADMIN_PASSWORD is only used when FIREBASE_AUTH_ENABLED is off. When Firebase
# is on, the admin row is provisioned in Mongo with no password_hash and the
# admin signs in via Firebase. When Firebase is off, ADMIN_PASSWORD must be
# set explicitly or seeding aborts.
ADMIN_PASSWORD=<initial strong password — only required when Firebase is disabled>
COOKIE_SECURE=true
FIREBASE_AUTH_ENABLED=true
FIREBASE_PROJECT_ID=academy-courtmastr
# Service account for Firebase Admin SDK (token verification + user delete).
# Provide ONE of: FIREBASE_CREDENTIALS_FILE (path), FIREBASE_CREDENTIALS_JSON
# (inline JSON), or rely on Application Default Credentials.
FIREBASE_CREDENTIALS_FILE=/secrets/firebase-service-account.json
FRONTEND_URL=https://academy.example.com
CORS_ORIGINS=https://academy.example.com
STRIPE_API_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
# Required when a separate Connect-scoped webhook endpoint is configured for
# connected-account events such as account.updated and capability.updated.
STRIPE_CONNECT_WEBHOOK_SECRET=whsec_...
SCHEDULER_TZ=America/Chicago
RESEND_API_KEY=re_...
SENDER_EMAIL=hello@academy.example.com
V2_EMAIL_DELIVERY_ENABLED=true
```

Frontend build:

```bash
BFF_API_ORIGIN=https://api.academy.example.com
NEXT_PUBLIC_API_BASE=/api/v2
NEXT_PUBLIC_FIREBASE_API_KEY=<firebase web api key>
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=academy-courtmastr.firebaseapp.com
NEXT_PUBLIC_FIREBASE_PROJECT_ID=academy-courtmastr
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=academy-courtmastr.firebasestorage.app
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=953230788846
NEXT_PUBLIC_FIREBASE_APP_ID=1:953230788846:web:1f2819c11418ecf5860bff
NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID=G-Z6GS6WRZY8
```

Use exact origins for `FRONTEND_URL` and `CORS_ORIGINS`. Firebase Auth must also
authorize the frontend host, currently `academy.courtmastr.com`.

## Mobile Google sign-in (first-party auth proxy)

With the default `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=academy-courtmastr.firebaseapp.com`,
the Google OAuth round-trip depends on storage on the `firebaseapp.com` origin,
which is **cross-site** from the tenant domains (`*.courtmastr.com`). Mobile
browsers (all iOS browsers, Brave, Chrome with third-party cookie phase-out)
block that storage, so popup sign-in errors and redirect sign-in silently
bounces back to `/login`. Desktop Chrome happens to still allow it.

Fix: serve the Firebase sign-in helper first-party. `next.config.ts` rewrites
`/__/auth/*` on every tenant domain to the `firebaseapp.com` helper, and
`NEXT_PUBLIC_FIREBASE_AUTH_PROXY=1` makes the SDK use the page's own host as
`authDomain` (see `frontend/lib/auth/auth-domain.ts`; localhost is exempt).

Rollout order — the flag must go last or Google sign-in breaks everywhere:

1. Google Cloud Console → APIs & Services → Credentials → the OAuth 2.0 web
   client auto-created by Firebase → add for EACH serving domain:
   - Authorized redirect URI: `https://<tenant-host>/__/auth/handler`
     (e.g. `https://blno-academy.courtmastr.com/__/auth/handler`)
   - Authorized JavaScript origin: `https://<tenant-host>`
2. Firebase Console → Authentication → Settings → Authorized domains:
   confirm each tenant host is listed (required already for desktop popup).
3. Verify the proxy is live: `curl -I https://<tenant-host>/__/auth/handler`
   should return the Firebase helper page (200), not the app's 404.
4. Set the GitHub repo variable `NEXT_PUBLIC_FIREBASE_AUTH_PROXY=1` (read by
   `.github/workflows/production.yml`) and redeploy the frontend.
5. Real-device test (BrowserStack or a phone): Google sign-in from iPhone
   Safari must land on `/admin` (or the persona home), and the backend must
   log a `GET /api/v2/me` for the session.

New tenant domains need step 1 repeated. Onboarding automation should add the
redirect URI alongside DNS/custom-domain setup.

## Phase 5 environment variables

The following variables were introduced in Phase 5 and must be set in production. Firebase env vars are documented above.

| Variable | Required | Description |
|---|---|---|
| `STRIPE_API_KEY` | Yes | Stripe secret key (`sk_live_...` or `sk_test_...`). Without this, all billing endpoints return 503. |
| `STRIPE_WEBHOOK_SECRET` | Yes | Stripe webhook signing secret (`whsec_...`). Without this, `POST /api/v2/parent/webhooks/stripe` returns 503 and all Stripe payment confirmations are silently dropped. |
| `STRIPE_CONNECT_WEBHOOK_SECRET` | Required for Connect | Signing secret for the Connect-scoped Stripe webhook endpoint that receives connected-account events (`account.updated`, `capability.updated`). Keep `STRIPE_WEBHOOK_SECRET` for account-level billing events. |
| `SCHEDULER_TZ` | No | IANA timezone for scheduled billing jobs. The backend default is `UTC`; production sets `America/Chicago` in `backend/fly.toml`. |

Set these on Fly with:

```bash
flyctl secrets set \
  STRIPE_API_KEY='sk_live_...' \
  STRIPE_WEBHOOK_SECRET='whsec_...' \
  STRIPE_CONNECT_WEBHOOK_SECRET='whsec_...' \
  -a courtmastr-academy-api
```

## SaaS v2 Production Readiness

SaaS mode uses the v2 backend runtime and remains launch-gated until the Wave 6
platform outputs are merged and verified. Do not enable SaaS mode in production until
`docs/requirements/2026-05-22-saas-production-readiness.md` has no
`BLOCKED BY WAVE 6` or unresolved `TODO` launch gates.

Required SaaS env additions:

```bash
V2_SAAS_MODE=true
# Only when an approved internal caller exists:
V2_ALLOWED_INTERNAL_TENANT_HEADER=X-Internal-Academy-Id
```

Before enabling `V2_SAAS_MODE=true`:

1. Wire platform billing, governance/export/support access,
   and platform audit persistence/routes.
2. Confirm tenant domain/subdomain records exist for the beta tenant.
3. Run:

```bash
scripts/smoke/saas_readiness_smoke.sh --static-only
```

Then run the full smoke against a prod-like SaaS environment:

```bash
API_URL=https://api.academy.example.com \
FRONTEND_URL=https://academy.example.com \
scripts/smoke/saas_readiness_smoke.sh
```

This smoke is non-destructive. It must not be pointed at production with real
auth tokens unless an operator explicitly approves that test.

## Auth Notes

The backend now runs `backend.v2.main:app` directly:

- **Legacy routes are removed.** `/api/auth/login`, `/api/auth/refresh`,
  `/api/auth/forgot-password`, and `/api/auth/reset-password` are not mounted and
  return normal **HTTP 404**.
- **Token verification uses Firebase Admin SDK** with `check_revoked=True`.
  Admin-disabling a user in the Firebase console takes effect on the next
  request — no waiting for token expiry.
- **Email verification is enforced server-side** for any `password`-provider
  token, both at signup and on every authenticated request. Google / Apple /
  phone identities are accepted as verified by their provider.
- **Invite acceptance requires Firebase identity first.** Invitees create their
  Firebase account (or sign in with Google) using the invited email, verify the
  email, then submit the invite token. No `password_hash` is stored.
- **Rollback owns Firebase too.** If a registration fails mid-flight after the
  Firebase user was created on the client, the backend deletes the Firebase
  user via the Admin SDK before re-raising.
- **Admin seeding** never plants a default password when Firebase is on. The
  admin Mongo row is provisioned without `password_hash`; sign-in goes through
  Firebase. Toggling Firebase OFF later therefore locks out the admin until
  `ADMIN_PASSWORD` is set and seeding re-runs.

**To turn Firebase off** (e.g., for an emergency fallback):

1. Set `FIREBASE_AUTH_ENABLED=false` and set a real `ADMIN_PASSWORD`.
2. Restart the backend. `seed_users` will plant the admin password hash.
3. Existing users linked only to Firebase will need passwords issued out-of-band
   (admin `/users/{id}/reset-password`) before they can sign in. There is no
   automatic password recovery for Firebase-linked users in legacy mode.

## Local Smoke Test

```bash
docker compose up --build
curl http://127.0.0.1:8001/api/v2/healthz
cd frontend
BFF_API_ORIGIN=http://127.0.0.1:8001 pnpm dev
open http://localhost:3001
```

## Fly.io Backend

The backend Fly app is `courtmastr-academy-api` in region `ord`.

Set required secrets before the first deploy:

```bash
cd backend
flyctl secrets set \
  MONGO_URL='mongodb+srv://...' \
  JWT_SECRET='<64+ random hex chars>' \
  ADMIN_EMAIL='ramchand4685@gmail.com' \
  ADMIN_PASSWORD='<initial strong password>' \
  FIREBASE_AUTH_ENABLED='true' \
  FIREBASE_PROJECT_ID='academy-courtmastr' \
  STRIPE_API_KEY='sk_live_...' \
  STRIPE_WEBHOOK_SECRET='whsec_...' \
  STRIPE_CONNECT_WEBHOOK_SECRET='whsec_...' \
  RESEND_API_KEY='re_...' \
  SENDER_EMAIL='noreply@academy.courtmastr.com' \
  -a courtmastr-academy-api
```

Deploy:

```bash
cd backend
flyctl deploy -a courtmastr-academy-api
flyctl status -a courtmastr-academy-api
flyctl logs -a courtmastr-academy-api
```

Keep `V2_EMAIL_DELIVERY_ENABLED=false` until final production email verification is complete.
Set it to `true` only after the Resend sender/domain is verified and parent
email delivery is intentionally approved.

## Next Frontend

The only production frontend deployable is `frontend/`.

Build command:

```bash
cd frontend
pnpm build
```

Deploy command:

```bash
cd frontend
pnpm deploy:cloudflare
```

Production frontend environment:

```bash
BFF_API_ORIGIN=https://api.academy.courtmastr.com
NEXT_PUBLIC_API_BASE=/api/v2
# Browser error capture + Web Vitals (optional). Create the Sentry project
# `courtmastr-frontend` first, then set its DSN; without it the SDK is never
# loaded. NEXT_PUBLIC_APP_ENV names the Sentry environment (default
# "production"); NEXT_PUBLIC_SENTRY_RELEASE tags events with a release.
NEXT_PUBLIC_SENTRY_DSN=
NEXT_PUBLIC_APP_ENV=production
```

`academy.courtmastr.com/*` is a Worker Route on the `academy-next` Cloudflare
Worker. The old CRA frontend has been removed and is not deployed by GitHub
Actions.

## Payments

1. Configure Stripe live or test keys.
2. Create an account-level webhook endpoint pointing to `/api/v2/parent/webhooks/stripe`.
3. Subscribe that account-level endpoint to checkout/payment events used by the app.
4. Store the account-level webhook signing secret in `STRIPE_WEBHOOK_SECRET`.
5. For Stripe Connect, create a Connect-scoped webhook endpoint pointing to the same path, subscribe it to `account.updated` and `capability.updated`, and store its signing secret in `STRIPE_CONNECT_WEBHOOK_SECRET`.
6. Run a test registration checkout and confirm the registration payment changes from pending to paid.

Refunds are tracked in local payment records. Stripe payments are refunded through Stripe when the payment has a captured Stripe payment intent.

## Email

1. Verify the academy sending domain in Resend.
2. Set `SENDER_EMAIL` to an address on that verified domain.
3. Set `RESEND_API_KEY`.
4. Set `V2_EMAIL_DELIVERY_ENABLED=true` only after the domain, sender, and test mailbox checks are complete.
5. Test password reset delivery from `/forgot-password`.

Email delivery is always blocked outside production, even when a real Resend key or `EMAIL_DELIVERY_MODE=live` is present. Email endpoints return skipped/blocked/failed status when Resend is not configured, delivery is safety-blocked, or provider delivery fails.

## Health And Monitoring

The backend exposes:

```bash
GET /api/v2/healthz
```

Monitor this endpoint from the production region. Alert on non-2xx responses, elevated latency, and repeated application errors. Application logs should be shipped to the platform log drain or external logging service.

## Production Release Records

The production GitHub Actions workflow publishes a `deploy-YYYY-MM-DD-<sha>`
release only after every changed component deploys successfully and production
smoke checks pass. Release content is aggregated from complete files under
`docs/release-notes/` since the previous `deploy-*` tag.

Publishing is idempotent and uses a job-scoped `GITHUB_TOKEN` with
`contents: write`; other validation and deploy jobs remain read-only. A
publishing failure happens after deployment, remains visible as a failed
workflow, and can be rerun safely. Never force, move, or reuse a production tag
for a different commit.

## Database Backups

Use managed MongoDB backups when available. For self-managed MongoDB, run scheduled backups and keep encrypted copies outside the app host.

Example backup:

```bash
mongodump --uri "$MONGO_URL/$DB_NAME" --archive=academy-manager-$(date +%F).archive --gzip
```

Example restore drill:

```bash
mongorestore --uri "$RESTORE_MONGO_URL/academy_manager_restore" --archive=academy-manager-YYYY-MM-DD.archive --gzip
```

Run a restore drill before launch and at least quarterly.

## Startup Migrations

The backend can run versioned, idempotent v2 Mongo migrations on startup
through `backend/v2/migrations/runner.py` when `V2_RUN_MIGRATIONS_ON_BOOT=true`.
Index and validator changes live under `backend/v2/migrations/`. Backfills
that need production operator judgment should still ship with explicit
dry-run-first scripts and a runbook entry.
