# Batch 3: Level-Up Approve Race

## What changed
- Fixes #592 — the level-up double-approve 500. `review_level_up.py` now catches the `DuplicateKeyError` raised when a genuine concurrent insert collides on the partial unique index `level_progress_active_unique`, and maps it to the same `RecommendationAlreadyReviewed` -> 409 response the CAS loser already produces, instead of letting it escape as an unhandled 500.
- Added a test that drives a true concurrent double-approve, where both readers observe the same pre-race snapshot (the existing race test only covered the interleaving where the loser observes post-winner state).
- Added a test that pins the pre-read replay guard independently of the CAS path, by defeating `update_status` so only the guard can catch the replay.
- Updated the in-memory `_LevelProgressRepo` test fake to raise `DuplicateKeyError` on a colliding active-row insert, mirroring real Mongo unique-index semantics.

## Deploy notes
No migrations. No manual steps. The unique index (`level_progress_active_unique`) already exists in prod; this change only adds server-side error handling around it.

## Risk / rollback
Low risk — the change narrows an unhandled-500 code path to a 409 that the client already handles for the existing CAS-loser case. No schema or index changes. Rollback: revert this PR.

PR: #790
