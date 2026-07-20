# Login-invite self-healing with enumeration protection

PR: #307

## What changed
Login-invite self-healing now checks Firebase account existence before
generating a reset link, so it works when Firebase email-enumeration protection
hides the usual missing-user error. Invite failures are also logged for
operator diagnosis.

## Deploy notes
No migration, environment variable, or manual deployment step is required.

## Risk / rollback
The risk is an incorrect Firebase existence check creating or linking the wrong
identity. Revert PR #307 to restore the exception-based flow; production
projects with email-enumeration protection may then return 502 for parents
whose Firebase account is missing.
