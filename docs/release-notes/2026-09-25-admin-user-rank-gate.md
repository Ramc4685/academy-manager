# admin-user-rank-gate

PR: #970

## What changed
A plain admin can no longer change an owner's or another admin's account. That covers email, status, name, roles and set-password invites. The change closes the X3 takeover, where an admin could change an owner's email and have a set-password link sent to the new address. Only the owner can change owner and admin accounts. Refused attempts and set-password sends are now written to the audit log.

## Deploy notes
None. No migration, and no environment variables or manual steps.

## Risk / rollback
Plain admins lose the ability to edit peer admins, including name and phone. Their own Staff page also shows read-only, although the backend still accepts self-edits. If this blocks a real workflow, revert this PR; that restores the old, exploitable behaviour. Run the read-only audit query in the PR body to look for past owner email changes made by non-owners.
