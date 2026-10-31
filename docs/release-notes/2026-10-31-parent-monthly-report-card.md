# parent-monthly-report-card

PR: #TBD

## What changed
Parents now get a monthly report card email on the first academy-local day of each month, covering the month just ended. Each child gets a card titled like "October for Aarav" with three tiles: new skills mastered that month, classes attended out of classes marked (for example 7/8; late counts as attended, voided marks are ignored), and the current level (for example L2). Below the tiles is a focus for the new month: the first required skill in the child's current level that is not mastered yet. When that skill has an active practice video in the curriculum, the email links it. A family with two children gets one email with a card for each. A child with no class mark and no new skill that month gets no card, and a family with no such child gets no email. It is a digest-category email, so a parent who unsubscribed from digests gets none, and every email carries the unsubscribe footer. A new hourly `send_parent_report_cards` job runs once per academy-local day at 09:00 and only sends on the 1st.

## Deploy notes
Migration `0214_parent_report_card_sends` adds the unique `(academy_id, parent_id, digest_date)` claim index on the new `parent_report_card_sends` collection, where `digest_date` holds the report month (`YYYY-MM`). It runs automatically on boot only if `V2_RUN_MIGRATIONS_ON_BOOT` is true. Otherwise apply it by hand before or right after deploy. The claim stays safe without the index (`claim_digest_send` verifies after insert). No new env vars. The first email goes out on the 1st of the month after deploy. Builds on the parent evening win email branch (migration 0213), so that lands first.

## Risk / rollback
Low to medium: this is a new outbound email to parents. Classes are counted by when the coach marked them, not the class date, so a class marked a day late can land in the next month's count. If the 1st's run fails for an academy all day, that month's card is skipped, not sent later. If the copy or volume is wrong, remove the job, or revert the PR to stop the sends. The `parent_report_card_sends` collection and its index are harmless to leave behind.
