# SaaS local staging runbook

Spins up a local Docker stack that approximates the Wave 7 SaaS production
contract well enough to run `scripts/smoke/saas_readiness_smoke.sh` end to
end. Phase B (Cloudflare Tunnel) covers the gaps this leaves open — see
that section near the bottom.

## 5-second cheat sheet

```bash
make help          # show everything below

make up            # build, start, seed, show URLs + login credentials
make test          # run the SaaS readiness smoke (7 gates)
make saas-status   # what's running + where to point your browser + creds
make down          # stop (Mongo data preserved)
make saas-reset    # wipe seeded data, keep stack running (fast)
make saas-nuke     # stop + wipe everything (interactive confirm)
```

After `make up`, point your browser at the URL `make saas-status` prints
(typically `http://acme.localhost:3000/login`) and sign in with the
displayed email + password. The Firebase emulator handles auth — no real
Firebase project is touched.

## What this proves

- Backend boots in SaaS mode (`V2_SAAS_MODE=true`).
- Legacy `/api/*` runtime routes are absent from the v2 backend.
- `/api/v2/healthz` returns OK.
- Unknown tenant hosts return **401/403** at `/api/v2/me` (no anonymous tenant fallback).
- A seeded tenant + Firebase emulator user produces a valid Firebase ID token,
  and `/api/v2/me` returns **200** when called with that token + the
  approved internal tenant header.
- Frontend builds with `NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST` set, talks
  to the backend via the BFF proxy.
- Tenant-host frontend proxy calls preserve the browser `Authorization`
  header and tenant host through `/api/v2/me` when a seeded token is provided.
- No `default_academy_id` is used on SaaS request paths (enforced by the
  static smoke checks).
- No frontend SaaS code path calls legacy `/api/*` (enforced by the static
  smoke checks).

## What this does NOT prove

You will still need real staging (or Phase B tunnels) to satisfy:

- Real DNS / subdomain tenant resolution (here we use `/etc/hosts` or smoke
  defaults like `tenant-smoke.localhost`).
- Real cross-origin CORS — everything is on localhost.
- TLS / secure cookies / HSTS / CSP.
- Mongo backup/restore drill against a managed instance.
- Production-scale alerting and logging path for billing/webhook failures.
- Real Firebase token signature validation — the emulator signs unverified
  JWTs. Behavior is close, not identical.

## Prerequisites

- Docker Desktop running.
- `backend/.venv` exists (used by the seed script):

  ```bash
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -r backend/requirements.txt
  ```

- Ports 3000, 4000, 8001 and 9099 are free, or you accept that the default dev
  compose stack is down. Mongo's 27017 is handled for you: if something else
  already holds it — a Homebrew `mongod` is the usual culprit — `up` writes
  `.local/mongo-port-override.yml` and binds staging Mongo to **27018**
  instead. Nothing to do by hand; `saas-status` always prints the port that is
  actually bound. Delete that file to go back to 27017.
- A real public Firebase Web API key is available locally. Put it in
  `frontend/.env.local` or export it before starting the stack:

  ```bash
  NEXT_PUBLIC_FIREBASE_API_KEY=your-public-web-api-key
  ```

  The Auth emulator still handles local sign-in; this key is required so the
  Docker-built browser bundle initializes Firebase without falling back to a
  fake or dummy key.

## Bring it up

```bash
scripts/dev/saas_staging.sh up
```

Clean startup checklist:

1. Confirm Docker Desktop is running.
2. Confirm the default local ports are not already occupied by another stack:
   3000, 4000, 8001, 9099, and 27017.
3. Confirm `backend/.venv/bin/python` exists and has
   `backend/requirements.txt` installed.
4. Start from a stopped SaaS staging stack:
   `scripts/dev/saas_staging.sh down`. Use `nuke` only when you explicitly
   want to remove local staging Mongo/emulator volumes.
5. Run `scripts/dev/saas_staging.sh up` and wait for `/api/v2/healthz`.
6. Seed the desired tenant, then run smoke. Do not use production Mongo,
   production Firebase, real Stripe keys, or real email credentials.

What this does:

1. Generates `.local/saas-staging.env` with random `JWT_SECRET` and
   `ADMIN_PASSWORD` if it does not exist (gitignored).
2. Reads `NEXT_PUBLIC_FIREBASE_API_KEY` from the environment,
   `frontend/.env.local`, or `frontend/.env`, and fails early if it is missing.
3. Builds the frontend with `NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST=http://localhost:9099`.
4. Starts: `mongo`, `firebase-emulator` (auth-only), `backend`, `frontend`.
5. Waits for the backend to respond to `/api/v2/healthz`.

Stack identifier: `docker compose -p saas-staging ps` to inspect.

## Seed a tenant

```bash
scripts/dev/saas_staging.sh seed
```

This will:

- Generate a random emulator owner password (stored in
  `.local/saas-staging-credentials.json`, gitignored) on first run.
- Create a Firebase emulator user `admin@acme.localhost`.
- Upsert Mongo docs:
  - `academies` → slug `acme`, primary domain `acme.localhost`
  - `users` → owner, linked to Firebase UID
  - `academy_memberships` → active admin role
  - `academy_settings` → defaults
  - `platform_roles` → owner is also `platform_admin` so `/platform/*`
    routes work for testing
