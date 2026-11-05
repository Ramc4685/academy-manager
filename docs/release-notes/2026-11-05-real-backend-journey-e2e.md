# real-backend-journey-e2e

PR: #1145

## What changed
Test-only. A new Playwright spec, `frontend/e2e/specs/real-backend-journeys.spec.ts`, runs six journeys against the real Next.js frontend, the real FastAPI backend and real MongoDB (Firebase Auth emulator), with nothing faked by `page.route`. The journeys are:
- an admin adds a student on a class roster in the UI, and the parent sees the class;
- the enrollment's monthly invoice shows the parent the right amount due, with a Pay button;
- a recorded payment shows the invoice as paid for the parent and on the admin family billing tab;
- a coach marks a student present in the coach UI, and both the admin's occurrence attendance and the parent's attendance page show it;
- a parent cannot read another family's invoice or class, and gets refused on admin routes;
- withdrawing a student voids an already-drafted later-month invoice and refuses billing for any later month.

Each test creates its own class and uses its own seeded family, so the tests stay independent. Seeding goes through the same `/api/v2` admin routes the UI calls. The payment is the admin's "record payment" route, because CI has no Stripe test keys. The spec is listed in `playwright.ci-real-auth.config.ts` next to the sign-in smoke spec.

## Deploy notes
No app code changed, and there is nothing to deploy. The `Frontend E2E Real Auth` CI job gets a second step that runs the new spec on the stack the smoke step already started. It adds well under a minute. That step is `continue-on-error`, so it reports failures but does not fail CI Gate until the owner agrees to make it required. A cross-academy admin check is not included: the local stack runs with `V2_SAAS_MODE` off, so every request resolves to BLno. That check needs a SaaS-mode stack.

## Risk / rollback
The only risk is a noisy non-blocking CI step. Roll back by reverting the PR.
