# Cutover Runbook — Wave 2: Parent Checkout

**Tickets:** W2-22.
**Owners:** RamC + on-call observer.
**Rollback:** Single edge flag flip + Stripe webhook endpoint swap.

## Pre-flight

- [ ] Wave 1B holds for 7 days in production.
- [ ] Stripe webhook fixture replay green on all 10 scenarios.
- [ ] Side-by-side contract diff documented under `docs/contract-deltas/parent-payments.md`.
- [ ] Stripe webhook endpoint configured in the Stripe dashboard to point at `/api/v2/parent/webhooks/stripe` (signature secret in env).
- [ ] Per-tenant `default_academy_id` confirmed in env.
- [ ] Outbox dispatcher healthy (no dead-letter accumulation in past 7d).
- [ ] Idempotency store TTL verified working.
- [ ] Parent route group Lighthouse baseline committed; size budget set per W2-baseline procedure (clone of W1A-01).

## Stripe webhook handoff

**Critical:** the legacy webhook stays armed in parallel until the v2 webhook
has processed at least one of each canonical event type successfully.

1. In Stripe dashboard, *add* the v2 endpoint (do not remove the legacy one).
2. Soak 48h. Both endpoints receive every event. Idempotency on Stripe event
   id (shared via `stripe_webhook_events` collection that both code paths
   read/write) prevents double-application.
3. Verify the v2 event audit shows every recent Stripe event id with
   `outcome=succeeded`.
4. **Then** remove the legacy webhook endpoint from Stripe dashboard.

## Canary — 10% parent traffic to v2

```bash
cd edge
wrangler deploy --gradual 10 --env prod  # with FLAG_PARENT_ALL=v2 on the canary version
```

**Soak: 1 hour.** Watch:

- `/api/v2/parent/*` p95 < 300 ms (reads), < 800 ms (POST).
- 0 errors of type `Billing.InvalidWebhookSignature` (signature mismatch is fatal).
- 0 `Coaching.*` regressions (coach unaffected).
- 0 `Billing.CapacityExceeded` without a paired `Billing.PaymentRefunded` within 5 min (auto-refund must fire).

## 100% promotion

```bash
wrangler deploy --gradual 100 --env prod
```

**Soak: 48 h.** Exit gate items per [the wave sheet](tickets/wave-2-parent-checkout.md#exit-checklist).

## Rollback

```bash
wrangler secret put FLAG_PARENT_ALL --env prod   # legacy
```

Plus:
- Re-enable legacy Stripe webhook endpoint in dashboard if it had been removed.
- The legacy `billing_routes.py` webhook continues to work since legacy code is still mounted; routing simply directs Stripe to it again.

## Post-cutover

- [ ] Legacy parent pages reachable only via `/legacy/parent/*` admin-gated path.
- [ ] Legacy E2E suite green.
- [ ] Wave 3 (admin) planning may open after 7-day soak with no rollback.
