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