- Mint a fresh Firebase ID token and print smoke env exports.

## Run the smoke

```bash
scripts/dev/saas_staging.sh smoke
```

This re-runs the seed (to get a fresh ID token — they expire in 1 hour),
exports the right env vars, and runs `scripts/smoke/saas_readiness_smoke.sh`.

You should see:

```
Checking frontend source for legacy /api/* calls...
Checking SaaS request-path code for default_academy_id use...
Checking v2 health endpoint...
Checking legacy route is gone in SaaS mode...
Checking unknown tenant host does not get anonymous tenant access...
Checking approved internal tenant header path...
Checking frontend v2 proxy if frontend is reachable...
Checking tenant frontend login page and authenticated v2 proxy...
SaaS readiness smoke checks passed
```

## Common operator tasks

- **Look at logs**: `scripts/dev/saas_staging.sh logs backend` (or
  `frontend`, `mongo`, `firebase-emulator`).
- **Inspect containers**: `scripts/dev/saas_staging.sh ps`.
- **Stop without losing data**: `scripts/dev/saas_staging.sh down`.
- **Wipe Mongo + emulator state**: `scripts/dev/saas_staging.sh nuke`
  (interactive confirm).
- **Firebase Emulator UI**: http://localhost:4000 — inspect users, mint
  tokens manually.

## Reproducing a bug against the API

The fastest way to confirm a backend defect against realistic data: seed BLno,
mint a token for that tenant, and drive the admin API with `curl`.

```bash
scripts/dev/saas_staging.sh blno-seed
scripts/dev/saas_staging.sh seed --slug blno --domain blno.localhost
```

The second command prints a block of `export` lines — eval them into your
shell. Then every request needs **three** headers:

```bash
curl -s "$API_URL/api/v2/admin/sessions?window=upcoming" \
  -H "Host: blno.localhost" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "x-cm-proxy-auth: $PROXY_AUTH_VALUE"
```

