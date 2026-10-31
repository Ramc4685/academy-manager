# Scheduled jobs and digests run on each academy's local clock (Settings overhaul Phase 4 PR 12)

PR: #1011

## What changed

- **Night jobs run per academy at the academy's local time.** Resumes (02:00), makeup-request expiry (02:30), hold expiry (02:45), monthly invoices (03:00), hold reminders (04:00), win-back notices (04:30), trial follow-ups (04:50), the owner brief (07:30) and the past-due reminder sweep (09:20) used to fire on `SCHEDULER_TZ` (Chicago in production) for every academy. Each now ticks hourly and runs once per academy-local date as soon as that academy's wall clock reaches the same time, on `academies.timezone` (an academy with no zone uses `LEGACY_FALLBACK_TIMEZONE`, BLNO's zone).
- **Once per local day, DST-safe.** A new `scheduler_run_markers` row per `(job, academy_id, local_date)` is claimed before the run; its `_id` is that triple, so the claim is atomic even before migration 0210 runs. Spring forward runs a 02:xx job at 03:xx (the same instant APScheduler used); fall back runs once; a tick missed by a deploy or restart catches up later the same local day.
- **Failures are per academy.** One academy raising is logged and sent to Sentry and never stops the others (new for every night job except trial follow-ups, and for both digests). A failed run is marked `failed` and retried on the next hourly ticks of the same local day, up to 3 attempts; a run whose process died is re-claimable after 2 hours. The owner brief gets one claim per academy-local day: a brief that failed, crashed or was cancelled by a deploy mid-send is reported and not retried, because it records no per-recipient send and a retry could mail owners already mailed.
- **Monthly invoices read `billing_day` and the period on the academy-local date.**
- **Coach and parent digests** send at the academy's local digest hour, and `digest_date` (which `parent_digest_sends` and the CRM Messages thread key on) is the academy-local date. The parent digest's "today's class" window and the coach-digest test send's default date use the academy zone too, not `SCHEDULER_TZ`. The env-default schedule, the `>=` window and `admin_cc_enabled` are unchanged.
- **Stays platform-wide on `SCHEDULER_TZ`:** only the engineering ops digest (07:00, one cross-academy email to `OPS_ALERT_EMAIL`). The interval jobs (webhook drain, reconciliation, dunning, cancellations, waitlist sweep, stalled reclaims) have no wall-clock time and are unchanged.
- **Monitoring:** the Sentry cron configs for the converted jobs are hourly crontabs at the job's minute (every tick checks in), and their ops-digest stale window drops from 26h to 3h, like the other hourly jobs. The ops digest's "Last invoice generation" counts are now summed over the window since the previous ops digest, because academies generate on separate hourly ticks; a later academy's tick no longer replaces BLNO's generation counts.
- **Cutover:** where the old cron already ran today (its `ops_job_runs` heartbeat is on the academy's local today at or after the job's time), today's marker is seeded as done, so deploying after 07:30 does not send a second owner brief. This check runs at boot and on every tick, so an old machine that keeps running the job during a rolling deploy is covered too. The new code marks its own heartbeats (`local_clock_tick_at`), so only an old-code heartbeat counts.
- **Intended move for a zoneless academy's past-due reminders.** The old sweep read a zoneless academy's day in UTC, so its reminders went at 09:20 UTC. The spec allows only the legacy fallback, so they now go at 09:20 Chicago. This does not affect BLNO, whose zone is set.

## Deploy notes

- Migration **0210_scheduler_run_markers**: a unique `(academy_id, job, local_date)` index and a 60-day TTL on `created_at`. New, empty collection; idempotent. Correctness does not depend on it (the claim uses `_id`), so the usual hand-applied migration order is fine. 0208/0209 are reserved for parallel batches.
- **BLNO does not move.** BLNO's `academies.timezone` is `America/Chicago` and production `SCHEDULER_TZ` is `America/Chicago`, so every job and digest fires at the same instant as before (pinned by tests across a spring-forward and a fall-back day). BLNO's zone was last read as `America/Chicago` in prod on 2026-09-01 (session-timezone repair). Before deploying, confirm it is still set: every night job and digest keeps Chicago for an unset zone through the legacy fallback, but the past-due sweep would move from 09:20 UTC to 09:20 Chicago.
- An academy with a different zone moves to its own local time on the first day after deploy; any job it already ran that day under the old Chicago clock is covered by the heartbeat seed.
- `settings.scheduler_tz` / `SCHEDULER_TZ` is now used only for the ops digest trigger and Sentry monitor timezone.

## Risk / rollback

- Risk: a job now runs hourly-ticked instead of once-daily; the marker is the only thing stopping a second run the same local day. The claim uses the always-present `_id` index, and the tests replay whole days of ticks (including two concurrent machines) to pin exactly-once.
- Risk: a failing job retries up to 3 times the same day where it used to wait a day. Every converted job is an idempotent sweep (claims or run records), except the owner brief, which does not retry an in-body failure.
- Rollback: revert this PR. The old fixed-hour crons return; `scheduler_run_markers` is then unused and can be left in place (the TTL empties it) or dropped.
