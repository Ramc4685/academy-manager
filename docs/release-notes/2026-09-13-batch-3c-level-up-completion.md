# batch-3c: level-up completion

PR: #0

## What changed

- Fixes #786 — level-up approval now writes a terminal `COMPLETED` status instead of `APPROVED`, so an approved recommendation no longer permanently blocks the next level-up for the same student/program. `ACTIVE_LEVEL_UP_STATUSES` drops `APPROVED`, so any pre-existing rows stuck in that status also stop blocking new recommendations.

## Deploy notes

Includes migration `backend/v2/migrations/0179_level_up_active_index_drops_approved.py`, which narrows the `recs_active_unique` partial index on `level_up_recommendations` to match the new active-status set (drops `APPROVED`). It only narrows the filter (covers fewer documents than before), so it cannot collide with any existing unique row. Confirm `V2_RUN_MIGRATIONS_ON_BOOT` covers it, or run the migration manually per AGENTS.md. No manual env var changes.

## Risk / rollback

Low risk: the change only affects which status is written on approval and which statuses count as "active" for the uniqueness index; no data is deleted. If this regresses, revert the PR — migration 0179 has no `down()` (consistent with the rest of this migration set, which is append-only), so a rollback would also need a follow-up migration restoring the old partial-filter expression if the narrower index proves incorrect in production.
