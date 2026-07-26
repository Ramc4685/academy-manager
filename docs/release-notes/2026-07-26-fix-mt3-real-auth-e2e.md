# fix-mt3-real-auth-e2e

PR: #TBD

## What changed

Added a new CI job, `frontend-e2e-real-auth`, that boots the local stack
(MongoDB, Firebase Auth emulator, backend, frontend) inside the runner via
`scripts/local_test_stack.sh fresh`, seeds demo data, and runs a new minimal
Playwright spec (`frontend/e2e/specs/real-auth-smoke.spec.ts`) that signs in
through the real login form as a seeded admin and parent, asserts the backend
`GET /api/v2/me` call returns the correct persona, and asserts the client-side
redirect lands on the right persona home (`/admin`, `/parent/payments`), plus
a negative case confirming an unauthenticated `/admin` visit redirects to
`/login`. Every other Playwright job in CI uses the auth bypass, so this is
the only job exercising the real Firebase sign-in → `/me` → persona-redirect
path automatically. The job is wired into `production-approval`'s gate, so it
blocks deploys like the other e2e jobs.

## Deploy notes

No migrations, no new env vars or secrets for production. The new CI job only
uses the Firebase Auth **emulator** and reuses the existing non-secret
`vars.REACT_APP_FIREBASE_*` GitHub Actions variables (already used by
`frontend-static`/`frontend-e2e-*` builds) plus fixed CI-only emulator
passwords (`e2e-ci-*-pass`, not valid against any real account). Note: this
job does not exercise prod Firebase's enumeration-protection behavior (see PR
#304) — the Auth Emulator doesn't reproduce that quirk.

## Risk / rollback

If the job proves flaky in practice, remove `frontend-e2e-real-auth` from
`.github/workflows/production.yml` (both the job definition and from
`production-approval`'s `needs`/`if`) — nothing else depends on it. Local
verification (isolated ports, fresh Mongo/emulator) ran all 3 spec assertions
green in ~48s before this PR was opened.
