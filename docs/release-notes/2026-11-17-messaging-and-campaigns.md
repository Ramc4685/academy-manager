# messaging-and-campaigns

PR: TBD

## What changed
Campaigns can now send from a resumable background job instead of inside the admin's request. With the setting on, a new campaign is saved with its recipient queue and the request returns straight away; a leased job claims one queued delivery at a time, sends it under a per-delivery idempotency key, and closes the campaign when the queue is empty. A crash or redeploy resumes where it stopped, and a stale claim is reclaimed after 10 minutes without mailing the family twice. Only the worker holding the current claim can record a result, and a delivery whose worker dies five times is marked failed (`send_gave_up`) so the campaign can still close. The campaign becomes visible to the job only after its whole queue is saved. The composer shows "Queued for N" for a queued campaign instead of a delivered count, including when a retried send lands while the queue drains. The daily ops digest flags any campaign still sending after 30 minutes (one whose request died before the hand-off, or a very large campaign still draining). `V2_MARKETING_SENDER_EMAIL` is now checked once when settings load. Campaigns created before the switch, or with it off, send inline exactly as today.

Admin Messages has a new Delivery problems panel: the academy's own people whose address is suppressed (bounce or spam complaint) and failed campaign sends. It reads the existing bounce data for the academy's own members only. Because the block list is shared by every academy, each blocked address shows only a generic "not receiving email" line, never the reason or date, and failed sends show a generic status rather than provider text. Sends held back by the shared block list are not listed as failures; a send held back because the person unsubscribed from this academy's email is listed as "They unsubscribed from these emails". The family Messages tab and the coach digest test send and log show the same plain-language codes, never a raw block-list reason. The panel is read-only: clearing an address stays a platform support action.

Push now has an event catalogue. The four events that already pushed (class date cancelled, waitlist offer, urgent announcement, dues reminder) are unchanged. Three new opt-in events push the recipients' phones: a direct message from the academy, an academy broadcast, and a routine class announcement. Broadcasts and announcements skip anyone who turned notifications off. `PUSH_DELIVERY_ENABLED` stays the global switch.

The session email campaign no longer calls its enrolled students "families" (#1029): it now says it reaches the families of N students, one email per family, since siblings share a parent email.

## Deploy notes
No migration; existing campaign documents read as inline. Optional env vars, all off by default: `V2_CAMPAIGN_BACKGROUND_SEND_ENABLED=true` turns the campaign queue on (set `V2_EMAIL_SEND_MAX_RETRIES` to 2 or more first, so a Resend 429 retries instead of failing the delivery); `V2_PUSH_EXTRA_EVENTS` is a comma list of `direct_message`, `academy_broadcast` and `class_announcement`. Stacked on the messaging-reliability branch; merge that first.

## Risk / rollback
The setting is not a kill switch: turning it off stops new campaigns from queuing, but the background job always drains campaigns that are already queued. The Delivery problems panel is additive and read-only. Roll back by reverting the PR after the queue has drained.
