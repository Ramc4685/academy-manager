# Autopay opt-in at payment time — design

**Date:** 2026-07-05
**Status:** Approved by RamC (this session)
**Owner:** billing context (backend/v2) + parent frontend

## Goal

Every one-time invoice payment doubles as an autopay enrollment by default. A
small checkbox ("Enroll in autopay for future invoices") sits below every Pay
button in the parent app, **checked by default**. Leaving it checked saves the
payment method used for the payment and enrolls the enrollment(s) in autopay.
Unchecking pays one time only, exactly like today. Parents already on autopay
never see the checkbox.

## Why this shape

- The checkbox lives in **our UI**, not Stripe's. Stripe hosted Checkout has no
  custom checkbox field (`custom_fields` supports only dropdown/numeric/text/
  label), so the decision is captured before redirect.
- Stripe natively supports "pay + save for later" in one session via
  `payment_intent_data.setup_future_usage = "off_session"`. One payment, one
  redirect, no post-payment interstitial. Stripe renders its standard
  "details will be saved for future payments" notice on the payment page,
  which provides the compliance-grade consent language.
- The activation machinery (consent capture, default payment method,
  `mark_autopay_active_from_setup`, webhook + checkout-status-poll dual path)
  already exists for the dedicated autopay-setup flow and is reused, fed from
  a payment intent instead of a setup intent.

## UX

- **Where:** parent invoice detail Pay button and the pay-all-open-invoices
  button (Payments page). Both get the checkbox directly below, label:
  "Enroll in autopay for future invoices", default checked.
- **Hidden when:** the related enrollment's `autopay_enrollment_status` is
  `active`, `setup_started`, or `paused` (nothing to offer). For pay-all, the
  checkbox is hidden only if **all** covered enrollments are in those states.
- **Re-prompt:** no memory of past declines — the checkbox appears (checked)
  on every eligible payment.
- **After success:** existing payment-success handling; if opted in, the
  Payments page will show autopay active once activation lands (webhook or
  status poll — both complete it).

## API changes (parent BFF)

- `StartInvoicePaymentRequest` and `StartBalancePaymentRequest`
  (backend/v2/interfaces/parent/views.py) gain `enroll_autopay: bool = False`.
  Frontend sends `true` when the checkbox is checked. Server default `false`
  keeps old clients one-time-only (fail-safe).
- `ParentInvoiceView` gains `enrollment_id: str | None` so the frontend can
  match invoices to enrollments for checkbox visibility.

## Backend flow

1. **Session creation** — `StartInvoicePayment` / `StartBalancePayment` use
   cases pass `enroll_autopay` to the gateway. When true,
   `create_invoice_checkout_session` adds:
   - `payment_intent_data.setup_future_usage = "off_session"`
   - `customer_creation = "always"` (payment method must attach to a customer)
   - metadata: `autopay_optin = "true"`, `enrollment_ids = "<id1,id2,…>"`
     (distinct enrollment_ids of the invoices being paid; respect Stripe's
     500-char metadata value limit — log + truncate-with-flag if exceeded),
     plus existing invoice metadata.
   Connected-account routing and the `allow_platform_charge_fallback` behavior
   are unchanged — the flag composes with both platform and destination-charge
   modes.
2. **Completion (both paths must handle it, mirroring autopay setup):**
   - `checkout.session.completed` webhook: when session `mode == "payment"`
     and metadata `autopay_optin == "true"`, run new
     `CompleteAutopaySetup.execute_from_payment_checkout(session)`:
     retrieve the payment intent → `payment_method` + `customer`; set as the
     parent's default payment method; capture autopay consent
     (source `invoice_payment_optin`, records checkbox consent version and
     the Stripe saved-payment-notice version); for each enrollment id in
     metadata, `mark_autopay_active_from_setup` (already idempotent and
     walks any legal status to `active`).
   - `GetCheckoutStatus` poll: same branch synchronously, so activation
     doesn't wait for the webhook (parity with the setup-session flow).
   - Payment failure/abandonment: no activation (metadata flag is inert
     unless the session completes). Unchecked box → none of this metadata is
     set; flow is byte-identical to today.
3. **ACH:** `us_bank_account` payments work with `setup_future_usage`; the
   saved bank account becomes the autopay method. Settlement delay affects
   payment confirmation timing only; enrollment activates when the session
   completes. Existing micro-deposit verification states remain for the
   dedicated setup flow and are untouched.

## Edge cases

- **Pay-all across children:** one saved payment method; ALL covered
  enrollments flip to autopay (approved decision).
- **Invoice without enrollment_id:** excluded from `enrollment_ids` metadata;
  payment proceeds; nothing to enroll for that invoice.
- **Already active + parent still opted in** (race, stale UI): activation is
  a no-op (idempotent walk); default payment method updates to the newly used
  method — acceptable and arguably desired.
- **`student_billing_enrollments` doc missing** (legacy data): activation
  currently returns False → surfaced error. The separate backfill-migration
  task covers the durable fix; this feature must not crash the payment
  result — log + do not fail the checkout-status response if activation
  fails (payment already succeeded; activation can be retried by the
  webhook worker).

## Testing

- Unit: use cases pass `enroll_autopay` through; gateway payload includes/
  omits `setup_future_usage` + metadata by flag; metadata enrollment_ids
  dedup/truncation.
- Application: `execute_from_payment_checkout` — happy path, multi-enrollment,
  missing enrollment doc (no crash), idempotent replay.
- Interface: webhook + checkout-status branches for `autopay_optin` sessions;
  old clients (no `enroll_autopay` field) unchanged.
- Frontend: checkbox default-checked, hidden when enrolled, request body
  carries the flag; component test for pay-all visibility rule.

## Out of scope

- ACH discount incentives (paused 11-slice project).
- Emailed invoice pay links (SendInvoice): those sessions stay one-time-only
  for now — the email flow has no UI to host the checkbox; revisit later.
- Admin toggle for `allow_platform_charge_fallback` (separate task).
