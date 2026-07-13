# fix-auth-redirect-to-sign-in-when-registering-with-an-existi

PR: #291

## What changed
- The register form (`/register`) already had a friendly message for Firebase's `auth/email-already-in-use` error, but only displayed it as static text — leaving the parent stuck on the register form with no way forward.
- Now redirects to `/login?email=<their email>` instead, and the login page prefills the email field and shows "An account already exists for this email. Sign in to continue."

## Deploy notes
No migration detected in the diff. Confirm no manual env var or manual step is needed before merge.

## Risk / rollback
_Auto-generated stub — author: fill in what breaks if this is wrong and how
to roll back before merge._ Revert the merge commit if this regresses.
