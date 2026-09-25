# Stripe direct charges for connected academies

Owner decision 2026-09-25: the platform Stripe account is CourtMastr. The house
academy (BLNO, `HOUSE_ACADEMY_ID`) charges on the platform account with no
`Stripe-Account` header. Every other academy connects its own Stripe account
and is charged with **direct charges** on that account.

## Connected account creation (`RealStripeGateway.create_connected_account`)

`POST /v2/core/accounts` (Accounts v2, same API family as before):

| Field | Value | Why |
| --- | --- | --- |
| `dashboard` | `full` | Academy manages refunds and disputes in its own Stripe Dashboard. |
| `defaults.responsibilities.fees_collector` | `stripe` | Stripe takes processing fees from the connected account; the platform pays no Stripe fee. |
| `defaults.responsibilities.losses_collector` | `stripe` | Stripe, not the platform, is liable for negative balances (refunds, disputes). |
| `configuration.merchant.capabilities.card_payments` | requested | Card charges. |
| `configuration.merchant.capabilities.ach_debit_payments` | requested | ACH debit; v2 name of the v1 capability `us_bank_account_ach_payments`. |
| `configuration.recipient` | not sent | `stripe_transfers` is only needed for destination or separate charges. |

## What the Stripe docs say (checked 2026-09-25)

- https://docs.stripe.com/connect/accounts-v2/connected-account-configuration
  - `fees_collector`: `stripe` means Stripe collects payment fees directly from the
    connected account. `application` means the platform collects the fees and pays Stripe.
  - `losses_collector`: `stripe` means Stripe is liable for the connected account's
    negative balances. If `losses_collector` is `application`, `fees_collector`
    must also be `application`.
  - Responsibilities are set when the merchant configuration is added and **cannot
    be updated later**.
  - Application fees: when Stripe collects fees, Stripe deducts its processing fee
    and the application fee from the payment. Set `application_fee_amount` to the
    platform's fee only (not Stripe's fee).
- https://docs.stripe.com/api/v2/core/accounts/create
  - `dashboard` enum: `express`, `full`, `none`.
  - Error `account_controller_express_dash_without_application_losses_or_fees`:
    "If `dashboard` is `express`, `fees_collector` must be `application` and
    `losses_collector` must be `application`." So Stripe-owned fees and losses
    need `full` or `none`. We use `full`.
  - Merchant capability names include `card_payments` and `ach_debit_payments`.
    Recipient `stripe_balance.stripe_transfers` "enables this Account to receive
    /v1/transfers".
- https://docs.stripe.com/connect/accounts-v2
  - The recipient configuration's `stripe_transfers` "is required to use indirect
    charges". Direct charges do not need it.
- https://docs.stripe.com/connect/direct-charges
  - Stripe recommends direct charges for connected accounts with the full Dashboard.
  - A direct charge uses the `Stripe-Account` header. `application_fee_amount` must be
    positive and less than the charge. Stripe charges no extra fee on the application fee.
  - PaymentIntents, Charges and Customers live on the connected account, not the platform.
  - Refunds are created with the `Stripe-Account` header. Application fees are **not**
    refunded automatically. Pass `refund_application_fee=true` (a partial refund returns
    a proportional share), or the connected account absorbs the fee.

## Readiness

`ConnectedAccount.is_ready_for_charges()` requires `status == "active"`,
`charges_enabled`, no owner disconnect, and a `card_payments` capability that is
either `active` or not recorded. A missing entry covers rows from before
capabilities were tracked and rows last written by a `capability.*` event for
another capability. The `transfers` (v1) / `stripe_transfers` (v2) capability is
never required.

## Accounts created before this change

Accounts created earlier (express dashboard, `application` fees and losses, and
`stripe_transfers` requested) keep those responsibilities. Stripe does not allow
changing them. They still pass readiness. When they are charged directly,
Stripe bills processing fees to the platform (fees_collector `application`) and
the platform stays liable for losses. Before charging one of those accounts
directly, check with read-only calls:
`stripe accounts retrieve acct_... ` or `GET /v2/core/accounts/acct_...?include=defaults`.
If one exists, the owner must decide whether to re-onboard it as a new account.

`create_connected_account` still uses the idempotency key
`connect-account:{academy_id}`. If a create call for an academy ran with the old
body in the 24 hours before deploy and is retried with the new body, Stripe
returns `409 idempotency_error`. It will not create a duplicate account.

## Checkout, autopay setup and autopay (charge paths)

`ChargeRoute` (`domain/charge_route.py`) decides the account for every charge:

| Route | Stripe calls | Idempotency key |
| --- | --- | --- |
| house academy (platform) | no `stripe_account`, no fee, same kwargs as before | unchanged |
| any other academy (connected) | `stripe_account=<acct>`, no `on_behalf_of` or `transfer_data`; `application_fee_amount` from `application_fee_bps` (floored), left out when 0 | `<key>[:fee<N>]:acct:<acct>` |

This covers registration checkout (`StartCheckout`), autopay setup checkout
(`StartSubscriptionCheckout`, `EnrollChildInSessionType`), invoice pay links and
bundled balance links (`SendInvoice`), the parent balance checkout
(`composition/parent.py`) and off-session autopay (`ChargeInvoiceViaAutopay`).
The parent return poll (`GetCheckoutStatus`), superseded-checkout expiry, and
webhook object hydration and autopay-setup completion read the session on the
same account. Webhooks use the event's top-level `account`.

### Where a parent's customer and card are recorded

