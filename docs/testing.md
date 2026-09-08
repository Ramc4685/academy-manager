# Testing Runbook

This is the maintained testing guide for CourtMastr Academy Manager. Keep this
file current when test commands, local stack behavior, staging setup, or CI
expectations change.

For task status and handoffs, keep using `test_result.md` as the index and
`docs/test-results/active/` as the per-task ledger directory.

## Quick Decision Guide

| Situation | Use |
| --- | --- |
| Small backend change | Focused `pytest` for touched area, then broader v2 tests if risk is shared |
| Small frontend change | Focused node/unit test if present, then `pnpm typecheck` |
| UI behavior change | Local stack plus browser verification |
| Auth, tenant, billing, or BFF routing change | SaaS staging smoke |
| Broad launch or "all user-facing" confidence | Production-scale local audit |
| Before pushing | `scripts/dev/pre-push-checks.sh` |

## Test Result Ledger

At the start of a task:

```bash
git status --short --branch
sed -n '1,160p' test_result.md
ls docs/test-results/active
```

If no active ledger exists for the task:

```bash
scripts/dev/test_result.py start "task title" --problem "What needs to be verified"
```

During and after work:

```bash
scripts/dev/test_result.py log task-title --agent main --status working --message "What changed"
scripts/dev/test_result.py verify task-title --message "Command/result or skipped check reason"
scripts/dev/test_result.py close task-title
```

Rules:

- Do not manually restore the old global YAML ledger in `test_result.md`.
- Record exact commands and results, not broad claims.
- Keep skipped checks explicit, with the reason.
- Do not close a ledger as complete if the relevant acceptance criteria are not
  actually verified.

## Local App Stack

Use this for day-to-day manual testing outside Docker.

```bash
scripts/local_test_stack.sh fresh     # full local reset: stop, start, seed
scripts/local_test_stack.sh all       # start everything, skip already-running, smoke
scripts/local_test_stack.sh status    # show running services and ports
scripts/local_test_stack.sh infra     # MongoDB + Firebase Auth emulator only
scripts/local_test_stack.sh app       # backend + frontend only; infra must be up
scripts/local_test_stack.sh smoke     # health checks
scripts/local_test_stack.sh seed      # seed demo data
scripts/local_test_stack.sh test      # backend v2 tests + frontend typecheck
scripts/local_test_stack.sh logs      # tail service logs
scripts/local_test_stack.sh stop      # stop processes started by this script
```

Local services:

| Service | URL |
| --- | --- |
| Backend | `http://127.0.0.1:8001` |
| Frontend | `http://localhost:3001` |
| MongoDB | `mongodb://127.0.0.1:27017` |
| Firebase Auth emulator | `http://127.0.0.1:9099` |

One-time setup:

- Put a real public Firebase Web API key in `frontend/.env.local`.
- The browser only receives `NEXT_PUBLIC_FIREBASE_*` values.
- Never use `dummy`; Firebase Auth fails silently with a fake browser key.

Auth emulator guardrails:

- Frontend emulator URL includes protocol:
  `NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST=http://127.0.0.1:9099`.
- Backend Admin SDK emulator host uses host and port only:
  `FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099`.
- After starting frontend auth flows, sign in once in a browser and confirm
  Firebase calls reach the emulator without `auth/invalid-api-key`.

Tenant URLs:

- Local stack BLNO: `http://blno.localhost:3001`
- Plain local fallback: `http://localhost:3001`

## Docker SaaS Staging

Use Docker SaaS staging when testing SaaS tenant resolution, BFF proxy behavior,
Firebase emulator auth, v2-only runtime behavior, or BLNO staging data.

Main commands:

```bash
scripts/dev/saas_staging.sh up          # production-like Docker build
scripts/dev/saas_staging.sh up-dev      # hot-reload Docker mode
scripts/dev/saas_staging.sh blno-seed   # seed BLNO realistic data
scripts/dev/saas_staging.sh seed        # seed generic acme tenant
scripts/dev/saas_staging.sh status      # containers, URLs, credentials
scripts/dev/saas_staging.sh smoke       # SaaS readiness smoke
scripts/dev/saas_staging.sh logs backend
scripts/dev/saas_staging.sh down        # stop, keep volumes
scripts/dev/saas_staging.sh reset       # wipe staging Mongo/emulator users, keep stack
scripts/dev/saas_staging.sh nuke        # stop and remove volumes; destructive
```

Use `up-dev` while building/debugging:

- Frontend source is volume-mounted and runs through Next dev.
- Backend source is volume-mounted and uvicorn reloads on Python changes.
- You usually do not rebuild after every edit.

Use `up` for production-like verification:

- Frontend `NEXT_PUBLIC_*` values are baked into the Docker image.
- Rebuild after changing `docker-compose.saas.yml` build args, frontend
  Dockerfile, frontend dependency lockfiles, or build-time environment.

Targeted rebuilds:

```bash
scripts/dev/saas_staging.sh rebuild-ui
scripts/dev/saas_staging.sh rebuild-api
```

Docker SaaS staging services:

