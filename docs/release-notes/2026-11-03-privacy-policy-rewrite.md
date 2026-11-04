# privacy-policy-rewrite

PR: #1115

## What changed
The `/privacy` page is rewritten to match the App Store privacy label and Google Play data-safety answers (slice M5, part D5; source: `docs/plans/2026-11-03-store-listing.md` section 3).

- Lists every data type the app collects, including children's details entered by a parent or the academy (name, date of birth, optional medical notes), stored card brand and last 4, messages, waiver signatures with IP and browser, push token, and Sentry crash reports.
- States what is not done: no ads, no selling data, no cross-app tracking, no location, contacts or camera; children do not sign in.
- Names the processors: Google Firebase, Stripe, Resend, Sentry, Fly.io, Cloudflare, MongoDB Atlas.
- Retention: account data while the account is open; invoices, payments and audit logs 7 years; waivers kept as the academy's record; exports 7 days.
- Deletion: in-app under Profile or via `/account-deletion`, the 14-day window, and what is kept.
- Responsibility: the academy for the records it keeps, Marvy Labs for the sign-in account.
- The draft banner stays, reworded to "Draft pending legal review". The nav links to the new deletion page.

## Deploy notes
Frontend only. No env vars or migrations. Before store submission the owner must get counsel to confirm the controller/processor wording and then remove the draft banner.

## Risk / rollback
Low; static page. If the app's data collection changes, this page and both store forms must change together. Roll back by reverting the PR.
