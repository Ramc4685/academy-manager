# fix(billing): stop swallowing Stripe checkout-creation failures in SendInvoice

PR: #441

## What changed

`SendInvoice` used to catch any Stripe checkout-creation exception, log at
WARNING, set `checkout_url=None`, and **still** send the parent an invoice email
recorded as `delivery_status="sent"` — an email whose only instruction was
"Please contact the academy to arrange payment". The connected-account-blocked
path (repo not configured, or account not charge-ready with platform fallback
off) produced the identical dead-end email. A broken payment setup looked like a
successful send. This is the mechanism behind "only emails went out" during the
August outage.

Now, when a pay link is **attempted and fails**:

- A `payment_attempts` row is recorded with `status="failed"` and a distinct
  `failure_code` — `checkout_creation_failed`, `connected_account_not_ready`, or
  `connected_accounts_not_configured`. This is the same telemetry axis
  `ChargeInvoiceViaAutopay` already writes, so existing admin billing
  health/reports read models surface it with no new infrastructure. The attempt
  key is idempotent per invoice/period/amount/failure-code, so repeated sends
  that fail the same way collapse onto one row.
- The failure logs at ERROR (with the idempotency key, which is itself part of
  the Stripe parameter-mismatch failure mode) instead of WARNING.
- The parent-facing invoice email is **not sent**, and delivery is recorded as
  `delivery_failed` rather than `sent`.
- `SendInvoiceResult` carries a new `checkout_failure_code`, surfaced to admins
  on `POST /v2/admin/billing/invoices/{id}/send` as `checkout_failure_code`
  (additive field on `SendInvoiceResponse`).
- The parent "Pay now" path still returns **409** but now raises
  `Billing.InvoicePayLinkUnavailable` instead of a bare `ValueError`, so the
  frontend payment-error mapper renders a real explanation.

Deliberately unchanged: an academy with **no Stripe wiring at all**, and
invoices that are simply not payable (zero balance / paid / void), still send
the normal email — including the "contact the academy to arrange payment" copy.
Only genuine errors and blocks are suppressed. On the parent-initiated path
(`email=None`) a checkout failure leaves the delivery axis untouched, so a
parent clicking "Pay now" cannot flip an already-delivered invoice to
`delivery_failed`.

Billing invariants preserved: financial status is still never changed by
`SendInvoice`; the connected-account posture still fails closed (including when
the billing-settings lookup raises); checkout idempotency keys are unchanged;
failure telemetry is best-effort and can never break a send.

Alerting/paging infrastructure is explicitly out of scope — that is issue #428.

Closes #426.

## Deploy notes

- Backend-only behavior change plus one additive frontend error-message
  mapping. No migration, no config, no new environment variables.
- No new collections: failures land in the existing `payment_attempts`
  collection, whose schema validator already accepts these fields (`status` is
  a free-form string).
- Expect `payment_attempts` rows with `status="failed"` and the new
  `failure_code` values to appear if any academy's Stripe Connect account is
  not charge-ready. These count toward the admin dashboard's failed-payment
  count — that visibility is the point of the change.
- Operational signal to watch after deploy: log lines matching
  `send_invoice: stripe checkout creation FAILED` and
  `send_invoice: SUPPRESSED parent invoice email`.

## Risk / rollback

- **Risk:** invoices for an academy with a broken Stripe setup will now stop
  emailing parents entirely rather than sending a pay-link-less email. That is
  intended, but it means a misconfigured academy sends no invoice notifications
  until its Connect account is fixed. Those invoices show `delivery_failed` in
  the admin list and can be re-sent once the setup is repaired.
- **Risk:** the admin "Send" response gained a field and the parent 409 gained
  an error code. Both are additive; existing clients ignore them.
- **Rollback:** revert the commit. No data migration to undo; any
  `payment_attempts` rows written by this change are inert historical records.

Verified: `pytest v2/tests` — 2731 passed; `ruff check v2` and
`ruff format --check v2` clean.