The `Host` header is the part that trips people up. Since #571 the tenant is
resolved from the request host, and the `x-internal-tenant-id` header alone is
**not** enough — without a tenant `Host` you get a 401 whose body reads
`Auth.TenantUnresolved`, which looks like a broken token but is not.
`x-cm-proxy-auth` carries `V2_PROXY_SHARED_SECRET` (#519); the seed generates
it into `.local/saas-staging.env` and prints it as `PROXY_AUTH_VALUE`.

ID tokens expire after an hour — re-run the `seed` line to mint a fresh one.

To read the database directly (occurrences, statuses, payment rows):

```bash
docker exec saas-staging-mongo-1 mongosh academy_manager_saas_staging \
  --quiet --eval 'db.sessions.find({}, {session_id: 1, status: 1, _id: 0})'
```

### Running uncommitted code in the stack

`up-dev` bind-mounts `./backend` and reloads on save, so backend edits in
*this* checkout are live immediately. To point the stack at a **different**
worktree — verifying a fix branch without disturbing your main checkout —
layer an extra compose file:

```yaml
# /tmp/fix-stack.yml
services:
  backend:
    volumes:
      - /abs/path/to/worktree/backend:/app/backend
  frontend:
    volumes:
      - /abs/path/to/worktree/frontend:/app
      - frontend_saas_dev_node_modules:/app/node_modules
      - frontend_saas_dev_next:/app/.next
    environment:
      CI: "true"            # pnpm won't prompt to purge node_modules
      NODE_ENV: development
    command: ["pnpm", "dev", "--port", "3001"]
```

```bash
docker compose -p saas-staging \
  -f docker-compose.yml -f docker-compose.saas.yml \
  -f .local/mongo-port-override.yml -f docker-compose.saas-dev.yml \
  -f /tmp/fix-stack.yml up -d
```

Two things that will otherwise cost you twenty minutes: the frontend `command`
override is required because the base compose pins `next start`, and a
bind-mounted source tree shadows the image's baked `.next` production build;
and `CI=true` is required because pnpm aborts non-interactively when the
mounted lockfile disagrees with the shared `node_modules` volume.

## Manual /etc/hosts setup (optional)

The seeded tenant uses `acme.localhost`. macOS/Linux resolve `*.localhost`
to 127.0.0.1 automatically. If your platform does not, add to `/etc/hosts`:

```
127.0.0.1   acme.localhost
127.0.0.1   tenant-smoke.localhost
```

You can then visit `http://acme.localhost:3000` in a browser, log in as
`admin@acme-saas-staging.dev` (password from
`.local/saas-staging-credentials.json`), and exercise the SaaS frontend
against the emulator.

For the BLNO local staging tenant used in Wave 8 checks, seed with explicit
tenant fields and rerun the same non-destructive smoke:

```bash
scripts/dev/saas_staging.sh seed \
  --slug blno \
  --domain blno.localhost \
  --display-name "BLNO Badminton Academy" \
  --owner-email admin@blno-badminton.dev \
  --owner-name "BLNO Admin"

scripts/dev/saas_staging.sh smoke \
  --slug blno \
  --domain blno.localhost \
  --display-name "BLNO Badminton Academy" \
  --owner-email admin@blno-badminton.dev \
  --owner-name "BLNO Admin"
```

Then open `http://blno.localhost:3000/login`, sign in with
`admin@blno-badminton.dev` and the generated emulator password, and confirm
the admin pages load through `/api/v2/*` without 401/500 responses.

For the full BLNO demo-data seed, run:

```bash
scripts/dev/saas_staging.sh blno-seed
```

Then open `http://blno.localhost:3000/login`. Use this host for Docker SaaS
manual testing; tenant resolution is host-based, and stale references to
`blno-academy.localhost` are not the canonical local BLNO route.

The seed path is intended to be idempotent. Re-running the BLNO command
upserts the academy, owner user, active admin membership, academy settings,
and platform admin role, then mints a fresh emulator ID token. The generated
owner password is stored per owner email in `.local/saas-staging-credentials.json`.

There is no `scripts/dev/seed_blno_demo_data.py` in this branch. If a later
wave adds it, keep it local-only, idempotent, and safe to re-run against the
Docker Mongo/Firebase emulator stack.

## Wave 12 launch-candidate checks

This pass adds scaffolding only. Final signoff waits for Wave 10 and Wave 11
branches to merge.

```bash
scripts/smoke/saas_readiness_smoke.sh --static-only
cd frontend
NEXT_PUBLIC_E2E_AUTH_BYPASS=1 PLAYWRIGHT_PORT=3107 pnpm exec playwright test e2e/specs/saas-launch-route-matrix.spec.ts --project=chromium-mobile --workers=1 --trace=off --output=/tmp/academy-wave12-pw-results
```

The route matrix scaffold covers:

- admin dashboard, sessions, students, users, waitlist, pause requests,
  payments, dues, expenses, payouts, reports, messages, waivers, settings,
  and audit logs
- coach today
- parent payments

The HTTP smoke covers or explicitly skips:

- `/api/v2/healthz`
- legacy `/api/*` blocked in SaaS mode
- unknown tenant rejected
- authenticated request without tenant host/header rejected
- frontend proxy preserving `Authorization`
- frontend proxy preserving tenant host via `/api/v2/me`

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `up` hangs waiting for backend | Module-level import in legacy server died | `logs backend` — usually a missing env. Compare `.local/saas-staging.env` against `backend/.env.example`. |
| Smoke finds a legacy `/api/*` route still returning 200 | Backend booted through the old legacy runtime or stale containers are running | Recreate containers: `down` then `up`. Env-var changes in compose require recreation, not just restart. |
| Smoke fails: `/api/v2/me` returned 500 | Mongo collection state or emulator user mismatch | Re-run `seed`. If still broken, `nuke` and start over. |
| Frontend shows wrong API base in network tab | Build args are baked in at image build time | After changing `docker-compose.saas.yml` build args, run `up` again — it will rebuild. |
| Emulator UI at :4000 won't load | Emulator did not start cleanly | `logs firebase-emulator`. First run downloads a JAR; needs internet. |

## Phase B: Cloudflare Tunnel (real DNS + real CORS)

When you need real public URLs to satisfy the rest of the gate:

```bash
scripts/dev/saas_tunnel.sh up        # starts cloudflared sidecars
scripts/dev/saas_tunnel.sh smoke     # re-runs smoke against the public URLs
```

See `docker-compose.tunnel.yml` and `scripts/dev/saas_tunnel.sh`. This is
Phase B of the SaaS staging work — to be added in a follow-up commit.

## What to attach to the Wave 7 PR

After a clean run, paste in the PR comment:

- `scripts/dev/saas_staging.sh smoke` output showing the final
  `SaaS readiness smoke checks passed` line.
- `docker compose -p saas-staging ps` output (showing all four services healthy).
- Any deviations from this runbook.

## Stripe test mode (payments + Connect on staging)

The backend reads Stripe config from the container environment; the compose
stack already injects `.local/saas-staging.env` (git-ignored), so no compose
changes are needed. Append your **test-mode** values there:

```bash
# .local/saas-staging.env  (test mode only — never live keys)
STRIPE_API_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...   # printed by `stripe listen` below
```

Then restart the backend and forward webhooks:

```bash
docker compose -p saas-staging -f docker-compose.yml -f docker-compose.saas.yml up -d backend
stripe listen --forward-to http://127.0.0.1:8001/api/v2/parent/webhooks/stripe
```

Connect flow (Express account links — no `STRIPE_CONNECT_CLIENT_ID` needed):

1. Sign in as admin → Settings → payment gateway panel → start Stripe Connect.
2. Complete the Express onboarding in Stripe's test sandbox (any test data).
3. The gateway panel shows the connected-account status; once the account is
   ready for charges, parent "Set up autopay" / "Pay" produce real test-mode
   Checkout sessions, and the webhook forwarder updates the app ledger.

Until a connected account is ready, parent payment attempts fail with the
parent-safe message "Online payments aren't fully set up for your academy
yet…" — that is expected, not a bug.
