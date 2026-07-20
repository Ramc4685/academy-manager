# Login-invite Firebase account self-healing

PR: #304

## What changed
- `generate_password_reset_link` threw a raw, unhandled `EmailNotFoundError` whenever a directory record (legacy/pre-migration parent, or one whose Firebase account was never provisioned) had no matching Firebase Auth user — surfacing as a bare 500 instead of a clean error.
- The adapter now self-heals: on `EmailNotFoundError` it provisions a passwordless Firebase account (same as the existing admin-creation path — no password is ever set or emailed) and retries once.
- Any other unexpected failure in `SendLoginInvite` is now wrapped as `LoginInviteSendFailed` (502) instead of propagating raw.

## Deploy notes
No migration, environment variable, or manual deployment step is required.

## Risk / rollback
The risk is creating a Firebase identity for the wrong directory record when
repairing an orphaned account. Revert PR #304 to disable self-healing; parents
whose Mongo directory record lacks a Firebase account will again be unable to
receive a login invite until repaired manually.
