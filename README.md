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

## Demo Accounts

The backend seeds these accounts on startup:

| Role | Email | Password |
| --- | --- | --- |
| Admin | `admin@badminton.app` | `Admin@12345` |
| Coach | `coach@badminton.app` | `Coach@12345` |
| Parent | `parent@badminton.app` | `Parent@12345` |

You can change the admin email/password in `backend/.env` with `ADMIN_EMAIL` and `ADMIN_PASSWORD`.

## Import BLNO Spreadsheet Data

The importer loads sessions, coaches, parents, students, enrollments, attendance, and payment records from the spreadsheet.

```bash
cd backend
source .venv/bin/activate
BLNO_XLSX="/Users/ramc/Downloads/BLno-Badmintion-Training.xlsx" python scripts/import_blno.py
```

The script reads `MONGO_URL` and `DB_NAME` from `backend/.env`, keeps the seeded demo users, and replaces imported academy data collections.

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
