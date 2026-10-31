# owner-skill-pathway-dashboard

PR: #1102

## What changed
The admin sidebar's Progress item now opens a skill-pathway dashboard (`/admin/pathway/dashboard`, API `GET /api/v2/admin/pathway/dashboard`): skills mastered this week, level-ups this month, players per level, students one skill from levelling up, students with no new skill in 6+ weeks (with skills done and last win), and skills ticked per coach this week. It also shows the level-up rule (Automatic vs I approve first), which reads and writes each level's existing `requires_admin_approval` setting.

## Deploy notes
No migration, no env vars. The Progress sidebar item is now always visible (it was hidden unless `NEXT_PUBLIC_SKILL_PROGRESS_OVERVIEW=1`); the per-student table stays behind that flag and is linked from the dashboard when it is on.

## Risk / rollback
Read-only except the rule toggle, which issues the same per-level update the curriculum editor already does; if one level's save fails, levels can end up mixed and the card says so. Revert this PR to roll back.