| Service | URL |
| --- | --- |
| Frontend | `http://localhost:3000` |
| BLNO tenant | `http://blno.localhost:3000/login` |
| Backend API | `http://127.0.0.1:8001` |
| Health | `http://127.0.0.1:8001/api/v2/healthz` |
| Firebase Emulator UI | `http://localhost:4000` |
| MongoDB | `mongodb://127.0.0.1:27017/academy_manager_saas_staging` |

Full details live in `docs/runbooks/saas-local-staging.md`.

## Focused Commands

Backend:

```bash
cd backend
source .venv/bin/activate
pytest
pytest v2/tests -q
```

When running ruff manually, activate `backend/.venv` first. The system ruff
version can differ from CI.

```bash
cd backend
source .venv/bin/activate
ruff format --check v2
ruff check v2
```

Frontend:

```bash
cd frontend
pnpm install
pnpm typecheck
pnpm lint
pnpm build
pnpm generate:api
node --no-warnings --test lib/api/*.node-test.mjs lib/auth/*.node-test.mjs
```

Container build smoke only:

```bash
docker compose up --build
curl http://127.0.0.1:8001/api/v2/healthz
```

Docker compose build smoke is not a substitute for auth testing. The generic
Docker path may use dummy Firebase browser config, so Firebase Auth browser
flows can fail there.

## Pre-Push Checks

Install hooks once:

```bash
scripts/dev/install-hooks.sh
```

Run before every push:

```bash
scripts/dev/pre-push-checks.sh
scripts/dev/pre-push-checks.sh --full   # force E2E
```

The script is change-aware and fail-fast (PR #477): it classifies the
outgoing diff and runs only the tier that matches. The full 3,600-test
backend suite and all frontend suites remain the enforced CI merge gate —
the required **CI Gate** status check on `main` — so the local hook is a
fast first filter, not the last line of defense.

| Tier | Triggered by | What runs |
| --- | --- | --- |
| docs-only | only `docs/`, `*.md`, issue templates changed | nothing — push completes in seconds |
| backend-only | only `backend/` changed, no high-risk paths | `ruff format --check` / `ruff check --force-exclude` on changed `v2/*.py` files; `pytest` on changed test files + `v2/tests/structural` |
| frontend-only | only `frontend/` changed, no high-risk paths | node unit tests, `pnpm typecheck`, `eslint --no-warn-ignored` on changed files |
| broad | high-risk paths (auth, tenancy, billing/Stripe/payments, migrations, `.github/workflows/`, `scripts/`, deploy/infra, lockfiles) or mixed backend+frontend | full backend suite + all frontend static checks (the pre-#477 behavior) |
| `--full` | flag | broad tier plus E2E |

E2E also runs automatically when `frontend/e2e/` files changed. Checks are
fail-fast: the first failure stops the run.

The tier classifier lives in `scripts/dev/lib/classify-changes.sh` and is
covered by `scripts/dev/pre-push-checks.test.sh` (run in CI as the Hook
Classifier Tests job — part of CI Gate).

If pre-push fails locally, fix it before pushing. Do not push just to unblock CI.

## UI Verification

For UI changes:

1. Start the relevant stack.
2. Open the affected route in a browser.
3. Verify the golden path.
4. Verify loading, empty, error, and retry states when touched.
5. Check mobile size for coach and parent workflows.
6. Capture a screenshot when the visual result matters.

## Production-Scale Local Audit

Use this only when the task asks for release-level confidence, production-like
local data, real-user route inventory, or every user-facing route/control.

```bash
scripts/dev/saas_staging.sh blno-seed
scripts/dev/saas_staging.sh scale --apply --parents 250 --students-per-parent 2
scripts/dev/saas_staging.sh local-auth-env > /tmp/academy-local-auth-env.sh
set -a; . /tmp/academy-local-auth-env.sh; set +a
LOCAL_AUTH_E2E=1 scripts/dev/saas_staging.sh audit-readiness
cd frontend
LOCAL_AUTH_E2E=1 pnpm exec playwright test -c playwright.local-auth.config.ts
cd ..
LOCAL_AUTH_E2E=1 scripts/dev/saas_staging.sh audit-gate
LOCAL_AUTH_E2E=1 scripts/dev/saas_staging.sh audit-artifacts
```

Expected clean pass:

- `audit-readiness` reports `READY`.
- `audit-gate` reports `CLEAN_PASS`.
- Playwright has zero failed and zero skipped tests.
- Audit artifacts are written under `/tmp/academy-manager-local/evidence/`.

Safety:

- This audit uses local sanitized BLNO data and Firebase emulator accounts.
- Do not use production data or production services.
- `scale --apply` mutates local staging data.
- Cleanup/reset/nuke delete local Mongo/emulator state and require explicit
  operator intent.
- Do not paste local test passwords or tokens into final responses, PRs, or docs.

## Final Verification Report

Every handoff or final response after implementation should include:

1. Commands run.
2. Results.
3. Manual checks completed.
4. Checks not run.
5. Why skipped checks were skipped.

Do not fake verification.
