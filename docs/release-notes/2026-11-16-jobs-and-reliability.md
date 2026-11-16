# jobs-and-reliability

PR: TBD

## What changed
Background jobs recover faster and fail louder. A monthly invoice run that fails, finishes partly or cannot send its emails now retries on the next hourly tick (up to three times that day) instead of the next day, with no duplicate invoices or emails. Autopay retries, PaymentIntent reconcile and stalled-hold recovery run on the wall clock, so deploys no longer push them back. A failed event handler retries for about an hour (was six minutes), and a dead-lettered event now logs an error and reaches Sentry at once. The Stripe webhook drain and reconcile loops skip a failing academy instead of stopping. An autopay charge that keeps failing for a technical reason stops retrying after 24 hours, shows under failed autopay as needing attention and alerts. If the scheduler or event dispatcher dies, the app exits so Fly restarts it: Fly only stops routing to a machine whose health check fails, it never restarts it. The frontend now deploys only after migrations and the backend deploy have succeeded.

## Deploy notes
Migration `0233_outbox_ttl` adds two TTL indexes: processed `outbox_events` rows and succeeded `event_handler_runs` rows expire 90 days after they finish. Pending, retrying, failed and dead-lettered rows never expire. The first TTL pass deletes every finished row older than 90 days. That is a one-off burst of deletes, small at today's volume. Nothing else to do: it applies through the release_command.

Owner steps:
- Confirm Atlas Cloud Backup is on for the production cluster, with daily snapshots and 30-day retention. If the tier cannot do that, schedule `backend/scripts/backup_restore.py` as `docs/runbooks/backup-restore.md` describes (A7-3). The repo cannot check this setting.

## Risk / rollback
A run with invoice emails that fail permanently, such as a parent with no usable address, now fails its local-day marker and reports to Sentry up to three times a day while the period's send pass keeps finding that invoice. It is noisier, but it never duplicates anything. A ladder capped as `technical_failure_capped` is not retried on its own: after an outage of more than 24 hours, the admin charges those invoices by hand from failed autopay. If the watchdog misjudges a healthy process, it restarts it every 30 seconds; watch for restart alerts after deploy. Roll back by reverting the merge commit. The TTL indexes can stay, or you can drop them with `dropIndex("outbox_processed_ttl")` and `dropIndex("event_handler_runs_succeeded_ttl")`.
