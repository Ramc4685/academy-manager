# Apple Pay / Google Pay + Text-to-Pay — Requirements

Date: 2026-07-06 · Roadmap item 7 of 9 · [Index](2026-07-06-00-roadmap-index.md)
**Flagged in the competitive analysis as the cheapest, highest-leverage win in the
whole roadmap — genuine market white space, nearly free given our Stripe stack.**

## Problem

The billing deep-dive found no competitor in the 14 studied prominently markets
Apple Pay/Google Pay support, and none offers text-to-pay (an SMS/email-delivered
secure payment link). Wallets ride along invisibly as "we accept cards" messaging
at best (e.g., TeamUp draws an explicit customer complaint for *missing* Apple
Pay entirely). Text-to-pay is mature and common in adjacent industries (healthcare
billing via Curogram/Gravity Payments/Podium) but has not crossed into the class/
academy-management category. Because we already use Stripe Checkout/Elements,
wallet support is largely a configuration and UI-marketing exercise, not a build —
this is the single lowest-effort, highest-differentiation item in the roadmap.

## Current State (codebase evidence)

- `backend/v2/contexts/billing/...` — Stripe integration uses PaymentIntent and
  SetupIntent flows via Stripe Checkout Sessions
  (`create_invoice_checkout_session`, per the autopay/ACH requirements doc from
  2026-06-30). Stripe Checkout natively supports Apple Pay/Google Pay when the
  relevant payment method types are enabled and domain verification is complete —
  this is largely a Stripe Dashboard/API-parameter configuration change plus
  frontend messaging, not new payment logic.
- No text-to-pay flow exists — there is no mechanism to generate a payment link
  and deliver it via SMS or email outside of the existing email-based invoice/
  campaign system (`MessageCampaign`, `MessageDelivery`).
- No SMS infrastructure exists at all today (confirmed gap from the codebase
  inventory) — text-to-pay's SMS delivery channel depends on at least a minimal
  SMS-sending capability, even if the full SMS/push notification platform (a
  separate, larger roadmap item not included in this set of 9) is not built.

## Goals

- Enable Apple Pay and Google Pay as payment options everywhere parents check out
  or set up autopay (invoice checkout, autopay setup, billing portal), and make
  their availability visible/marketed in the parent-facing UI (a wallet button,
  not just an unlabeled "card" field that happens to support it).
- Let an admin (or an automated dunning notification) generate a one-time payment
  link for a specific invoice/balance and deliver it via SMS and/or email, so a
  parent can pay directly from a text message without logging into the portal.

## Non-Goals

- Not building the full SMS/push notification platform (transactional +
  marketing messaging infrastructure) in this slice — only the minimal SMS-send
  capability needed to deliver a text-to-pay link. If a broader SMS platform is
  built later, this feature should consume it rather than maintaining its own
  separate SMS integration.
- Not adding new payment methods beyond Apple Pay/Google Pay (e.g., no Cash App
  Pay, no Klarna/BNPL) in this slice.

## Requirements

### R1. Wallet enablement in Checkout
- Verify/enable Apple Pay and Google Pay payment method types on all existing
  Stripe Checkout Session creation paths: invoice payment, autopay setup
  (SetupIntent), and any billing-portal-initiated payment.
- Complete Stripe's domain verification requirement for Apple Pay on the
  production domain(s) (and any custom academy subdomains, if wallets should work
  there too — confirm Stripe's domain-verification scope for multi-tenant
  subdomains before assuming it "just works" per tenant).

### R2. Wallet visibility/marketing in UI
- Parent-facing checkout and autopay-setup screens show a wallet button (Apple
  Pay/Google Pay) prominently, not just as a side effect of the card field —
  this is the "prominently marketed" gap the competitive research identified as
  unaddressed industry-wide.
- Parent portal/marketing copy explicitly mentions wallet support as a
  convenience feature (this is a positioning opportunity, not just a technical
  toggle).

### R3. Text-to-pay link generation
- Admin (or an automated dunning notification, once wired) can generate a
  time-limited, single-invoice (or family-statement, if roadmap item 3 has
  shipped) Stripe-hosted payment link.
- Link generation reuses existing invoice Checkout Session creation, just
  surfaced as a shareable URL rather than a redirect from an in-app button.

### R4. Delivery channel
- Deliver the generated link via SMS (requires minimal SMS-send integration —
  see Data Model/Dependencies) and/or email (reuse existing
  `MessageCampaign`/`MessageDelivery` infrastructure, which is already email-only
  and can send a link today without new infrastructure).
- Track delivery status per link (sent, delivered if the SMS provider reports it,
  clicked, paid) so admin can see whether a text-to-pay nudge worked.

### R5. Link security
- Payment links are single-use or time-limited (do not remain valid indefinitely —
  a lost/forwarded text should not be a standing payment backdoor), and are scoped
  to exactly the invoice/balance they were generated for (cannot be manipulated to
  pay a different amount or a different family's balance).

## Data Model Changes

### New `payment_links`
```text
link_id
academy_id
invoice_id (or family_id, if generated against a consolidated statement)
stripe_checkout_session_id
delivery_channel: "sms" | "email" | "both"
expires_at
status: "active" | "expired" | "used" | "revoked"
created_by: admin_user_id | "system_dunning"
```

### New `payment_link_deliveries`
```text
delivery_id
link_id
channel: "sms" | "email"
recipient: string   # phone or email, minimally logged
sent_at
delivered_at: datetime | null   # if provider reports delivery status
clicked_at: datetime | null
```

## Dependencies

- SMS delivery (R4) requires at minimum a transactional SMS-send integration
  (e.g., Twilio, matching what several competitors already use — Jackrabbit's
  Twilio integration is a reasonable reference point). This is a small, scoped
  dependency (send-only, one message type) — not the full SMS/push platform.
  Email delivery can ship first as a fast-follow-free alternative if SMS
  integration takes longer to stand up.
- If roadmap item 3 (consolidated family statement) has shipped, text-to-pay
  links can target a family balance instead of a single invoice — otherwise,
  scope to single-invoice links for the first release.

## Open Decisions

1. Is the SMS-send dependency (Twilio or equivalent) scoped as part of this item,
   or is email-only the first release with SMS as an explicit fast-follow?
2. Link expiry window: fixed (e.g., 7 days) or configurable per academy?
3. Does a used/expired link auto-regenerate a fresh one on request, or does admin
   have to manually create a new one each time?
4. Should text-to-pay links be automatically generated and sent as part of the
   dunning notification flow (roadmap item 6) once both exist, or remain a manual
   admin action for this first release?

## Acceptance Criteria / Test Cases

- A parent checking out sees an Apple Pay or Google Pay button (on a supported
  device/browser) alongside card entry, not only a generic card field.
- Completing payment via Apple Pay/Google Pay in Checkout correctly creates the
  PaymentIntent, allocates to the invoice, and closes it exactly like a card
  payment does today (no separate/parallel payment path).
- Admin generates a text-to-pay link for a specific invoice; the link opens a
  Stripe-hosted checkout scoped to exactly that invoice's balance.
- A text-to-pay link cannot be reused after successful payment, and expires per
  the configured window if unused.
- Delivery tracking shows sent/delivered/clicked/paid status for a generated link
  (to the extent each channel's provider reports it).
