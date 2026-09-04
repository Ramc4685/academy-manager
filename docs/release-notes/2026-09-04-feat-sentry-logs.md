# feat-sentry-logs

PR: #655

## What changed
- With `SENTRY_DSN` set, INFO and above from the backend's JSON logging
  pipeline are forwarded to Sentry Logs (30-day retention, searchable by
  `request_id` and `academy_id`) in addition to error events. Errors are
  captured exactly as before.
- A `before_send_log` guard keeps the free plan's 5 GB/month quota safe:
  DEBUG records, `uvicorn.access`, and the health-probe request line are
  never sent.
- New setting `sentry_logs_enabled` (`V2_SENTRY_LOGS_ENABLED` or
  `SENTRY_LOGS_ENABLED`, default true) switches log forwarding off without
  disabling error tracking.
- Traces remain at 0, profiling off, `send_default_pii=False`.

## Deploy notes
No new secrets. Nothing is sent until `SENTRY_DSN` is set on the Fly app.
After it is set, Sentry → Logs should show request lines within a minute of
the machine restart. If the quota is ever exhausted Sentry drops further
logs for the month; nothing is billed on the free plan.

## Risk / rollback
Low. Log forwarding runs inside the Sentry SDK's own background worker; it
cannot block a request. Set `SENTRY_LOGS_ENABLED=false` to stop forwarding
without a deploy, or revert this PR.
