# CI/CD Deployment Runbook

Production deployment is handled by one GitHub Actions workflow:
`.github/workflows/production.yml`.

## Workflow

- Pull requests to `main` run validation only.
- Pushes to `main` and manual dispatches run validation, wait for the protected
  `production` GitHub Environment gate, then deploy.
- Tags do not deploy production. A merge to `main` is the release event.

## Validation Jobs

- **Backend** installs legacy + v2 Python dependencies, compiles backend code,
  runs the broad non-live legacy pytest suite, runs v2 import-linter
  boundaries, and runs `backend/v2/tests` with shared coverage.
- **Frontend** installs `frontend-next/` with pnpm, then runs typecheck, lint,
  build, OpenAPI drift check, size budget reporting, Lighthouse when configured,
  and Playwright E2E.
- **Edge** runs the Cloudflare router table tests.

The legacy CRA app under `frontend/` is deprecated and is not built, tested, or
deployed by the production workflow.

## Production Targets

- Frontend: `https://academy.courtmastr.com`
- Backend API: `https://api.academy.courtmastr.com`
- Fly app: `courtmastr-academy-api`
- Next/Cloudflare frontend project: `academy-next`
- Edge worker: `academy-edge-router`

## Required GitHub Secrets

```bash
FLY_API_TOKEN=<Fly deploy token>
CLOUDFLARE_API_TOKEN=<Cloudflare Workers deploy token>
CLOUDFLARE_ACCOUNT_ID=<Cloudflare account id>
```

The Cloudflare token needs permission to deploy the Next frontend worker and
the `academy-edge-router` worker. The Fly token needs permission to deploy
`courtmastr-academy-api`.

## Required GitHub Variables

The workflow maps these existing `REACT_APP_*` variables into the
`NEXT_PUBLIC_*` names used by `frontend-next/`:

```bash
REACT_APP_FIREBASE_API_KEY=<Firebase web API key>
REACT_APP_FIREBASE_AUTH_DOMAIN=academy-courtmastr.firebaseapp.com
REACT_APP_FIREBASE_PROJECT_ID=academy-courtmastr
REACT_APP_FIREBASE_STORAGE_BUCKET=academy-courtmastr.firebasestorage.app
REACT_APP_FIREBASE_MESSAGING_SENDER_ID=953230788846
REACT_APP_FIREBASE_APP_ID=1:953230788846:web:1f2819c11418ecf5860bff
REACT_APP_FIREBASE_MEASUREMENT_ID=G-Z6GS6WRZY8
```

Use a protected GitHub Environment named `production` with required reviewers
before launch. Protect the `main` branch with required status checks for the
`Backend`, `Frontend`, and `Edge` jobs from the `Production` workflow.

## Manual Deploy

1. Merge the deployment branch into `main`, or open GitHub Actions.
2. Run `Production` from the `main` branch when redeploying manually.
3. Approve the `production` environment gate.

Do not run production deployment from feature branches. Deploy jobs skip unless
`github.ref` is `refs/heads/main`.

## Smoke Test

Run the same production smoke check locally:

```bash
scripts/smoke/production_smoke.sh
```

The smoke script checks backend health, v2 health, CORS for
`https://academy.courtmastr.com`, frontend reachability, the same-origin BFF
proxy, Firebase build config in Next chunks, and Stripe webhook signature
rejection.
