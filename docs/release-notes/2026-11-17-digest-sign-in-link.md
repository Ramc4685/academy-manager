# digest-sign-in-link

PR: #1202

## What changed
The parent daily digest no longer emails a one-time auto-login link to parents who have never signed in. An emailed link that grants a session is a bearer credential, and a digest is forwardable mail (OWASP authentication cheat sheet, NIST 800-63B). The "set up your account" button now always opens the sign-in page with the parent's email prefilled and a `returnTo` of `/parent/payments` when a balance is owed, or `/parent/dashboard` otherwise. The login page checks `returnTo` with `sanitizeReturnPath`. After a fresh sign-in on that page, the parent lands on `returnTo` only once #1201's login handler change is on main (it is merged in before this ships). A parent who instead sets a password through the "Forgot password?" email still ends on the dashboard, not the payments page.

The magic-link issue path is deleted, so nothing in the codebase can mint a link any more. Links already sent stay redeemable until they expire (72h), and redeeming one now needs a membership in the link's academy that is active and holds only the parent role. A parent who is also a coach, admin or owner, a removed member, a staff-only user or a user from another academy gets the same "invalid link" answer as an unknown token, keeps the link unused, and signs in normally. Consume, the `POST /api/v2/magic-link/consume` route and the `/auth/magic` page remain only for links already sent.

## Deploy notes
- No migration and no settings change.
- From 72h after deploy, no live magic link remains. A follow-up then deletes consume, the route, the `/auth/magic` page, and the `custom`-provider email-verification exemption in `token_claims.py` and `load_auth_claims.py`.

## Risk / rollback
- Risk: a never-activated parent now sets a password ("Forgot password?" on the prefilled sign-in page) instead of landing in the portal with one click. That is the intended trade.
- Risk: a parent who also holds a staff role, or (in non-SaaS mode, where the membership comes from `users.roles`) whose user row lacks the parent role, can no longer redeem an old link and has to sign in instead.
- Rollback: revert the PR. Nothing is stored differently.
