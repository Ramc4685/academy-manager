# account-deletion-review-gaps

PR: #1121

## What changed
- The admin account-deletions list now accepts the `running` status, so the Families page no longer gets a 500 while an erasure is under way.
- A support cancel now restores legacy memberships that had no status (recorded as active).
- Parent and student login invites are refused when the Firebase login they resolve to has a pending self-deletion, even if no Mongo record links that login to the email.
- The support-restore runbook says to retry a failed cancel until it succeeds.

## Deploy notes
No migration, no new secrets, no config changes.

## Risk / rollback
Low. Revert the PR to roll back. The only behaviour change for academies is that a few more login invites are refused while a person's deletion is pending, and they show the existing generic invite-failed message.
