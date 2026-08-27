# feat(ops): alerting for background failures — scheduler listener, Sentry, daily ops digest

PR: #TBD

## What changed

Closes #428. Background failures previously ended at a local log line: Sentry
was wired only for the request path, so APScheduler job crashes and the outbox
dispatcher's top-level loop guard reported nothing, and quarantined webhooks,
dead-letter events, and dunning terminals accumulated in Mongo unobserved.

- **APScheduler error listener.** `backend/v2/main.py` registers
  `handle_scheduler_job_event` for `EVENT_JOB_ERROR | EVENT_JOB_MISSED` before
  `scheduler.start()`. Job errors log with `exc_info` and are sent to Sentry via
  `capture_exception`; misfires (no exception object) log and send a
  `capture_message`. The listener never raises — APScheduler dispatches
  listeners inline, so a raise there would take down the notification for every
  other listener.
- **Dispatcher loop guard.** `backend/v2/shared/events/dispatcher.py` now calls
  `capture_exception(exc)` inside the `_run_loop` top-level `except`, alongside
  the existing `log.exception`.
- **Daily owner ops digest.** New `send_ops_digest` scheduler job (daily cron at
  07:00 in `SCHEDULER_TZ`, guarded by the existing Mongo `job_lease`) emails a
  cross-academy summary to `OPS_ALERT_EMAIL`: quarantined + failed
  `stripe_webhook_events`, `dead_letter_events` (total and last 24h), dunning
  terminals in the last 24h, and the last monthly-invoice-generation counts.
- **Invoice run recording.** `_generate_monthly_invoices_body` writes its totals
  to a new `ops_job_runs` collection (`_id = "generate_monthly_invoices"`) so
  the digest can report them from whichever machine holds the digest lease.
- New shared modules `backend/v2/shared/observability/ops_alerts.py` and
  `ops_digest.py`; new setting `ops_alert_email` with the standard two-tier
  `V2_OPS_ALERT_EMAIL` → `OPS_ALERT_EMAIL` fallback.
- Unit tests: `backend/v2/tests/unit/test_ops_alerts.py` (12 tests) cover the
  listener callback and digest collection/rendering with fakes.

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
- The dispatcher change adds one call after the existing log line; with no DSN
  it returns immediately.
- The digest job is leased like every other scheduled job, is read-only apart
  from the `ops_job_runs` upsert, and short-circuits when `OPS_ALERT_EMAIL` is
  unset. Each Mongo probe is isolated, so an unreadable collection degrades to a
  line in the email rather than failing the job.

Rollback: unset `OPS_ALERT_EMAIL` to silence the digest and `SENTRY_DSN` to
silence the reports, or revert the PR — no data migration to undo.
