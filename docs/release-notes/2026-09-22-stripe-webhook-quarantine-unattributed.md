# stripe-webhook-quarantine-unattributed

PR: #914

## What changed

- The Stripe webhook ingest (`HandleWebhookEvent.accept`) no longer attributes an event that carries neither `metadata.academy_id` nor a Connect `account` marker to the boot academy when the deployment runs in `multi_academy` mode. Such an event is stored under the sentinel academy `__unattributed__` (which no per-academy drain ever claims), marked `quarantined` with reason `unattributed_no_tenant_marker`, logged as a structured warning, alerted once through the existing quarantine ops alert (Sentry `capture_message`), and acknowledged to Stripe with 200 so it is not retried forever. Retries of the same event hit the insert-first dedup and produce no second row and no second alert.
- Rule for the platform (non-Connect) path: in `single_academy` mode (`APP_TENANCY_MODE=single_academy`) there is exactly one tenant, `PRIMARY_ACADEMY_ID`, by construction, so an unmarked platform event is still attributed to it for every event type; no event-type allowlist is needed because there is no second academy it could belong to. In `multi_academy` mode no unmarked event is attributed to anyone.
- The structured `stripe_webhook_event_quarantined` log line for an ingest-time quarantine carries `academy_id: "__unattributed__"` (the bucket the row was stored under), not the boot academy, so the alert and the Mongo filter above agree. Processing-side quarantines keep logging the handler's own academy.
- Events that do carry a Connect `account` marker which fails to resolve are unchanged: the processing-side guard already quarantines and alerts on those.
- `HandleWebhookEvent` gains a `tenancy_mode` constructor parameter (default `single_academy`); `compose_parent` and `compose_parent_webhook_handler` pass `settings.tenancy_mode`.

## Deploy notes

No migration, no new index, no new environment variable. The current production deployment runs `APP_TENANCY_MODE=single_academy`, so behavior there is unchanged. Before a second academy is onboarded in `multi_academy` mode, ops should watch for the `Stripe webhook event quarantined (unattributed_no_tenant_marker)` alert; each one names a Stripe event id that needs a human to decide which academy it belongs to (no admin UI lists the `__unattributed__` bucket yet; use the `stripe_webhook_events` collection filtered on `academy_id: "__unattributed__"`).

## Risk / rollback

Low. Single-academy behavior is byte-for-byte the same and covered by tests. In multi-academy mode the only new outcome is that an unattributable event is parked instead of being processed against the boot academy, which is the intended trade. Rollback is a revert of the PR; quarantined rows would then stay quarantined under `__unattributed__` and could be replayed by hand once re-stamped with a real `academy_id`.
