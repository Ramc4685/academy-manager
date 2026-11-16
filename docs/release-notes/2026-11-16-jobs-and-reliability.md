# jobs-and-reliability

PR: TBD

## What changed
Background jobs recover faster and fail louder. A monthly invoice run that fails, finishes partly or whose email pass crashes now retries on the next hourly tick (up to three times that day) instead of the next day, with no duplicate invoices or emails. A single invoice email that fails is still re-sent by the next day's run. Autopay retries, PaymentIntent reconcile and stalled-hold recovery run on the wall clock, so deploys no longer push them back. A failed event handler retries for about an hour (was six minutes), and a dead-lettered event now logs an error and reaches Sentry at once. The Stripe webhook drain, reconcile and autopay retry loops skip a failing academy instead of stopping, then mark the run failed so the heartbeat shows it. An autopay charge that keeps failing for a technical reason backs off from hourly to daily retries after 24 hours, shows under failed autopay as needing attention and alerts. Because the cap is our own fault, the family gets no late fee and no past-due reminder while it lasts. A paid or voided invoice stands its ladder down on the next daily check. If the scheduler or event dispatcher dies, the app exits so Fly restarts it: Fly only stops routing to a machine whose health check fails, it never restarts it. The frontend now deploys only after migrations and the backend deploy have succeeded.

## Deploy notes
Migration `0233_outbox_ttl` adds two TTL indexes: processed `outbox_events` rows expire 400 days after they finish (they also stop a replayed webhook or a months-later dispute update from emailing a family twice, so they match `event_audit`), and succeeded `event_handler_runs` rows expire after 90 days. Pending, retrying, failed and dead-lettered rows never expire. The first TTL pass deletes every finished row past its window. That is a one-off burst of deletes, small at today's volume. Nothing else to do: it applies through the release_command.

Owner steps:
- Confirm Atlas Cloud Backup is on for the production cluster, with daily snapshots and 30-day retention. If the tier cannot do that, schedule `backend/scripts/backup_restore.py` as `docs/runbooks/backup-restore.md` describes (A7-3). The repo cannot check this setting.

## Risk / rollback
A ladder capped as `technical_failure_capped` is retried once a day, so after an outage of more than 24 hours collection resumes within a day of the fix. To collect sooner, the admin contacts the family or records a payment (no reminder goes out on its own); the next daily check then stands the ladder down. If the watchdog misjudges a healthy process, it restarts it every 30 seconds; watch for restart alerts after deploy. Roll back by reverting the merge commit. The TTL indexes can stay, or you can drop them with `dropIndex("outbox_processed_ttl")` and `dropIndex("event_handler_runs_succeeded_ttl")`.
