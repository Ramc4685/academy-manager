# fix-identity-self-heal-login-invites-when-firebase-account-i

PR: #304

## What changed
- `generate_password_reset_link` threw a raw, unhandled `EmailNotFoundError` whenever a directory record (legacy/pre-migration parent, or one whose Firebase account was never provisioned) had no matching Firebase Auth user — surfacing as a bare 500 instead of a clean error.
- The adapter now self-heals: on `EmailNotFoundError` it provisions a passwordless Firebase account (same as the existing admin-creation path — no password is ever set or emailed) and retries once.
- Any other unexpected failure in `SendLoginInvite` is now wrapped as `LoginInviteSendFailed` (502) instead of propagating raw.

## Deploy notes
No migration detected in the diff. Confirm no manual env var or manual step is needed before merge.

## Risk / rollback
_Auto-generated stub — author: fill in what breaks if this is wrong and how
to roll back before merge._ Revert the merge commit if this regresses.
