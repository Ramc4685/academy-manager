# fix(billing): stop swallowing Stripe checkout-creation failures

PR: #441

## What changed

When a Stripe pay link is attempted and fails — the gateway raises, or the academy's Connect account exists but cannot take charges — `SendInvoice` and the parent portal's "Pay balance" now log at ERROR, record one `checkout_mint_failed` row per invoice on `payment_attempts`, and suppress the parent email that used to go out saying "contact the academy to arrange payment". Admins get an accurate reason on the send response and in the student billing panel; the parent 409 now carries `Billing.InvoicePayLinkUnavailable`.

An academy with **no Connect account at all** is explicitly not a failure — it still sends its normal invoice email, since the platform Stripe client is wired for every tenant and cannot be used to detect this.

## Deploy notes

No migration, config, or new env vars. Mint failures reuse the existing `payment_attempts` collection under a distinct status that the dunning sweep, billing-health failed-payments list, and revenue reports all filter out, so no existing counter or retry surface changes. Watch for `send_invoice: stripe checkout creation FAILED` and `SUPPRESSED parent invoice email` after deploy.

## Risk / rollback

Main risk: an academy whose Connect account is broken now sends no invoice emails at all until it is fixed — intended, and visible as `delivery_failed` in the admin invoice list. Revert the commit to roll back; the `checkout_mint_failed` rows left behind are inert and already excluded from every charge-outcome reader.
