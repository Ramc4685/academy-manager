# Win-back emails: fix the daily job crash on Mongo datetimes

PR: #TBD

## What changed

- The daily `send_win_back_notices` job (30/60/90-day emails to families who left, issue #778) crashed for BLNO on every attempt with `TypeError: can't subtract offset-naive and offset-aware datetimes`. The enrollment lifecycle event repository returned `effective_at` / `occurred_at` exactly as Mongo stores them, without a timezone (the Mongo client does not use `tz_aware`). The win-back job then subtracted that from the current time, which does have a timezone.
- `MongoEnrollmentEventRepository` now marks both fields as UTC when it reads them, with the shared `ensure_utc` helper (the #706 pattern). This also covers the leaving report and the move-history read, which use the same repository.
- This did not start with #1011. The repository has returned these values without a timezone since win-back shipped in #813. The job failed on the first "dropped" event in its 92-day lookback, before it claimed or sent anything, so it is unlikely any win-back email has ever gone out. Before #1011 the error went only to Sentry. #1011 made it visible as a failed per-academy scheduler marker.
- No change to milestone rules or deduplication. New contract tests run on mongomock and on a real `mongod`. They cover: the job with the default clock, a retried tick or the next day's tick not re-sending a milestone already sent, and a missed day being picked up on the next tick.

## Deploy notes

- No migration and no config change.
- After deploy, the next hourly tick that reaches 04:30 America/Chicago runs today's win-back for BLNO. The failed marker `send_win_back_notices:acad_blno_badminton:2026-09-29` stays failed, and there is no catch-up run for 29 Sep.
- A missed day does not skip a milestone. Each tick works out, for every "dropped" event in the last 92 days, the highest milestone already reached (30, 60 or 90 days), and sends it if it has not already been sent for that departure. A 30-day email missed on 29 Sep therefore goes out on the next tick that succeeds. A milestone is only lost once the next one takes its place: a family past day 60 gets the 60-day email, not the 30-day one. After day 92 nothing is sent.
- Expect a one-time batch on the first tick that succeeds. The job has never completed, so every departed family between 30 and 92 days out (no seat-holding enrollment, no balance owed, win-back switch on) gets one email for the highest milestone it has reached. Check the `win_back_notices_sent` log line and the `win_back_notice_sends` collection after the 04:30 Chicago tick.

## Risk / rollback

- Low. The change is limited to how two datetime fields are read in one repository. The values are the same moments in time, now marked as UTC. Every consumer was already comparing against or displaying UTC-aware times.
- Rollback: revert the PR. The job goes back to failing every day, and nothing it wrote needs cleaning up. Emails that were already sent are recorded in `win_back_notice_sends` and are not sent again after a re-deploy.
