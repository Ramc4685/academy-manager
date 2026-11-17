# messaging-and-campaigns

PR: TBD

## What changed
Campaigns can now send from a resumable background job instead of inside the admin's request. With the setting on, a new campaign is saved with its recipient queue and the request returns straight away; a leased job claims one queued delivery at a time, sends it under a per-delivery idempotency key, and closes the campaign when the queue is empty. A crash or redeploy resumes where it stopped, and a stale claim is reclaimed after 10 minutes without mailing the family twice. Campaigns created before the switch, or with it off, send inline exactly as today.

## Deploy notes
No migration; existing campaign documents read as inline. Optional env var `V2_CAMPAIGN_BACKGROUND_SEND_ENABLED=true` turns the queue on (default false). Stacked on the messaging-reliability branch; merge that first.

## Risk / rollback
Turning the setting off stops new campaigns from queuing; any campaign already queued keeps status sending until the setting is turned back on. Roll back by reverting the PR after the queue has drained.
