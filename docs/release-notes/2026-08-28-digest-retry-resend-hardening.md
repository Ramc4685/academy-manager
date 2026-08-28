# digest-retry-resend-hardening

PR: #489

## What changed

A failed coach or parent daily digest is now retried on the next hourly tick instead of being lost for the day — capped at 3 attempts, and never at the cost of sending the same digest twice. The Resend API key is validated once at boot and a rejection is alerted, so an expired key is caught on the deploy that broke it rather than weeks later; the daily ops digest also reports failed digest sends. Autopay dunning failure notices now go through the outbox, so a transient email error no longer means the parent is never told their payment failed.

## Deploy notes

Migration `0153_digest_send_attempt_count` backfills `attempt_count` on existing `coach_digest_sends` and `parent_digest_sends` rows. It runs **automatically on boot** (`run_migrations_on_boot`); no manual step. It is required for the retry to work on rows written before this deploy.

Boot now makes one outbound Resend request (`Domains.list`) when `email_delivery_enabled` and `resend_api_key` are both set, bounded by a 10s timeout and never fatal. No new env vars. Bounce/complaint webhooks and a suppression list are explicitly out of scope and still open.

## Risk / rollback

Main risk is the digest re-claim: if it matched too broadly a recipient could be emailed twice. It is a single conditional update restricted to `status: failed` with attempts remaining, so `sent` and in-flight `queued` rows can never match, and two concurrent ticks cannot both win it. Dunning notices switching to the outbox makes delivery asynchronous (seconds later, via the dispatcher) rather than inline.

Rollback: revert the PR. The `attempt_count` and `retryable` fields left on existing documents are ignored by the previous code, so no data cleanup is needed.
