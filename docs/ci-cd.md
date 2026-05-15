# CI/CD Deployment Runbook

Production deployment is handled by GitHub Actions.

## Workflows

- `.github/workflows/ci.yml` runs on pull requests and pushes to `main`.
- `.github/workflows/deploy.yml` runs on pushes to `main` and manual dispatches from `main`.
- Deployments validate the app first, wait for the protected `production` GitHub Environment gate, deploy the Fly backend, deploy the Cloudflare Pages frontend, then run production smoke checks.
- Tags do not deploy production. A merge to `main` is the release event; the approval gate is the final production control.

## Production Targets

- Frontend: `https://academy.courtmastr.com`
- Frontend fallback: `https://courtmastr-academy.pages.dev`
- Backend API: `https://api.academy.courtmastr.com`
- Fly app: `courtmastr-academy-api`
- Cloudflare Pages project: `courtmastr-academy`

## Required GitHub Secrets

```bash
FLY_API_TOKEN=<Fly deploy token>
CLOUDFLARE_API_TOKEN=<Cloudflare Pages deploy token>
CLOUDFLARE_ACCOUNT_ID=<Cloudflare account id>
```

The Cloudflare token needs permission to deploy the `courtmastr-academy` Pages project. The Fly token needs permission to deploy `courtmastr-academy-api`.

## Required GitHub Variables

These values are embedded into the frontend at build time by GitHub Actions:

```bash
REACT_APP_FIREBASE_API_KEY=<Firebase web API key>
REACT_APP_FIREBASE_AUTH_DOMAIN=academy-courtmastr.firebaseapp.com
REACT_APP_FIREBASE_PROJECT_ID=academy-courtmastr
REACT_APP_FIREBASE_STORAGE_BUCKET=academy-courtmastr.firebasestorage.app
REACT_APP_FIREBASE_MESSAGING_SENDER_ID=953230788846
REACT_APP_FIREBASE_APP_ID=1:953230788846:web:1f2819c11418ecf5860bff
REACT_APP_FIREBASE_MEASUREMENT_ID=G-Z6GS6WRZY8
```

Use a protected GitHub Environment named `production` with required reviewers before launch. That keeps automatic deploys from `main` under an explicit approval gate.

Protect the `main` branch with required status checks for the `Backend` and `Frontend` CI jobs. Direct pushes to `main` should stay disabled outside emergency operations.

## Manual Deploy

1. Merge the deployment branch into `main`, or open GitHub Actions.
2. Run `Deploy Production` from the `main` branch when redeploying manually.
3. Approve the `production` environment gate.

Do not run production deployment from feature branches. The workflow skips all deploy jobs unless `github.ref` is `refs/heads/main`.

Frontend installs are locked with `frontend/yarn.lock`; CI and deploy use `yarn install --frozen-lockfile`.

## Smoke Test

Run the same production smoke check locally:

```bash
scripts/smoke/production_smoke.sh
```

The deploy workflow runs `scripts/smoke/verify_frontend_bundle.sh` before publishing the Cloudflare Pages build.
The production smoke script checks backend health, CORS for `https://academy.courtmastr.com`, and frontend reachability.
It also verifies that the deployed frontend bundle contains the production API URL and Firebase project id so missing build-time configuration fails the deploy.
