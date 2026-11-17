# messaging-and-campaigns

PR: TBD

## What changed
Campaigns can now send from a resumable background job instead of inside the admin's request. With the setting on, a new campaign is saved with its recipient queue and the request returns straight away; a leased job claims one queued delivery at a time, sends it under a per-delivery idempotency key, and closes the campaign when the queue is empty. A crash or redeploy resumes where it stopped, and a stale claim is reclaimed after 10 minutes without mailing the family twice. Campaigns created before the switch, or with it off, send inline exactly as today.

Admin Messages has a new Delivery problems panel: the academy's own people whose address is suppressed (bounce or spam complaint) and failed campaign sends. It reads the existing bounce data for the academy's own members only. Because the block list is shared by every academy, the reason and date show only when the problem was recorded under this academy; otherwise the row just says the address is not receiving email. The panel is read-only: clearing an address stays a platform support action.

Push now has an event catalogue. The four events that already pushed (class date cancelled, waitlist offer, urgent announcement, dues reminder) are unchanged. Three new opt-in events push the recipients' phones: a direct message from the academy, an academy broadcast, and a routine class announcement. Broadcasts and announcements skip anyone who turned notifications off. `PUSH_DELIVERY_ENABLED` stays the global switch.

## Deploy notes
No migration; existing campaign documents read as inline. Optional env vars, all off by default: `V2_CAMPAIGN_BACKGROUND_SEND_ENABLED=true` turns the campaign queue on; `V2_PUSH_EXTRA_EVENTS` is a comma list of `direct_message`, `academy_broadcast` and `class_announcement`. Stacked on the messaging-reliability branch; merge that first.

## Risk / rollback
Turning the setting off stops new campaigns from queuing; any campaign already queued keeps status sending until the setting is turned back on. The Delivery problems panel is additive and read-only. Roll back by reverting the PR after the queue has drained.
