# digest-sign-in-link

PR: TBD

## What changed
The parent daily digest no longer emails a one-time auto-login link to parents who have never signed in. An emailed link that grants a session is a bearer credential, and a digest is forwardable mail (OWASP authentication cheat sheet, NIST 800-63B), so the "set up your account" button now always opens the sign-in page with the parent's email prefilled and `returnTo=/parent/payments` when a balance is owed, or `/parent/dashboard` otherwise. The login page checks `returnTo` with `sanitizeReturnPath` before it navigates. Links already sent stay redeemable until they expire (72h), but redeeming one now also requires an active parent membership in the academy the link was issued for. A staff-only, removed or wrong-academy user gets the same "invalid link" answer as an unknown token, and the link is not used up. The magic-link issue code, consume code, `POST /api/v2/magic-link/consume` route and `/auth/magic` page now exist only for links already in inboxes. A cleanup will delete them once 72h have passed after deploy.

## Deploy notes
- No migration and no settings change.
- From 72h after deploy, no live magic link remains. Delete the magic-link stack in a follow-up then.

## Risk / rollback
- Risk: a never-activated parent now has to set a password ("Forgot password?" on the prefilled sign-in page) instead of landing in the portal with one click. That is the intended trade.
- Risk: in non-SaaS mode the membership check uses the legacy adapter, which builds the membership from `users.roles`. A parent whose user row lacks the `parent` role can no longer redeem an old link and has to sign in instead.
- Rollback: revert the PR. Nothing is stored differently.
