# Batch 4: Level-Up Recommendation CAS

## What changed
- Fixes #548 — a review could approve a level-up recommendation (running the certificate write, level advance, and skill seeding) before any write guarded the recommendation row, so a reject that landed a moment later could still commit RECOMMENDED -> REJECTED, leaving the row REJECTED while the student already held the certificate for the level.
- A review now claims the recommendation row first with a compare-and-set (RECOMMENDED -> APPROVING/REJECTING) that stamps `claimed_at`, taken before any side effect runs. Exactly one of two concurrent reviewers wins the CAS; the loser is refused and has written nothing.
- The claim is a 10-minute lease, reclaimable if the holder's process died mid-review, and an ordinary review failure releases the claim immediately — a failed approval is retryable at once with no recovery job needed.
- Claimed rows still count as active for duplicate-recommendation checks (`get_active_for_student`, `list_active_for_students`, the `recs_active_unique` partial index) and still surface to admins in `list_pending`.
- Migration 0176 widens the `level_up_recommendations` status enum, adds `claimed_at`, and rebuilds the partial unique index.

## Deploy notes
- Migration required: apply `0176_level_up_claim_statuses` by hand — prod does not run migrations on boot.
- No other manual steps.

## Risk / rollback
Moderate risk — touches the level-up review write path and a status-enum/index migration, but the CAS is additive (existing single-reviewer flows still work) and the migration only widens the enum and rebuilds an index rather than altering existing documents' data. Rollback: revert this PR; the migration is additive and does not need to be reversed to roll back the code (a widened enum with an unused claim status is harmless).

PR: #0
