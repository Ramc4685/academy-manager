# Badminton Academy Manager

Local full-stack app for managing a badminton academy: sessions, students, enrollments, attendance, payments, coach payouts, parent access, messaging, reports, and admin settings.

## Local Services

- Frontend: `http://localhost:3000`
- Backend API: `http://127.0.0.1:8001/api`
- MongoDB: `mongodb://127.0.0.1:27017`
- Local database name: `academy_manager_local`

## First-Time Setup

1. Create environment files:

   ```bash
   cp backend/.env.example backend/.env
   cp frontend/.env.example frontend/.env
   ```

2. Generate a local JWT secret and put it in `backend/.env`:

   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

3. Install backend dependencies:

   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. Install frontend dependencies:

   ```bash
   cd frontend
   yarn install
   ```

## Start Locally

Run these in separate terminals.

1. Start MongoDB:

   ```bash
   mkdir -p /tmp/academy-manager-mongo-local
   mongod --dbpath /tmp/academy-manager-mongo-local --bind_ip 127.0.0.1 --port 27017
   ```

2. Start the backend:

   ```bash
   cd backend
   source .venv/bin/activate
   uvicorn server:app --host 127.0.0.1 --port 8001 --reload
   ```

3. Start the frontend:

   ```bash
   cd frontend
   yarn start
   ```

Open `http://localhost:3000`.

## Admin Account

The backend seeds only the configured admin account on startup. Set `ADMIN_EMAIL`
in `backend/.env` before using the app outside local development. Demo coach and
parent accounts are not enabled unless `SEED_DEMO_ACCOUNTS=true` is explicitly
set.

## Firebase Auth

Production login uses Firebase Authentication for identity and MongoDB for app
roles and academy permissions. Firebase handles Google login, email/password,
and password reset. The backend maps the Firebase token to the local `users`
record by Firebase UID or by verified email on first login.

Backend:

```bash
FIREBASE_AUTH_ENABLED=true
FIREBASE_PROJECT_ID=academy-courtmastr
ADMIN_EMAIL=ramchand4685@gmail.com
```

Frontend:

```bash
REACT_APP_FIREBASE_AUTH_DOMAIN=academy-courtmastr.firebaseapp.com
REACT_APP_FIREBASE_PROJECT_ID=academy-courtmastr
REACT_APP_FIREBASE_STORAGE_BUCKET=academy-courtmastr.firebasestorage.app
REACT_APP_FIREBASE_MESSAGING_SENDER_ID=953230788846
REACT_APP_FIREBASE_APP_ID=1:953230788846:web:1f2819c11418ecf5860bff
REACT_APP_FIREBASE_MEASUREMENT_ID=G-Z6GS6WRZY8
```

Set `REACT_APP_FIREBASE_API_KEY` from the Firebase Web App config in deployment
secrets. Authorized Firebase domains must include `academy.courtmastr.com` and
`localhost` for local development.

## Import BLNO Spreadsheet Data

The importer loads sessions, coaches, parents, students, enrollments, attendance, and payment records from the spreadsheet.

```bash
cd backend
source .venv/bin/activate
BLNO_XLSX="/Users/ramc/Downloads/BLno-Badmintion-Training.xlsx" python scripts/import_blno.py
```

The script reads `MONGO_URL` and `DB_NAME` from `backend/.env`, keeps only the configured admin user, and replaces imported academy data collections.

## Stripe Local Testing

Stripe checkout is disabled until these values are set in `backend/.env`:

```bash
STRIPE_API_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

For webhook testing, run Stripe CLI in another terminal:

```bash
stripe listen --forward-to 127.0.0.1:8001/api/webhook/stripe
```

Copy the printed `whsec_...` value into `STRIPE_WEBHOOK_SECRET`, then restart the backend.

## Resend Email Safety

Email delivery is disabled by default in local/test environments, even when
`RESEND_API_KEY` is set. This prevents integration tests and manual local runs
from sending real parent emails.

Local/test email is always blocked. Do not use local/test for live email smoke
tests.

For production sending, set `APP_ENV=production` and
`EMAIL_DELIVERY_ENABLED=true`.

For production sending, verify the academy domain in Resend and update `SENDER_EMAIL` to a sender on that verified domain.

## Verification Commands

Backend tests:

```bash
cd backend
source .venv/bin/activate
pytest
```

Frontend build:

```bash
cd frontend
yarn build
```

Frontend tests:

```bash
cd frontend
yarn test --watchAll=false
```

## Deployment

Container files are included for staging smoke tests:

```bash
docker compose up --build
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for production environment variables, Stripe webhook setup, email configuration, health checks, and backup/restore expectations.

## Notes

- Keep real secrets only in `.env` files. Do not commit them.
- Use explicit CORS origins for cookie-based auth. Do not use `CORS_ORIGINS=*`.
- The app uses httpOnly JWT cookies, so frontend requests must use the configured backend URL and credentials.
