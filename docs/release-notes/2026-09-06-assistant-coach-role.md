# assistant-coach-role

PR: #663

## What changed
New academy role **Assistant coach**: a per-session helper who signs into the
coach app, sees only the sessions they are assigned to, and can mark
attendance, update skills and add notes there. They cannot author lesson
plans, edit rosters, touch billing, message families, or post announcements,
and payroll never pays them (it still pays the actual or scheduled coach
only).

- Sessions carry an assistants list, edited from the admin session detail
  page ("Coaching staff" → Assistants). Future occurrences pick up changes.
- Admins (not only owners) can grant "Assistant coach" from a user's page,
  the roles panel, or when creating a user.
- Coach app for assistants: banner explaining the scope, no Messages,
  no announcements or billing on session detail, no pay card on profile.

## Deploy notes
None. No migration (session and occurrence validators accept the new field;
existing documents read as "no assistants"). No env vars.

To onboard a helper: create or open their user → grant "Assistant coach" →
open the session → Coaching staff → Edit assistants → tick them. They land on
Today with only that session.

## Risk / rollback
Low. Existing coaches, admins and owners are unaffected; the new guard only
narrows a role that no user holds until granted. Revert the PR to remove the
role; any `assistant_coach_ids` left on sessions are ignored by the old code.
