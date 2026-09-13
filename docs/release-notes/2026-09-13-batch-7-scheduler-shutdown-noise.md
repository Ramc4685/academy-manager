# batch-7-scheduler-shutdown-noise

PR: #0

## What changed

- Fixes #752 — A Fly deploy that overlapped an in-flight scheduled job (e.g. the 10-minute Stripe reconcile) cancelled the job's task, and APScheduler surfaced that `CancelledError` as `EVENT_JOB_ERROR`. `handle_scheduler_job_event` in `backend/v2/shared/observability/ops_alerts.py` treated every job error the same, so `ops_alerts` paged Sentry on routine deploy-time cancellation and buried real failures of the same job under the noise. The listener now checks whether the job's exception is `asyncio.CancelledError`: if so it logs `scheduler_job_cancelled` at info and skips Sentry entirely; any other exception (including one raised mid-shutdown) still logs `scheduler_job_error` at error and reports to Sentry exactly as before.
- Also added a bounded scheduler drain at shutdown (`_drain_scheduler` in `backend/v2/main.py`, 10s, under `fly.toml`'s 30s `kill_timeout`): the lifespan's `finally` block now pauses the scheduler and awaits any in-flight job futures before calling `scheduler.shutdown(wait=False)`, so fewer runs get cut off at all. `AsyncIOExecutor.shutdown`'s `wait` argument is a no-op for asyncio jobs (it cancels every pending future unconditionally), so the wait has to happen explicitly beforehand. The drain never raises — a scheduler that misbehaves during shutdown just falls through to the existing `shutdown(wait=False)` call, so the outbox dispatcher stop and Mongo client close that follow it are unaffected.

## Deploy notes

No migrations, no new environment variables, no config changes. Both changes are internal to the FastAPI lifespan and the scheduler-event listener; no new required manual step.

## Risk / rollback

Low risk. The exemption in `handle_scheduler_job_event` is scoped strictly to `asyncio.CancelledError` — every other exception path (real job failures, mid-shutdown errors) is unchanged and still pages Sentry. The new `_drain_scheduler` step only runs in the shutdown path, is bounded at 10 seconds (well under the 30s Fly kill timeout), and is wrapped so any internal failure is logged and swallowed rather than propagated, so it cannot strand the Mongo client or outbox dispatcher shutdown that follow it. If anything regresses, revert this PR's merge commit.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
