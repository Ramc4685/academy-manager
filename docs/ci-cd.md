# CI/CD Deployment Runbook

Production deployment is handled by GitHub Actions.

## Workflows

- `.github/workflows/ci.yml` runs on pull requests and pushes to `main`.
- `.github/workflows/deploy.yml` runs on pushes to `main` and manual dispatches from `main`.
- Deployments validate the app first, wait for the protected `production` GitHub Environment gate, deploy the Fly backend, deploy the Cloudflare Pages frontend, then run production smoke checks.

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

Use a protected GitHub Environment named `production` with required reviewers before launch. That keeps automatic deploys from `main` under an explicit approval gate.

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

The script checks backend health, CORS for `https://academy.courtmastr.com`, and frontend reachability.
