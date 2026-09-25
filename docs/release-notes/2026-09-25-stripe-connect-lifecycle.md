# Stripe Connect: sticky disconnect, reconnect resync, destination refunds

PR: #969

## What changed

- **Disconnect now sticks (audit X6).** "Disconnect Stripe" is still local only (the Stripe account is not rejected or deauthorized), but it now stamps `disconnected_at` on the academy's `academy_connected_accounts` row. Connect webhooks (`account.updated`, `capability.*`) no longer change a disconnected row: the write is conditional on the marker being unset, in the same atomic update. Before this change, the next `account.updated` with `charges_enabled` silently re-activated the account and charges resumed. `is_ready_for_charges` also refuses a disconnected row.
- **Reconnect resets and resyncs (audit X9).** Starting Connect onboarding again on a disconnected or disabled account clears the marker and re-reads the account from Stripe (`Account.retrieve`). The status becomes active, restricted or disabled from Stripe's live flags. If that read fails, the status resets to `pending` (not charge-ready) and the next webhook brings it current. The same Stripe account is reused, and no new account is created.
- **Refunds of destination charges (audit X7).** When the refunded PaymentIntent has `transfer_data.destination`, the refund now sends `reverse_transfer=true`, which pulls the money back from the academy's connected account. When the PaymentIntent has an application fee, it also sends `refund_application_fee=true`. Both are pro-rata on partial refunds. The owner chose this policy on 2026-09-25. Platform charges (today's fallback path) are refunded exactly as before. The flags come from the PaymentIntent, which cannot change once paid, so a retry with the same idempotency key sends identical parameters.
- **`capability.*` webhook crash fixed.** The webhook's Connect resolver shim lacked `get_by_stripe_account_id`, so every `capability.*` event without `charges_enabled` raised `AttributeError` in production wiring. It now keeps the previous status, as intended.

## Deploy notes

- No migration and no new index. `disconnected_at` is a new optional field. Missing reads as "not disconnected", so existing rows behave as before.
- An account disconnected **before** this deploy has no marker, so a webhook can still re-activate it. If BLNO's row is currently `disabled` because of a disconnect, the owner should press Connect again after the deploy (this runs the new resync), or disconnect again to set the marker.
- One extra Stripe read per refund (`PaymentIntent.retrieve`) and per reconnect (`Account.retrieve`). No new secrets or settings.

## Risk / rollback

- Low risk today. BLNO charges route to the platform account via the fallback flag, so no destination charges exist yet and refunds keep their current parameters. The refund change goes live only once BLNO's connected account is charge-ready.
- If the PaymentIntent read fails, the refund fails the same way a failed `Refund.create` does today. The refund is never sent without the Connect flags.
- Rollback: revert this PR. The stray `disconnected_at` values are harmless to the old code, which ignores unknown fields on read (pydantic default `extra="ignore"`).
