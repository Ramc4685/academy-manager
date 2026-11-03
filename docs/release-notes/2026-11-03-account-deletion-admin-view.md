# account-deletion-admin-view

PR: #TBD

## What changed
Admins can now see which families deleted their own account, and there is a public page explaining how deletion works (slice M5, part D4).

- New `GET /api/v2/admin/account-deletions` lists this academy's self-service deletion requests, newest first: who, when it was asked, when personal details are (or were) removed, and how many removal attempts have failed. It never returns the person's email.
- The family page shows a banner when that parent deleted their account: the date, when details are removed, that support can still restore it until then, and that any balance stays on the family to collect offline. A retrying removal says so.
- The families list shows a "Deleted accounts" card linking to each one. The card is hidden when there are none.
- New public page `/account-deletion` explains in-app deletion (Profile → Delete account), what is deleted and kept, the 14-day window, and a support email for people who cannot sign in. Google Play's data-deletion form points here.

## Deploy notes
Needs D1 (migration `0216_account_deletion_requests`) and D3 deployed first. No new env vars, secrets or migrations. After deploy, enter `https://<host>/account-deletion` in the Google Play Console data-safety form.

## Risk / rollback
Low. Read-only admin view and a static public page. Roll back by reverting the PR.
