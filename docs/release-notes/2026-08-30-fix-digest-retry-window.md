# digest-retry-window

PR: #558

## What changed
The digest retry ladder added by #435 / PR #489 could never fire. The digest
jobs tick hourly, but each academy only acted when `schedule.hour ==
current_hour`, so it got exactly one `try_claim` per recipient per day — and
`reclaim_failed_send` is only reachable from `try_claim`'s duplicate-key
branch, against a claim key that includes `digest_date`. A row that failed
today could therefore only be reclaimed by a later tick today, which the
exact-hour gate made impossible: a Resend outage or a deploy spanning the
digest hour silently lost that day's digest for every recipient. The gate is
now `current_hour >= schedule.hour`, so the digest hour opens a window that
closes at midnight when `digest_date` rolls over.

Separately, `try_claim` inserts the QUEUED row *before* sending, so a crash
between the insert and `mark_sent`/`mark_failed` left a row that was neither
`failed` (not reclaimable) nor releasable — it held the unique
`(academy, recipient, date)` claim for that date forever. The reclaim now also
matches `queued` rows older than `STALE_QUEUED_AFTER` (15 minutes), chosen to
sit above the jobs' 10-minute `job_lease` so a run still holding its lease can
never have its own claim stolen. `sent` and `skipped` remain unmatchable at any
age. `reclaim_failed_send` is renamed `reclaim_retryable_send`, and the tick
predicate is extracted as `digest_window_open` so it can be unit-tested — the
original bug shipped because that rule lived in a scheduler closure no test
could reach.

## Deploy notes
No migration. Existing `attempt_count` / `retryable` fields and migration 0154
are unchanged — they simply become reachable. Digest jobs now do real work on
every tick from the digest hour to midnight instead of one tick a day; the
extra cost per later tick is one duplicate-key insert and one indexed no-op
re-claim per recipient, because `try_claim` runs before plan generation.

## Risk / rollback
The behaviour change is that a recipient whose send failed earlier in the day
may now receive the digest later that day rather than not at all — intended,
but it means digests can arrive off the configured hour. Retries stay bounded
by `MAX_DIGEST_SEND_ATTEMPTS` (3). The stale-QUEUED reclaim is the riskier
half: if a send could ever legitimately stay in flight beyond 15 minutes while
its job had lost the 10-minute lease, two runs could both send. Raise
`STALE_QUEUED_AFTER` if the lease is ever lengthened — the two constants are
coupled and that coupling is documented at both sites. Roll back by reverting
the merge commit; no state is persisted that a revert would strand, and rows
reclaimed while it was live are ordinary queued/sent rows afterwards.
