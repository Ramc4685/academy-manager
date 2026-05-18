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
SCHEDULER_TZ=America/Chicago
RESEND_API_KEY=re_...
SENDER_EMAIL=hello@academy.example.com
EMAIL_DELIVERY_ENABLED=false
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

## Phase 5 environment variables

The following variables were introduced in Phase 5 and must be set in production. Firebase env vars are documented above.

| Variable | Required | Description |
|---|---|---|
| `STRIPE_API_KEY` | Yes | Stripe secret key (`sk_live_...` or `sk_test_...`). Without this, all billing endpoints return 503. |
| `STRIPE_WEBHOOK_SECRET` | Yes | Stripe webhook signing secret (`whsec_...`). Without this, `POST /api/webhook/stripe` returns 503 and all Stripe payment confirmations are silently dropped. |
| `SCHEDULER_TZ` | No | IANA timezone for scheduled billing jobs. The backend default is `UTC`; production sets `America/Chicago` in `backend/fly.toml`. |

Set these on Fly with:

```bash
flyctl secrets set \
  STRIPE_API_KEY='sk_live_...' \
  STRIPE_WEBHOOK_SECRET='whsec_...' \
  -a courtmastr-academy-api
```

## Auth Migration Notes

With `FIREBASE_AUTH_ENABLED=true`:

- **Legacy routes are disabled.** `/api/auth/login`, `/api/auth/refresh`,
  `/api/auth/forgot-password`, and `/api/auth/reset-password` return **HTTP 410**.
  The frontend already routes those flows through Firebase.
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
curl http://127.0.0.1:8001/api/health
cd frontend-next
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

Keep `EMAIL_DELIVERY_ENABLED=false` until final production email verification is complete.

## Next Frontend

The only production frontend deployable is `frontend-next/`.

Build command:

```bash
cd frontend-next
pnpm build
```

Deploy command:

```bash
cd frontend-next
pnpm deploy:cloudflare
```

Production frontend environment:

```bash
BFF_API_ORIGIN=https://api.academy.courtmastr.com
NEXT_PUBLIC_API_BASE=/api/v2
```

`academy.courtmastr.com/*` is a Worker Route on the `academy-next` Cloudflare
Worker. The old CRA app under `frontend/` is deprecated and is not deployed by
GitHub Actions.

## Payments

1. Configure Stripe live or test keys.
2. Create a webhook endpoint pointing to `/api/webhook/stripe`.
3. Subscribe to checkout session events used by the app.
4. Store the Stripe webhook signing secret in `STRIPE_WEBHOOK_SECRET`.
5. Run a test registration checkout and confirm the registration payment changes from pending to paid.

Refunds are tracked in local payment records. Stripe payments are refunded through Stripe when the payment has a captured Stripe payment intent.

## Email

1. Verify the academy sending domain in Resend.
2. Set `SENDER_EMAIL` to an address on that verified domain.
3. Set `RESEND_API_KEY`.
4. Set `EMAIL_DELIVERY_ENABLED=true` only after the domain, sender, and test mailbox checks are complete.
5. Test password reset delivery from `/forgot-password`.

Email delivery is always blocked outside production, even when a real Resend key or `EMAIL_DELIVERY_MODE=live` is present. Email endpoints return skipped/blocked/failed status when Resend is not configured, delivery is safety-blocked, or provider delivery fails.

## Health And Monitoring

The backend exposes:

```bash
GET /api/health
```

Monitor this endpoint from the production region. Alert on non-2xx responses, elevated latency, and repeated application errors. Application logs should be shipped to the platform log drain or external logging service.

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

## Startup Indexes

The backend creates required Mongo indexes on startup through `backend/db.py`. There is not yet a versioned migration framework, so schema changes that need backfills should be shipped with explicit one-off scripts and a runbook entry.
