# delete-curriculum-level

PR: #1237

## What changed
- Admins can permanently delete a curriculum level from the program editor (Settings → Curriculum). "Delete level" shows only on the program's last active level and only while nothing uses it, opens a confirm dialog, and removes the level with its skills and their criteria. It sits beside the existing Retire level (a soft hide), and exists to undo a mistaken save, such as an AI skill ladder appended by accident, from the top down.
- `DELETE /api/v2/admin/levels/{level_id}` refuses with 409 `Curriculum.LevelInUse` (listing what uses it) when any student placement, skill progress, test attempt, certificate, level-up recommendation, coach skill note, lesson card, video ref, external ref or class recap points at the level or its skills, or when an active level comes after it. `GET /api/v2/admin/programs/{program_id}/level-usage` tells the editor which levels are deletable. Each delete writes a `curriculum.level_deleted` row to `audit_logs`.
- The AI "Draft a skill ladder" card now says that saving adds the drafted levels after the program's last level and never replaces existing ones, and points to Delete level to undo a mistaken save.

## Deploy notes
None. No migration, no env var. Backend and frontend should ship together (the editor calls the new usage route).

## Risk / rollback
The delete is permanent; the usage check is the safety net, so a reference type it does not check could be orphaned. The check and the delete are not one transaction, so progress recorded in the same instant as a delete could be orphaned (admin-only, rare). Roll back by reverting the PR; deleted levels are recoverable only from a database backup.
