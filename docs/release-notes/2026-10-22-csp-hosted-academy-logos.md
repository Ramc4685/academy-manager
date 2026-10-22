# csp-hosted-academy-logos

PR: pending

## What changed
The CSP `img-src` now also allows the project's Firebase Hosting site (`https://<project>.web.app`, so `https://academy-courtmastr.web.app` in production). On the Spark plan the project has no Storage bucket, so `POST /admin/academy/media` answers 503 and academy logos are hosted on Firebase Hosting instead, then saved with "Or paste a logo link". The first one is BLNo's: `https://academy-courtmastr.web.app/academies/blno/logo.png`. The policy is still report-only, so these logos already render; this keeps them rendering when it is flipped to enforcing, and stops them showing up as CSP reports meanwhile. A unit test pins both logo origins in `img-src`.

## Deploy notes
None for the app. Logos on Hosting are deployed outside this repo with `firebase deploy --only hosting` from a folder whose `public/academies/<slug>/logo.png` holds the files; a Hosting deploy replaces the whole site, so keep every academy's logo in that folder. The Firebase auth helper paths (`/__/auth/*` on `firebaseapp.com`) are reserved and unaffected (checked 200 after the first deploy).

## Risk / rollback
The new origin only serves files the project owner deploys. Roll back by reverting the PR; logos on Hosting would then only render while the CSP stays report-only.
