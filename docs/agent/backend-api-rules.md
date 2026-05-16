# Backend and API Rules

Use this file for FastAPI, MongoDB, Firebase Auth, Stripe, Resend, scheduler, backend tests, and v2 BFF/API changes.

---

## Commands

Legacy backend:

```bash
cd backend
source .venv/bin/activate
pytest
uvicorn server:app --host 127.0.0.1 --port 8001 --reload
```

Focused tests:

```bash
cd backend
source .venv/bin/activate
pytest tests/test_firebase_auth.py
pytest tests/test_stripe_webhook_idempotency.py
pytest tests/test_coach_today.py
```

v2 backend, when present:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests
uvicorn v2.main:app --reload --port 8001
```

---

## Legacy Backend Rules

- Legacy app entry point is `backend/server.py`.
- Legacy routers live under `backend/routers/`.
- Shared legacy services live under `backend/services/`.
- Keep legacy fixes narrow and compatible with existing `/api/*` clients.
- Do not move legacy code into v2 as part of an unrelated bug fix.
- Preserve httpOnly cookie behavior.
- Preserve explicit CORS origins. Do not use wildcard origins with credentials.

---

## v2 Backend Rules

- Mount v2 only behind the configured gate when the branch supports it.
- Keep `/api/v2/*` paths persona-first: `/api/v2/coach/*`, `/api/v2/parent/*`, `/api/v2/admin/*`.
- Interfaces must call application use cases.
- Application use cases must use ports/protocols.
- Infrastructure owns MongoDB and external providers.
- Tenant or academy scoping must be applied consistently through the v2 repository layer when present.
- Add or update v2 tests alongside each v2 workflow.

---

## MongoDB Rules

- Use Motor/PyMongo APIs already established in the repo.
- Create indexes through startup/index helpers or v2 migrations, not ad hoc shell changes.
- Avoid destructive collection operations unless the user explicitly asks.
- Do not change production data shape without a migration or compatibility plan.
- Integration tests should clean up their own test data when possible.

---

## Auth Rules

Production auth uses Firebase Authentication plus MongoDB app roles.

- Firebase token verification belongs in backend auth infrastructure.
- JWT/Firebase identity proves who the user is; app role and academy access still come from MongoDB/app records.
- When `FIREBASE_AUTH_ENABLED=true`, legacy password endpoints may be disabled or return 410 by design.
- Email verification is enforced server-side for password-provider Firebase users.
- Never store Firebase service account JSON in git.

---

## Stripe and Billing Rules

- Stripe API and webhook secrets must come from environment variables.
- Webhook handling must be idempotent.
- Do not undo Stripe-paid payments manually unless the code path explicitly supports refund/adjustment semantics.
- Local Stripe webhook testing uses:

```bash
stripe listen --forward-to 127.0.0.1:8001/api/webhook/stripe
```

---

## Email Rules

- Local/test email delivery is safety-blocked.
- Do not enable live email in local/test.
- Production sending requires `APP_ENV=production` and `EMAIL_DELIVERY_ENABLED=true`.
- Resend failures should be surfaced as provider status, not hidden as successful sends.

---

## API Error Rules

- Return structured errors.
- Keep status codes meaningful.
- Do not leak cross-persona data existence.
- Keep auth failures and permission failures consistent with existing route behavior.

---

## OpenAPI Rules

When v2 OpenAPI generation is present:

- Regenerate frontend types after changing v2 response/request shapes.
- Commit generated types only if the project convention requires it.
- Treat OpenAPI drift as a real contract failure.
