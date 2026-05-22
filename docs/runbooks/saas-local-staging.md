# SaaS local staging runbook

Spins up a local Docker stack that approximates the Wave 7 SaaS production
contract well enough to run `scripts/smoke/saas_readiness_smoke.sh` end to
end. Phase B (Cloudflare Tunnel) covers the gaps this leaves open — see
that section near the bottom.

## What this proves

- Backend boots in SaaS mode (`V2_ENABLED=1`, `V2_SAAS_MODE=true`).
- Legacy `/api/health` returns **410** (SaaS guard active).
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

- Ports 3000, 4000, 8001, 9099, 27017 are free, or you accept that the
  default dev compose stack is down.
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

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `up` hangs waiting for backend | Module-level import in legacy server died | `logs backend` — usually a missing env. Compare `.local/saas-staging.env` against `backend/.env.example`. |
| Smoke fails: `/api/health` returned 200 (expected 410) | Backend booted but `V2_SAAS_MODE` was not picked up | Recreate containers: `down` then `up`. Env-var changes in compose require recreation, not just restart. |
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
