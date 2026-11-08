# delete-curriculum-level

PR: #1161

## What changed
- Admins can delete a curriculum level from the program editor (Settings → Curriculum). "Delete level" shows only on the program's last level, and only while nothing uses it (removing a middle level would leave a gap that level-up cannot cross, so an appended ladder is undone from the top down), opens a confirm dialog, and removes the level with its skills and their criteria. `DELETE /api/v2/admin/levels/{level_id}` refuses with 409 `Curriculum.LevelInUse` (listing what uses it) when any student placement, skill progress, test attempt, certificate, level-up recommendation, coach skill note, lesson card, video ref or external ref points at the level or its skills. `GET /api/v2/admin/programs/{program_id}/level-usage` tells the editor which levels are deletable. Each delete writes a `curriculum.level_deleted` row to `audit_logs`.
- The AI "Draft a skill ladder" card now says plainly that saving adds the drafted levels after the program's last level and never replaces existing ones, and points to Delete level to undo a mistaken save (the 2026-11-08 BLNO levels 7–10 case, which had to be cleaned up by hand in prod).

## Deploy notes
None. No migration, no env var. Backend and frontend should ship together (the editor calls the new usage route).

## Risk / rollback
The delete is permanent; the guard is the safety net, so a reference type it does not check could be orphaned. The check and the delete are not one transaction, so progress recorded in the same instant as a delete could be orphaned (an admin-only, rare race). Roll back by reverting the PR; deleted levels are only recoverable from a database backup.
