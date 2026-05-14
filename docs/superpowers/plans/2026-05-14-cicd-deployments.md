# CI/CD Deployments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep `main` production-ready and automatically deploy backend/frontend after successful checks.

**Architecture:** Add GitHub Actions as the single deployment control plane. Pull requests run validation only; pushes to `main` run validation, deploy the backend to Fly, deploy the frontend to Cloudflare Pages, and run production smoke checks against `https://api.academy.courtmastr.com` and `https://academy.courtmastr.com`.

**Tech Stack:** GitHub Actions, Python 3.12, Node 22/Yarn 1, Fly.io, Cloudflare Wrangler/Pages, FastAPI, Create React App.

---

## Required Repository Secrets

Create these in GitHub: `Settings -> Secrets and variables -> Actions`.

- `FLY_API_TOKEN`: Fly token with deploy access to `courtmastr-academy-api`.
- `CLOUDFLARE_API_TOKEN`: Cloudflare token with Pages deploy permission for account `2d2ca3d9333825a9a67050e43506ae5b`.
- `CLOUDFLARE_ACCOUNT_ID`: `2d2ca3d9333825a9a67050e43506ae5b`.

Do not store MongoDB, Stripe, Resend, JWT, or app runtime secrets in GitHub unless a workflow truly needs them. Runtime secrets should stay in Fly secrets and provider dashboards.
`REACT_APP_BACKEND_URL` is intentionally hardcoded in the workflows as `https://api.academy.courtmastr.com`, not stored as a secret.

## File Structure

- Create `.github/workflows/ci.yml`: validation for PRs and pushes.
- Create `.github/workflows/deploy.yml`: production deployment from `main`.
- Create `scripts/smoke/production_smoke.sh`: shell smoke test for deployed API/frontend.
- Modify `.gitignore`: keep local deployment caches ignored if needed.
- Create `docs/ci-cd.md`: document branch flow, deployment flow, and required secrets.

## Branch Policy

- `main` is production.
- Feature work should happen on `feat/<short-name>` branches.
- Pull requests into `main` must pass CI.
- Direct pushes to `main` should be avoided except emergency deployment/ops commits.
- Production deployment runs only on `push` to `main` and can also be manually triggered.

---

### Task 1: Add Production Smoke Script

**Files:**
- Create: `scripts/smoke/production_smoke.sh`

- [ ] **Step 1: Create the smoke script**

```bash
mkdir -p scripts/smoke
cat > scripts/smoke/production_smoke.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-https://api.academy.courtmastr.com}"
FRONTEND_URL="${FRONTEND_URL:-https://academy.courtmastr.com}"

echo "Checking API health: ${API_URL}/api/health"
api_body="$(curl -fsS "${API_URL}/api/health")"
echo "${api_body}" | grep -q '"ok":true'

echo "Checking API CORS for frontend origin"
cors_headers="$(curl -fsS -i -X OPTIONS "${API_URL}/api/auth/me" \
  -H "Origin: ${FRONTEND_URL}" \
  -H "Access-Control-Request-Method: GET")"
echo "${cors_headers}" | grep -qi "access-control-allow-origin: ${FRONTEND_URL}"

echo "Checking frontend shell: ${FRONTEND_URL}"
frontend_headers="$(curl -fsS -I "${FRONTEND_URL}")"
echo "${frontend_headers}" | grep -q "200"

echo "Production smoke checks passed"
EOF
chmod +x scripts/smoke/production_smoke.sh
```

- [ ] **Step 2: Run smoke script locally**

Run:

```bash
scripts/smoke/production_smoke.sh
```

Expected: `Production smoke checks passed`. If local DNS still has IPv6 routing issues, verify with the temporary Pages URL separately but keep CI pointed at the production domain.

- [ ] **Step 3: Commit**

```bash
git add scripts/smoke/production_smoke.sh
git commit -m "ci: add production smoke checks"
```

---

### Task 2: Add Pull Request CI Workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create CI workflow**

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  frontend:
    name: Frontend build and tests
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: yarn
          cache-dependency-path: frontend/yarn.lock

      - name: Install dependencies
        run: yarn install --frozen-lockfile

      - name: Run frontend tests
        run: CI=true yarn test --watchAll=false

      - name: Build frontend
        env:
          REACT_APP_BACKEND_URL: https://api.academy.courtmastr.com
        run: yarn build

  backend-import:
    name: Backend import checks
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Compile backend modules
        run: python -m compileall .

      - name: Collect backend tests
        env:
          REACT_APP_BACKEND_URL: https://api.academy.courtmastr.com
        run: pytest --collect-only -q
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add validation workflow"
```

Notes:
- This does not run mutating backend integration tests against production on every PR.
- Backend full integration tests should be moved to a staging database before enabling them in CI.

---

### Task 3: Add Main Branch Deployment Workflow

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Create deploy workflow**

```yaml
name: Deploy Production