`parent_billing_customers` stays one row per `(academy_id, parent_id)`. The new
`stripe_account_id` field (migration `0204`, optional string) names the account
that holds `stripe_customer_id` and every saved payment method. If the field is
missing, the account is the platform. That covers every existing row and every
house-academy row.

- A write for a different account than the stored one replaces the customer and
  drops the old account's saved payment methods. A platform card is never
  charged on a connected account, and the reverse is also blocked.
- `promote_payment_method_to_default` only changes the row stored for the same
  account.

### Autopay

- House: unchanged. The platform `Customer.search` finds the saved card, and the
  PaymentIntent is created on the platform.
- Connected: charges the customer and card **stored** for the academy's account
  (`get_saved_payment_method`). It never runs a platform search. If no card is
  stored for that account, it raises `no_saved_payment_method` and Stripe is not
  called.

### Existing non-house parents

Before this change, a non-house academy's parents saved cards as platform
customers (destination charges). Those rows have no `stripe_account_id`, so the
connected route does not find them, and autopay for those parents fails with
`no_saved_payment_method` until they set up autopay again, on the academy's
account. Before deploying, count them with a read-only query:
`db.parent_billing_customers.countDocuments({academy_id: {$ne: "<HOUSE_ACADEMY_ID>"}, stripe_customer_id: {$type: "string"}, stripe_account_id: {$exists: false}})`.

## Webhooks from connected accounts

A direct charge's events (`checkout.session.*`, `payment_intent.*`,
`setup_intent.succeeded`, `charge.*`) happen ON the academy's connected
account. Stripe only delivers them to an endpoint registered for
**Connect** events (events on connected accounts), signed with that endpoint's
own secret (`STRIPE_CONNECT_WEBHOOK_SECRET`). The gateway already tries both
secrets. Before the first non-house academy takes a payment, confirm in the
Stripe Dashboard that a Connect endpoint exists for `/webhooks/stripe` and
subscribes to the same payment event types as the platform endpoint.

How an event is attributed (`HandleWebhookEvent._ingest_academy_id`):

1. The event has a top-level `account`: its owner is looked up across every
   academy by `MongoConnectedAccountDirectory` (read-only, platform-scoped,
   uses the unique `academy_connected_accounts_stripe_account` index from
   migration 0139, so no new migration). The event is stored under the owner.
   - If `metadata.academy_id` names a different academy, the event is
     quarantined under the owner with `quarantine_reason =
     connect_account_metadata_conflict`. Metadata never overrides the account.
   - If no academy owns the account, the event is stored under the boot
     academy and the processing guard quarantines it ("unknown connected
     account").
2. No `account` (the house academy, and older destination charges):
   `metadata.academy_id`, as before.

While processing, the Stripe objects are read back on the event's account
(`stripe_account=event.account`). Platform events keep the account-less calls.

Find conflicting events:

```js
db.stripe_webhook_events.find(
  { quarantine_reason: "connect_account_metadata_conflict" },
  { event_id: 1, event_type: 1, academy_id: 1, stripe_account: 1, error_message: 1 }
)
```

## Refunds, dashboard refunds and disputes

### Which account a refund is created on

A payment records the Stripe account its charge lives on in
`stripe_account_id` (`ledger_payments`, and `payments` for historical rows).
The webhook that confirms the charge writes it (Connect event `account`), as do
the synchronous autopay path and reconciliation of PaymentIntents found on the
connected account. Absent means the platform account.

- Direct charge (`stripe_account_id` set): the refund is created ON that
  account (`Stripe-Account` header). The academy's balance funds it. There is
  no transfer to reverse, and `refund_application_fee` is left off (Stripe's
  default), so the platform keeps its application fee on a refunded direct
  charge. This is the default until the owner decides otherwise.
- House academy, and legacy destination charges made before direct charges:
  no account, so the refund request is exactly what it was before. The #969
  logic still adds `reverse_transfer` and `refund_application_fee` when the
  PaymentIntent carries `transfer_data` (a legacy destination charge).

### Refunds made in the academy's Stripe Dashboard

They arrive as a Connect `charge.refunded` and go through the same handler as
platform refunds. The handler is idempotent on the cumulative
`amount_refunded`, so the echo of an in-app refund does nothing. An event
whose `account` contradicts the payment's recorded account is quarantined.

### Disputes (`charge.dispute.created`, `charge.dispute.closed`)

- Recorded in `payment_disputes` (migration 0205), one row per dispute. A late
  `created` never reopens a closed dispute.
- Mirrored onto the payment row as `dispute_id`, `dispute_status`,
  `dispute_reason`, `dispute_amount_cents`, `dispute_outcome` and
  `disputed_at`. Money fields (status, refunded, allocations) are never
  touched, and no platform-side adjustment is created.
- Shown on Billing Health (`disputes` in `/admin/billing/connect-readiness`;
  a `payments_disputed` attention reason while any are open).
- The academy owner is e-mailed once per (dispute, opened|closed) through the
  outbox event `Billing.PaymentDisputeNoticeRequested`. Its `event_id` is
  deterministic, so replays do not re-send.

### Before deploy

- Apply migration 0205 by hand (migrations do not run on boot in prod).
- The Connect webhook endpoint must subscribe to `charge.refunded`,
  `charge.dispute.created` and `charge.dispute.closed`, and the platform
  endpoint must subscribe to the two dispute events for the house academy.
  Check in the Stripe Dashboard (read-only).
- In `multi_academy` mode a platform dispute event has no
  `metadata.academy_id` and no `account`, so it is quarantined as
  unattributed. House disputes are only recorded automatically in
  `single_academy` mode.
