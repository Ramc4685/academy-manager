# staging platform charge fallback toggle

## Current State

Status: verified in staging — awaiting production deploy approval

## Problem

The platform's Stripe Connect application is under Stripe review (~48h ETA, error
`account_create_activation_required` on POST /v2/core/accounts in production).
Until approved, no academy can get a charge-ready connected account, and all three
payment paths (checkout, invoice pay link, autopay) refuse to charge.

A temporary per-academy toggle `BillingSettings.allow_platform_charge_fallback`
(default false) lets these paths fall back to a direct platform-account charge
(`connected_account_id=None`) instead of refusing, while the review is pending.

## Changed Files

- backend/v2/contexts/billing/domain/billing_settings.py (new flag)
- backend/v2/contexts/billing/application/use_cases/start_checkout.py
- backend/v2/contexts/billing/application/use_cases/charge_invoice_via_autopay.py
- backend/v2/contexts/billing/application/use_cases/send_invoice.py
- backend/v2/composition/parent.py, backend/v2/composition/admin.py (wiring)
- 9 new unit tests across the three use-case test files

## Verification

Environment: Docker saas-staging stack rebuilt from working tree (branch
fix/blno-launch-readiness), BLNO seeded via seed_blno_staging.py. Connected
account for `blno` present but not charge-ready (`charges_enabled: false`) —
exactly the pending-review posture. Endpoint exercised: POST
/api/v2/admin/billing/invoices/{id}/send (SendInvoice use case) with invoice
`inv-from-pay_blno_prasanthboddapati0805_abhishta_boddapati_jun2026`
(balance 6000 cents).

1. FLAG OFF (no billing_settings doc): response `checkout_url: null`; backend log
   `send_invoice: refusing pay link ... connected account not ready`. PASS —
   pre-change behavior preserved.
2. FLAG ON (`allow_platform_charge_fallback: true` upserted for blno): response
   returned a real test-mode checkout URL (`cs_test_a1fBl9...`); backend log
   `send_invoice: connected account not ready — falling back to PLATFORM charge
   (allow_platform_charge_fallback=on)`. Session retrieved from Stripe ON THE
   PLATFORM ACCOUNT with no Stripe-Account header (a connected-account session
   would 404 there): livemode=false, amount_total=6000, mode=payment,
   status=open, payment_intent=null (deferred; no on_behalf_of/transfer_data
   params sent), metadata carries academy_id=blno + invoice_id. PASS.
3. FLAG OFF again: response `checkout_url: null`; refusal log returned. PASS —
   toggle is cleanly reversible.

Also: full backend v2 suite 2089 passed / 0 failed on this working tree;
security review (read-only agent) found no issues (fail-closed default,
tenant-scoped flag, idempotency keys unchanged, P2 autopay gate still enforced
before the fallback).

## Operator Runbook

Enable for an academy (production Mongo):

    db.billing_settings.updateOne(
      { academy_id: "acad_blno_badminton" },
      { $set: { allow_platform_charge_fallback: true } },
      { upsert: true }
    )

Disable (once Stripe approves the Connect platform application and the academy's
connected account is charge-ready): same command with `false`. Payments taken
during the fallback window settle to the platform Stripe account and are
identifiable in the ledger by their payment intents having no connected-account
routing.

## Log

- 2026-07-04: Implementation (Sonnet subagent), full-suite run (Haiku subagent),
  security review (Sonnet security-reviewer). Staging verification run from the
  main session after a subagent delegation loop was stopped.
- 2026-07-04: Staging quirks encountered and resolved: host mongod occupies
  27017 so staging Mongo was bound to 127.0.0.1:27018 via a temporary compose
  override (scratchpad-only, not in repo); a stale `staging-mongo-fwd` container
  from the stopped agent chain was removed; the mongo container had lost its
  network attachment after a failed port bind and was force-recreated.

## Reusable Lessons

- `scripts/dev/saas_staging.sh` derives the Mongo URL from `docker compose port
  mongo 27017`, which breaks when host port 27017 is occupied (local mongod).
  Workaround: run the seed with `SAAS_STAGING_MONGO_URL=mongodb://127.0.0.1:27018`
  after overriding the port mapping, or run the seed inside the compose network.
- Retrieving a Checkout Session with the platform key and no Stripe-Account
  header is a cheap proof of which account a session was created on.
