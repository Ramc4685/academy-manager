# webhook-retry-cap-quarantine

PR: #491

## What changed

A Stripe webhook event that keeps failing is now auto-quarantined after 24 attempts (roughly a day of the existing 1m/5m/15m/hourly backoff) instead of retrying forever, and an alert is raised the one time it gives up. Because a quarantined event is no longer claimed by the 60s drain job, a poisoned event stops occupying one of the 25 attempts in every tick and stops delaying real payment events. Quarantined events now record *why*, so the admin Billing Health card's "quarantined" and "failed" counts mean two different things: needs a human, versus still retrying.

## Deploy notes

No migration and no new env vars. The new `quarantine_reason` and `quarantined_at` fields are written going forward and are read defensively when absent on existing rows.

Expect the quarantined count on the Billing Health card to rise once shortly after deploy: events already past 24 attempts will quarantine on their next drain tick. That is the existing backlog becoming visible, not new breakage. Each one alerts as it quarantines, so a large backlog produces a burst of alerts on the first day.

## Risk / rollback

The main risk is quarantining too eagerly and stopping retries that would have succeeded — the cap is set at 24 attempts to make that unlikely, and a below-cap failure is unchanged. Quarantined events are not lost: the existing admin replay puts one back in the drain with a fresh budget and clears its quarantine metadata. Guard rejections (e.g. a livemode mismatch) now also alert per event, so a deployment pointed at the wrong Stripe mode will be noisy.

Rollback: revert the PR. Events already quarantined stay quarantined and remain replayable by an admin; the extra fields are ignored by the previous code.
