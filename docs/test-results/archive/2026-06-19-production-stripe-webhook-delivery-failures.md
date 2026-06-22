# production stripe webhook delivery failures

## Current State

Status: active

## Problem

Stripe Dashboard shows 54/54 production webhook deliveries failed for https://api.academy.courtmastr.com/api/v2/parent/webhooks/stripe; identify root cause and fix safely.

## Changed Files

- None recorded yet.

## Log

- 2026-06-19T13:10:53 main/NA: Task ledger created.
- 2026-06-19T13:11:12 main/working: Confirmed screenshot shows Stripe destination active but 54/54 failed deliveries. Production health returned 200. Deliberate invalid-signature POST to production webhook returned 400 Billing.InvalidWebhookSignature, establishing expected failure shape for signing-secret mismatch.
- 2026-06-19T13:11:44 main/working: Fly app courtmastr-academy-api is healthy on machine version 103; secrets list shows STRIPE_WEBHOOK_SECRET deployed. This rules out host outage and missing webhook secret; still investigating exact failed delivery body/status.
- 2026-06-19T13:13:07 main/working: Live Fly log tail shows deliberate invalid-signature probe as POST /api/v2/parent/webhooks/stripe 400. Runtime env has STRIPE_WEBHOOK_SECRET set (len 38, whsec prefix) and no V2 override; handler uses that secret through Settings fallback.
- 2026-06-19T13:13:51 main/working: Using Fly live STRIPE_API_KEY, listed configured webhook endpoint: enabled, live, URL https://api.academy.courtmastr.com/api/v2/parent/webhooks/stripe, events include checkout.session.completed/expired, invoice paid/failed, payment_intent.payment_failed, charge.refunded, subscription updated/deleted. Recent Stripe API events with delivery_success=false are live checkout.session.expired events with pending_webhooks=1.
- 2026-06-19T13:15:06 main/working: Production Mongo stripe_webhook_events collection is empty (no received/processed/failed/quarantined webhook rows) despite Stripe showing pending failed deliveries. Since accept() verifies signature before store_received(), this points to failures before durable storage; with STRIPE_WEBHOOK_SECRET present, the leading hypothesis is a deployed signing-secret mismatch.
- 2026-06-19T13:17:44 main/working: Created replacement live Stripe webhook endpoint we_1Tk6yVRMJDJBjoQzb0xTew57 with same production URL/events, rotated Fly STRIPE_WEBHOOK_SECRET and V2_STRIPE_WEBHOOK_SECRET to the new one-time secret, waited for Fly machine health, and disabled old endpoint we_1TglsaRMJDJBjoQzN6Y50g9W.
- 2026-06-19T13:18:58 main/working: First bulk resend attempt had a local zsh word-splitting bug and did not replay additional events; rerunning with newline-safe ID parsing.
- 2026-06-19T13:19:24 main/working: Bulk replay using Stripe CLI to new endpoint completed: live API returned 13 delivery_success=false event ids; stripe events resend --webhook-endpoint we_1Tk6yVRMJDJBjoQzb0xTew57 succeeded for all 13 and failed for 0.
## Verification

- No verification recorded yet.
- 2026-06-19T13:18:39: Post-rotation smoke: production health 200; Fly runtime STRIPE_WEBHOOK_SECRET and V2_STRIPE_WEBHOOK_SECRET now both set to same new whsec digest; stripe events resend evt_1ThvKgRMJDJBjoQzoh4ZOTIo to new endpoint succeeded and production Mongo created stripe_webhook_events row with status=received.
- 2026-06-19T13:21:27: Final production verification: Stripe has new enabled endpoint we_1Tk6yVRMJDJBjoQzb0xTew57 and old endpoint we_1TglsaRMJDJBjoQzN6Y50g9W disabled; Fly machine version 104 started with 1/1 health check passing; GET https://api.academy.courtmastr.com/api/v2/healthz returned 200; production stripe_webhook_events total=13 with processed=13, received/processing/failed/quarantined all 0 after replay.
## Reusable Lessons

- None recorded yet.
