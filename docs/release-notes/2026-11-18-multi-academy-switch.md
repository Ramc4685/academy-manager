# multi-academy-switch

PR: #1212

## What changed
Production switches from single-academy to multi-academy mode, so a second academy can exist beside BLNO. The request host now picks the academy: `<slug>.courtmastr.com`, or a verified domain row. BLNO keeps `blno-academy.courtmastr.com` (its slug) and `academy.courtmastr.com` (a verified row), so BLNO families see no change. Platform routes turn on so a platform admin can create the demo academy at `/platform/tenants`.

Inside the iPhone and Android app, the login page shows "Explore the demo academy", which opens `demo-academy.courtmastr.com/login` in the app. App Store and Play reviewers sign in there with demo accounts. The link is hidden on the web and on the demo academy itself.

## Deploy notes
- Needs #1211 deployed first: the Fly secret `V2_PROXY_SHARED_SECRET` and the Worker secret `BFF_PROXY_SHARED_SECRET` must match. Without the Fly secret the API refuses to boot; with a mismatch every request is refused.
- Production read-only checks before this PR: `multi_academy_preflight` prints READY; `tenant_host_preflight` passes Gates 0 and 3 for `blno-academy.courtmastr.com`.
- Within 15 minutes of the deploy: `/api/v2/healthz` returns 200, and an owner, a coach and a parent can sign in on `blno-academy.courtmastr.com` and `academy.courtmastr.com` and see BLNO's data.
- The iOS and Android shells allow `demo-academy.courtmastr.com` only after a new store build (`mobile/capacitor.config.ts`, `Info.plist` App-Bound Domains). Older builds open that link in the system browser.

## Risk / rollback
- Risk: access now comes only from `academy_memberships`. The preflight found every active user has one; anyone added outside the app since then could be refused sign-in.
- Risk: a request whose host matches no academy is refused rather than falling back to BLNO.
- Rollback: revert this PR and deploy. Single-academy mode ignores memberships, platform routes and the demo academy's rows.
