# account-deletion-screen

PR: #TBD

## What changed
Parents and coaches can now delete their own account from their profile page (slice M5, part D2). This is the in-app path Apple and Google require, and it uses the `POST /api/v2/me/account-deletion` endpoint from part D1.

- A "Delete account" card sits at the bottom of the parent profile and the coach profile. Opening it explains what happens: the person is signed out everywhere, their personal details are removed after 14 days (the academy can restore the account until then), and invoices and payment records are kept for 7 years, with any balance staying with the academy.
- The person confirms by typing DELETE and signing in again. Password accounts enter their password; Google and Apple accounts confirm with that provider. This meets the backend's 5-minute recent sign-in rule.
- On success the app signs out, clears cached data, and opens the login page with "Your account has been deleted and you are signed out."
- Refusals show a plain message: the only owner of an academy and a coach with upcoming classes are told why, and an old sign-in is asked to sign in again.
- Admins and students have no profile page yet, so they have no delete button. The only owner of an academy cannot delete anyway.

## Deploy notes
Frontend only. It needs the D1 backend and migration `0216_account_deletion_requests` deployed first. No new env vars or secrets.

## Risk / rollback
Low. The card is collapsed by default and needs a typed DELETE plus a fresh sign-in, so an accidental tap cannot delete. A mistaken deletion is reversible by hand within 14 days (see the D1 note). Roll back by reverting the PR.
