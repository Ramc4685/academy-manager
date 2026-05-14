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
ADMIN_PASSWORD=<initial strong password>
COOKIE_SECURE=true
FRONTEND_URL=https://academy.example.com
CORS_ORIGINS=https://academy.example.com
STRIPE_API_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
RESEND_API_KEY=re_...
SENDER_EMAIL=hello@academy.example.com
EMAIL_DELIVERY_ENABLED=true
```

Frontend build:

```bash
REACT_APP_BACKEND_URL=https://api.academy.example.com
```

Use exact origins for `FRONTEND_URL` and `CORS_ORIGINS`. Cookie auth will break if the frontend and API URLs do not match the configured origins.

## Local Container Smoke Test

```bash
docker compose up --build
curl http://127.0.0.1:8001/api/health
open http://localhost:3000
```

For a staging or production image, pass the public API URL into the frontend build:

```bash
docker build \
  --build-arg REACT_APP_BACKEND_URL=https://api.academy.example.com \
  -t academy-manager-frontend ./frontend
```

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
