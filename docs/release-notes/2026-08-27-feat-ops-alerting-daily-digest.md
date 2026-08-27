# feat(ops): alerting for background failures — scheduler listener, Sentry, daily ops digest

PR: #439

## What changed

Closes #428. Background failures previously ended at a local log line: Sentry
was wired only for the request path, so APScheduler job crashes and the outbox
dispatcher's top-level loop guard reported nothing, and quarantined webhooks,
dead-letter events, and dunning terminals accumulated in Mongo unobserved.

- **APScheduler error listener.** `backend/v2/main.py` registers
  `handle_scheduler_job_event` for `EVENT_JOB_ERROR | EVENT_JOB_MISSED` before
  `scheduler.start()`. Job errors log with `exc_info` and are sent to Sentry via
  `capture_exception`; misfires (no exception object) log and send a
  `capture_message` at warning level. The listener never raises — APScheduler
  dispatches listeners inline, so a raise there would take down the notification
  for every other listener. The scheduler now sets
  `job_defaults={"misfire_grace_time": 30}`: APScheduler's 1-second default
  would have turned routine event-loop stalls on the 60s webhook-drain job into
  a steady stream of misfire alerts.
- **Dispatcher loop guard.** `backend/v2/shared/events/dispatcher.py` calls
  `capture_exception(exc)` inside the `_run_loop` top-level `except`, alongside
  the existing `log.exception`. The capture is itself wrapped (a Sentry
  transport error must not escape the last-resort guard and kill the dispatcher
  for the process lifetime) and throttled via `should_report_failure` — the
  loop polls once a second, so a sustained Mongo outage reports on the 1st,
  10th, then every 100th consecutive failure instead of ~86k times a day.
- **Daily owner ops digest.** New `send_ops_digest` scheduler job (daily cron at
  07:00 in `SCHEDULER_TZ`, guarded by the existing Mongo `job_lease`) emails a
  cross-academy summary to `OPS_ALERT_EMAIL`: quarantined + failed
  `stripe_webhook_events`, `dead_letter_events` (total and last 24h), dunning
  terminals in the last 24h, and the last monthly-invoice-generation counts.
  The snapshot is stamped in the scheduler timezone so the subject line does not
  carry yesterday's date in a UTC+ deployment, and a failed send (Resend returns
  `SendOutcome(ok=False)` rather than raising) logs at error and reports to
  Sentry — the alerting channel's own failure must not be silent.
- **Actionable attention flag.** The "attention needed" subject uses only
  signals a human can act on today: quarantined webhooks *in the window* (the
  all-time total still shows in the body, but one old unreplayed event must not
  pin the subject forever) and failed webhooks whose `next_retry_at` is more
  than an hour overdue (a plain `failed` count is a transient retry state that
  self-heals on the next 60s drain tick).
- **Invoice run recording.** `_generate_monthly_invoices_body` writes its totals
  to a new `ops_job_runs` collection (`_id = "generate_monthly_invoices"`) so
  the digest can report them from whichever machine holds the digest lease. The
  job ticks daily but only generates on each academy's `billing_day`, so an
  empty tick records a `last_tick_at` heartbeat only (`meaningful=False`) and
  leaves the last real run's totals intact.
- New shared modules `backend/v2/shared/observability/ops_alerts.py` and
  `ops_digest.py`; new setting `ops_alert_email` with the standard two-tier
  `V2_OPS_ALERT_EMAIL` → `OPS_ALERT_EMAIL` fallback.
- `dunning_states` and `stripe_webhook_events` are now registered in the
  `TENANT_OWNED_COLLECTIONS` ratchet (`v2/tests/test_no_raw_tenant_mongo_access.py`),
  which was previously blind to them, with `ops_digest.py` recorded in a new
  `APPROVED_CROSS_TENANT_EXCEPTIONS` set for by-design cross-tenant readers.
- Unit tests: `backend/v2/tests/unit/test_ops_alerts.py` (25 tests) cover the
  listener callback, the failure-report backoff, the dispatcher surviving a
  raising Sentry, and digest collection/rendering with fakes.

No new routes, so the audit inventory manifest is unchanged.

## Deploy notes

Two new environment variables, both optional and both no-ops when unset:

- `OPS_ALERT_EMAIL` — owner recipient for the daily ops digest. Unset ⇒ the job
  logs `ops_digest_skipped` and sends nothing. (`V2_OPS_ALERT_EMAIL` takes
  precedence if set.)
- `SENTRY_DSN` — already read by `configure_error_tracking`; set it in prod so
  scheduler and dispatcher failures actually leave the box. Unset ⇒ Sentry stays
  disabled and the new code paths log only.

Email delivery reuses the existing digest send port and its guard: real Resend
delivery requires `EMAIL_DELIVERY_ENABLED=true`, `RESEND_API_KEY`, **and**
`APP_ENV` in {staging, prod}; every other environment uses the stub. No
migration is required — `ops_job_runs` is created implicitly on first upsert.

## Risk / rollback

Low. All three pieces are additive and fail-open:

- The listener is advisory and swallows its own exceptions; it cannot affect job
  execution.
- The dispatcher change adds one throttled, self-guarded call after the existing
  log line; with no DSN it returns immediately, and a raising Sentry is caught
  rather than escaping the loop.
- The digest job is leased like every other scheduled job, is read-only apart
  from the `ops_job_runs` upsert, and short-circuits when `OPS_ALERT_EMAIL` is
  unset. Its probes run concurrently and each is isolated, so an unreadable
  collection degrades to a line in the email rather than failing the job.
- `misfire_grace_time: 30` is a scheduler-wide default change. It is far shorter
  than any job's own interval (the tightest is 60s), so no job's timing moves;
  it only widens the window before APScheduler declares a run missed.

The one behaviour worth watching after deploy is alert volume: if misfire
warnings still appear for `process_stripe_webhook_events`, raise the grace time
rather than removing the listener.

Rollback: unset `OPS_ALERT_EMAIL` to silence the digest and `SENTRY_DSN` to
silence the reports, or revert the PR — no data migration to undo.