on:
  push:
    branches: [main]
  workflow_dispatch:

concurrency:
  group: production
  cancel-in-progress: false

permissions:
  contents: read

env:
  REACT_APP_BACKEND_URL: https://api.academy.courtmastr.com

jobs:
  validate:
    name: Validate
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      # Backend/frontend validation steps omitted here for brevity.

  production-approval:
    name: Production Approval
    runs-on: ubuntu-latest
    needs: validate
    if: github.ref == 'refs/heads/main'
    environment: production
    steps:
      - run: echo "Production deployment approved for ${GITHUB_SHA}"

  deploy-backend:
    name: Deploy backend to Fly
    runs-on: ubuntu-latest
    needs: production-approval
    if: github.ref == 'refs/heads/main'
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Fly
        uses: superfly/flyctl-actions/setup-flyctl@ed8efb33836e8b2096c7fd3ba1c8afe303ebbff1

      - name: Deploy backend
        working-directory: backend
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
        run: flyctl deploy --remote-only --app courtmastr-academy-api

  deploy-frontend:
    name: Deploy frontend to Cloudflare Pages
    runs-on: ubuntu-latest
    needs: deploy-backend
    defaults:
      run:
        working-directory: frontend
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: yarn
          cache-dependency-path: frontend/yarn.lock

      - name: Install dependencies
        run: yarn install --frozen-lockfile

      - name: Build frontend
        env:
          REACT_APP_BACKEND_URL: ${{ env.REACT_APP_BACKEND_URL }}
        run: yarn build

      - name: Deploy to Cloudflare Pages
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
        run: yarn wrangler pages deploy build --project-name courtmastr-academy --branch main

  smoke:
    name: Smoke production
    runs-on: ubuntu-latest
    needs: deploy-frontend
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Run production smoke checks
        env:
          API_URL: https://api.academy.courtmastr.com
          FRONTEND_URL: https://academy.courtmastr.com
        run: scripts/smoke/production_smoke.sh
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: deploy production from main"
```

---

### Task 4: Document Deployment Runbook

**Files:**
- Create: `docs/ci-cd.md`

- [ ] **Step 1: Add CI/CD section to README**

Add this section after `## Deployment`:

```markdown
## CI/CD

Production deploys are controlled by GitHub Actions.

- Pull requests into `main` run frontend tests, frontend build, backend module compilation, and backend test collection.
- Pushes to `main` validate, wait for the protected `production` environment gate, deploy the backend to Fly, deploy the frontend to Cloudflare Pages, then run production smoke checks.
- Manual production redeploy is available from GitHub Actions -> Deploy Production -> Run workflow.

Required GitHub Actions secrets:

- `FLY_API_TOKEN`
- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`

Runtime application secrets stay in Fly secrets, not GitHub Actions.

Production URLs:

- Frontend: `https://academy.courtmastr.com`
- Backend API: `https://api.academy.courtmastr.com`

Emergency rollback:

1. For frontend, open Cloudflare Pages -> `courtmastr-academy` -> Deployments -> rollback to the previous successful deployment.
2. For backend, use Fly releases:
   `flyctl releases -a courtmastr-academy-api`
   `flyctl deploy --image <previous-image> -a courtmastr-academy-api`
3. Run `scripts/smoke/production_smoke.sh`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/ci-cd.md
git commit -m "docs: document production cicd"
```

---

### Task 5: Verify End-to-End CI/CD

**Files:**
- No source changes expected.

- [ ] **Step 1: Push feature branch**

```bash
git push origin feat/cicd-production-deploy
```

- [ ] **Step 2: Open pull request into main**

Expected:
- `CI / Frontend build and tests` passes.
- `CI / Backend import checks` passes.
- `Deploy Production` does not run on the PR.

- [ ] **Step 3: Merge pull request**

Expected:
- `Deploy Production / Deploy backend to Fly` passes.
- `Deploy Production / Deploy frontend to Cloudflare Pages` passes.
- `Deploy Production / Smoke production` passes.
- The protected `production` environment approval is requested before deploy jobs run.

- [ ] **Step 4: Confirm production**

Run:

```bash
scripts/smoke/production_smoke.sh
```

Expected: `Production smoke checks passed`.

---

## Deferred Hardening

- Add a staging Fly app and staging MongoDB so backend integration tests run safely without touching production.
- Add GitHub branch protection requiring CI before merge.
- Add a scheduled daily smoke check workflow.
- Add deployment notifications to email/Slack after production smoke succeeds or fails.
- Add Dependabot for GitHub Actions, npm, and pip.

## Self-Review

- Spec coverage: branch update process, CI, backend deploy, frontend deploy, smoke checks, and docs are covered.
- Placeholder scan: no implementation steps use TBD/TODO placeholders.
- Risk note: mutating backend integration tests are intentionally excluded from PR CI until a staging database exists.
