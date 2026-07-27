# MT3 — Real-auth e2e job in CI

Status: DONE (PR #361, 2026-07-27)
Size: M · Depends on: none · Tracker: ../TRACKER.md

## Problem

Every Playwright run in CI uses the auth bypass (`NEXT_PUBLIC_E2E_AUTH_BYPASS`), so the real login path — Firebase sign-in → backend `/me` → persona redirect — is never exercised automatically. A real-auth config exists (`frontend/playwright.local-auth.config.ts`) but is only run manually against a local stack. Auth regressions (token verification, cookie/session handling, persona routing) ship blind.

## Current behavior (verified 2026-07-20)

- CI jobs `frontend-e2e-chromium` (`.github/workflows/production.yml:250`, runs `pnpm exec playwright test --project=chromium-mobile` :288) and `frontend-e2e-webkit` (:297, `--project=webkit-mobile` :335) use `frontend/playwright.config.ts` — bypass-based, no backend/emulator services.
- `frontend/playwright.local-auth.config.ts`: `testMatch: ["local-auth-qa.spec.ts", "local-auth-inventory.spec.ts"]` in `./e2e/specs`; baseURL guarded by `assertLocalAuthBaseURL` — allows only `http://` on hosts `localhost`, `127.0.0.1`, `blno.localhost` (default `http://blno.localhost:3000`); single project `local-auth-chromium-mobile` (Pixel 7); evidence dir defaults under `/tmp/academy-manager-local/...`; `forbidOnly: !!process.env.CI` (CI-aware already).
- `scripts/local_test_stack.sh`: process-based local stack — MongoDB (127.0.0.1:27017), Firebase **Auth emulator** (127.0.0.1:9099, project `academy-courtmastr`, UI :4000), backend uvicorn :8001, frontend :3001. Commands: `fresh` (stop → start all → seed demo data), `infra`, `app`, `seed` (destructive drop+reseed), `smoke`, `stop`. Firebase emulator needs `firebase-tools` (Java + npm).
- Alternative stack: `make up` = `saas-up saas-seed saas-status` (docker-compose.saas.yml) — the Docker SaaS staging sandbox, which serves the `blno.localhost` tenant host the local-auth config defaults to.
- Existing real-auth specs `frontend/e2e/specs/local-auth-qa.spec.ts` / `local-auth-inventory.spec.ts` are broad QA sweeps (written for a manual audit) — too heavy/flaky for a CI gate.

## Proposed change

Add one CI job (`frontend-e2e-real-auth`) that boots Mongo + Firebase Auth emulator + backend + frontend inside the runner (reuse `scripts/local_test_stack.sh`; fall back to `make up` docker compose only if the script proves runner-hostile), seeds a known user, and runs a **new minimal smoke spec**: real email/password login against the emulator → backend `/me` returns the persona → frontend redirects to the persona home. No real secrets — the emulator accepts any project-scoped credentials.

## Implementation steps

1. **Write the minimal spec** `frontend/e2e/specs/real-auth-smoke.spec.ts`:
   - Navigate to login page; sign in with a seeded admin (and ideally one parent) via the real form.
   - Assert network call to backend `/me` succeeds (200, correct persona in payload) using `page.waitForResponse`.
   - Assert redirect lands on the persona home (`/admin` for admin; parent dashboard for parent) and a signed-in element renders.
   - Negative case: unauthenticated visit to `/admin` redirects to login. Keep total runtime under ~2 min.
2. **Add the spec to the config**: extend `testMatch` in `frontend/playwright.local-auth.config.ts` with `"real-auth-smoke.spec.ts"` — or better, add a dedicated `playwright.ci-real-auth.config.ts` that matches only the smoke spec (keeps the manual QA sweeps out of CI). Reuse `assertLocalAuthBaseURL`.
3. **Seed strategy**: use the stack's existing seeder (`scripts/local_test_stack.sh seed` — drops and reseeds demo data into local Mongo and creates matching emulator users; verify by reading the seed script it invokes). The spec must reference seeded fixture credentials from one place (e.g. `frontend/e2e/fixtures/real-auth-users.ts`) so seed and spec can't drift. If the current seeder doesn't create Firebase-emulator users, add that (emulator REST API `POST /identitytoolkit.googleapis.com/v1/accounts:signUp` on :9099 — no credentials needed).
4. **CI job** in `.github/workflows/production.yml`, modeled on `frontend-e2e-chromium` (:250-296):
   - `needs: [changes]`, same `if:` gating plus `needs.changes.outputs.backend == 'true'` (auth spans both sides).
   - Steps: checkout; setup Python 3.12 + `pip install -r backend/requirements.txt` (cache like :102); setup pnpm 11 / Node 22 (like :266-276); `npm i -g firebase-tools`; setup Java 17 (`actions/setup-java`, required by the emulator); start Mongo (simplest: `services: mongo: image: mongo:7` service container on 27017, letting the stack script skip its own mongod — it checks the port first via `port_pids`); run `scripts/local_test_stack.sh fresh` (exports `FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099` for the backend so token verification hits the emulator — verify the script does this; it defines the var at :20); `scripts/local_test_stack.sh smoke` as readiness gate.
   - Run: `pnpm exec playwright test --config=playwright.ci-real-auth.config.ts` with `LOCAL_AUTH_BASE_URL=http://localhost:3001` (the script's frontend port) and `LOCAL_AUTH_EVIDENCE_DIR=$RUNNER_TEMP/real-auth-evidence`.
   - Upload evidence dir as artifact on failure (like :290-296); `timeout-minutes: 15`.
   - **Secrets needed: none.** Emulator project id `academy-courtmastr` is public config; no live Firebase/Stripe keys. Assert the job env contains no `FIREBASE_*` prod secrets.
5. **Wire into the gate**: add the job to the `production-approval` `needs` list (production.yml:345) so it blocks deploys like the other e2e jobs. Optionally start it `continue-on-error: true` for one week to measure flake, then promote — mirror how the repo handles advisory jobs (see `backend-advisory`).

## Files to change

- New: `frontend/e2e/specs/real-auth-smoke.spec.ts`
- New: `frontend/playwright.ci-real-auth.config.ts` (or extend `frontend/playwright.local-auth.config.ts`)
- New: `frontend/e2e/fixtures/real-auth-users.ts`
- `.github/workflows/production.yml` (new job + `production-approval.needs`)
- Possibly `scripts/local_test_stack.sh` (CI-friendliness: non-interactive, respect pre-provisioned Mongo service, emulator user seeding)

## Tests & verification

- Local dry-run: `scripts/local_test_stack.sh fresh` then `pnpm exec playwright test --config=playwright.ci-real-auth.config.ts` passes on a laptop.
- Push a branch touching only the workflow → job runs green in CI; re-run 3× to check flake before gating deploys.
- Deliberately break seeding (wrong password in fixture) → job fails with a readable trace artifact — proves it actually tests auth.

## Risks / rollback

- Runner flake from four processes + emulator JVM startup: mitigate with the `smoke` readiness gate, generous `expect` timeouts (config already sets 10s), retries: 1 in the CI config, and the advisory-first rollout.
- The stack script was written for macOS laptops (`lsof`, `/tmp` paths) — test on `ubuntu-latest` early; if it fights the runner, fall back to `make up` (docker-compose.saas.yml) which is Linux-native, and point `LOCAL_AUTH_BASE_URL` at `http://blno.localhost:3000` with an `/etc/hosts` entry.
- Memory note (PR #304): the prod-Firebase enumeration behavior is NOT emulated — this job validates the login flow, not prod Firebase quirks; don't oversell its coverage in the release note.
- Rollback: delete the job from the workflow; nothing else depends on it.

## PR checklist

- [ ] Release note (per AGENTS.md `docs/release-notes/`)
- [ ] TRACKER.md updated
- [ ] Plan Status flipped to DONE
