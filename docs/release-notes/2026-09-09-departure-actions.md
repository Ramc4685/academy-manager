# departure-actions

PR: #700

## What changed

The admin enrollment actions move to one shared component used by both the class roster and the student profile, so a departure can be handled from the person rather than the class. Labels adopt the industry vocabulary: Transfer, Hold, Return, Drop, Delete. Delete leaves the button row for an overflow menu and is shown only to an owner. Every dialog states what happens to the seat, autopay, invoices already issued and the family balance.

## Deploy notes

No migration, no env, no route changes. Frontend only.

## Risk / rollback

Purely presentational plus gating; revert to roll back. The Delete owner gate here is frontend-only — the backend route restriction ships with #697.
