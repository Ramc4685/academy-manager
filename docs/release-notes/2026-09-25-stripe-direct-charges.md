# Stripe Connect direct charges for non-house academies

PR: #978

## What changed

- One charge-route resolver decides every card charge. The house academy (BLNO, `HOUSE_ACADEMY_ID`) charges on the platform account exactly as before. A non-house academy with a ready connected account is charged with **direct charges** on its own account (`Stripe-Account` header). Any other academy is refused.
- New connected accounts are created with the full Stripe dashboard, and Stripe is their fees and losses collector. The academy pays Stripe's fees and carries its own refunds and disputes; the platform carries none. Accounts created the old way (express, where the platform is liable) are refused direct charges. Starting onboarding on one of them replaces it with a new direct-charge account.
- Checkout, autopay setup and off-session autopay create the Stripe customer and card on the academy's account. `parent_billing_customers.stripe_account_id` records that account. The optional platform fee is sent as `application_fee_amount`.
- Connect webhooks are attributed to the academy that owns `event.account`. A conflicting `metadata.academy_id` or an unknown account is quarantined. If the owner lookup fails, the webhook returns 503 so Stripe retries.
- In-app refunds of direct charges are created on the academy's account. A refund made in the Stripe dashboard updates the invoice. Disputes (`charge.dispute.created/closed`) are recorded, shown on Billing health, and emailed to the academy owner.

## Deploy notes

- Migrations 0204 (adds the optional `stripe_account_id` to the `parent_billing_customers` validator) and 0205 (`payment_disputes` indexes) run automatically in the deploy release command (`python -m backend.v2.migrations`). They do not run on boot (`run_migrations_on_boot` is false).
- Owner, in the Stripe dashboard:
  - Add `checkout.session.*`, `payment_intent.*`, `setup_intent.succeeded`, `charge.refunded` and `charge.dispute.*` to the Connect webhook endpoint.
  - Add `charge.dispute.created/closed` to the platform endpoint.
  - Confirm that `STRIPE_CONNECT_WEBHOOK_SECRET` matches the Connect endpoint.
  - Check that the Connect settings allow Stripe-managed losses.
- No new env vars. Do not onboard a second academy until staging acceptance (slice 7) passes.

## Risk / rollback

- BLNO's paths (platform charges, platform customers, saved cards, autopay via `Customer.search`) are pinned byte-identical by contract tests. No non-house academy is live, so no production money path changes on deploy.
- Rollback: revert this PR. 0204 only relaxes the validator and 0205 only adds indexes; both are harmless to the old code.
