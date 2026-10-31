# parent-evening-wins

PR: #TBD

## What changed
Parents now get one short "evening win" email on any academy-local day when their child mastered a skill or finished a level, and no email on days without a win. A skill win reads like "Aarav mastered Forecourt movement today. That's 3 of 6 skills in Level 2, three to go." A level-up gets a celebration and a "See the certificate" button. Every email links to the child's page on `/parent/progress`. A family with two children gets one email covering both. It is a digest-category email, so a parent who unsubscribed from digests gets none, and every email carries the unsubscribe footer. The wins are read from state: skills that are PASSED with today's `last_updated_at`, and certificates issued today. An undone tap therefore never shows up. A new hourly `send_parent_evening_wins` job sends once per academy-local day at 19:00, after the 18:30 level-up sweep from the tap-to-master change.

## Deploy notes
Migration `0213_parent_win_sends` adds the unique `(academy_id, parent_id, digest_date)` claim index on the new `parent_win_sends` collection. It runs automatically on boot only if `V2_RUN_MIGRATIONS_ON_BOOT` is true. Otherwise apply it by hand before or right after deploy. The claim stays safe without the index (`claim_digest_send` verifies after insert). No new env vars. The first evening after deploy, every BLNO family whose child had a win that day gets an email.

## Risk / rollback
Low to medium: this is a new outbound email to parents. Wins tapped after 19:00 local are not emailed; the next run only looks at its own day. If the copy or volume is wrong, remove the job, or revert the PR to stop the sends. The `parent_win_sends` collection and its index are harmless to leave behind.
