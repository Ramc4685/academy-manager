# auth-and-accounts

PR: TBD

## What changed
Sign-in and account fixes. Forgot-password and email-verification mail now come from the academy's own branded sender and open on the academy's own page in any browser; digest login links go only to parents who have never signed in; and magic links sign in the right account, survive a Firebase hiccup, and replace older unused links. Deleting an account now takes the children off upcoming classes, stops autopay and sends a confirmation email at once (personal data is still erased after 14 days), and email lookups use an exact indexed match.

## Deploy notes
Two backfill migrations, both idempotent and safe to re-run: `0228_users_backfill_normalized_email` (stamps `normalized_email` on legacy users rows; skips and logs case-duplicates, which need merging by hand) and `0229_users_backfill_last_login_at` (stamps `last_login_at` from the sign-in audit trail, ignoring magic-link sessions, so the digest does not send login links to parents who already signed in). Run both before or with the deploy. New public route `POST /api/v2/password-reset` (always 204 and sends after responding, per-mailbox throttled, IP rate limited). A sign-up for an address that already has an account now gets the set-password email instead of "verify". The CSP stays Report-Only; it now allows the Google sign-in script and the Firebase auth-helper iframe so it can be enforced later.

## Risk / rollback
Medium: touches sign-in token resolution (server-minted custom tokens now resolve by Firebase uid only) and account deletion side effects (classes dropped and autopay paused through the billing use cases). Roll back by reverting the PR; the migrations only add fields and need no reversal. Known follow-up: Variant B (attacker-linked provider on an unverified account) still open; planned fix is to reject a federated session whose provider email differs from the Firebase account email, and provision Firebase accounts for rostered parents at creation; emulator check owed.
