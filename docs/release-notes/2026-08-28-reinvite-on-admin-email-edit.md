# reinvite-on-admin-email-edit

PR: #484

## What changed
Editing a user's email address in the admin directory now automatically sends
that user a fresh "set your password" invite, and the admin sees whether it was
sent. Previously the Firebase email change silently cleared the account's
verified state, locking the user out of password login with nobody told.
Re-submitting an unchanged email no longer touches Firebase at all.

## Deploy notes
None. No migrations, no new env vars. The invite reuses the existing
`send_login_invite` path (Firebase password-reset link + Resend), so academies
already sending invites need no further setup.

## Risk / rollback
If wrong, an admin email edit either sends an unwanted invite email or (worse)
still fails to send one — the response's `login_invite.status` and the
`re-invite after email change failed` log line show which. The edit itself
never depends on the invite, so a failure cannot block or corrupt the user
record. Roll back by reverting the PR; behavior returns to the previous silent
lockout.
