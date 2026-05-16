# Wave 2 — Parent Checkout

**Goal:** Parent onboarding → enrollment → Stripe checkout → webhook → confirmation email, all served from v2 for 100% of parent traffic.

**Prerequisite:** Wave 1B exit gate cleared.

**Exit gate (from plan):**
1. Parent onboarding + checkout fully on v2.
2. Stripe webhook fixture replay matches v1 outcomes for the canonical 10 scenarios.
3. Side-by-side contract comparison: v2 payment history payload matches v1 (modulo documented persona-shape deltas).
4. No double-charge, no missed enrollment confirmations across a 48h soak.

**Estimate:** 3 weeks.

---

## Backend — Billing context (full)

### W2-01 — Billing domain (Payment + Subscription aggregates, events)
- **Type:** Backend / Domain
- **Estimate:** 6h
- `contexts/billing/domain/{models,events,errors}.py`. `Payment` (id, stripe_payment_intent_id, amount, currency, status: pending|succeeded|failed|refunded, parent_id, session_id). `Subscription` aggregate. Events: `Billing.PaymentSucceeded`, `PaymentFailed`, `PaymentRefunded`, `CheckoutExpired`, `SubscriptionCancelled`. Errors: `InvalidWebhookSignature`, `PaymentNotFound`, `RefundExceedsAmount`.
- **Acceptance:** Pure unit tests on invariants; events use `Literal name/schema_version`.

### W2-02 — Stripe gateway (anti-corruption layer)
- **Type:** Backend / Infra
- **Estimate:** 6h
- `contexts/billing/infrastructure/stripe_gateway.py` — only file allowed to import `stripe`. Methods: `create_checkout_session`, `verify_webhook`, `parse_event` (returns domain events), `issue_refund`. All boundary types are domain types.
- **Acceptance:** Stripe SDK never imported outside this file (lint rule).

### W2-03 — Payment repository + Subscription repository (Mongo)
- **Type:** Backend / Infra
- **Estimate:** 4h
- Both extend `TenantScopedRepository`. Tenant-isolation tests required.

### W2-04 — Use cases: start_checkout, handle_webhook_event, issue_refund
- **Type:** Backend / Application
- **Estimate:** 10h
- `start_checkout(parent_id, session_id) -> CheckoutSession` — creates a Stripe Checkout Session, persists `Payment(status=pending)`, returns URL.
- `handle_webhook_event(payload, signature)` — verifies, parses, idempotent on Stripe event id, persists state change, writes outbox event.
- `issue_refund(payment_id, amount)` — admin path; calls Stripe gateway, persists state, emits `PaymentRefunded`.
- **Acceptance:** Each use case has happy + error tests; idempotency on Stripe event id verified.

### W2-05 — Billing migrations (payments, subscriptions, stripe_events indexes)
- **Type:** Backend / DB
- **Estimate:** 2h
- Indexes per plan §0.7. `payments`: `(academy_id, stripe_payment_intent_id)` unique, `(academy_id, parent_id, created_at)`. New collection `stripe_events`: `(stripe_event_id)` unique for raw event idempotency.

## Backend — Onboarding context

### W2-06 — Onboarding domain (Application, Waiver)
- **Type:** Backend / Domain
- **Estimate:** 5h
- Aggregates: `Application` (id, parent_id, status: started|patching|ready|completed|abandoned), `Waiver` (id, version, accepted_by, accepted_at). Errors: `ApplicationNotFound`, `WaiverNotAccepted`.

### W2-07 — Use cases: start_application, patch_application, get_status, accept_waiver
- **Type:** Backend / Application
- **Estimate:** 8h
- Mirrors legacy `onboarding_routes.py` behavior. Reads waiver versions; rejects checkout if latest not accepted.

### W2-08 — Onboarding migrations + indexes
- **Type:** Backend / DB
- **Estimate:** 1h
- `onboarding_applications`: `(academy_id, parent_id, created_at)`, `(academy_id, status)`. `waivers`: `(academy_id, version)` unique.

## Backend — Enrollment write slice + event handlers

### W2-09 — Confirm enrollment on `Billing.PaymentSucceeded`
- **Type:** Backend / Application + Event handler
- **Estimate:** 5h
- New use case `ConfirmEnrollment(parent_id, session_id, payment_id)`. Cross-context handler in `composition/event_handlers.py` reacts to `PaymentSucceeded`, calls Enrollment's `ConfirmEnrollment` via the application port. Capacity check enforced inside the aggregate; failure triggers auto-refund via Billing.
- **Acceptance:** Integration test: simulated `PaymentSucceeded` event → enrollment confirmed → audit row written.

### W2-10 — Waitlist promotion on cancellation
- **Type:** Backend / Application + Event handler
- **Estimate:** 4h
- Use case `PromoteFromWaitlist(session_id)`. Handler reacts to `Enrollment.EnrollmentCancelled` → promotes oldest waitlist entry. FIFO ordering enforced by the `(academy_id, session_id, joined_at)` index.

### W2-11 — Auto-refund on capacity failure
- **Type:** Backend / Application
- **Estimate:** 3h
- If `ConfirmEnrollment` raises `CapacityExceeded`, Billing's `auto_refund(payment_id, reason)` use case fires. Idempotent on payment id.

## Backend — Parent BFF

### W2-12 — Parent BFF routes
- **Type:** Backend / Interface
- **Estimate:** 8h
- `interfaces/parent/{onboarding_routes,payment_routes,enrollment_routes,webhook_routes}.py` + `views.py`. Persona-shaped DTOs only. Stripe webhook lives under `interfaces/parent/webhook_routes.py` (no auth header, signature-verified).

### W2-13 — Parent BFF security tests
- **Type:** Backend / Test
- **Estimate:** 4h
- Negative-coverage from security matrix: admin/coach hitting parent paths → 404.

### W2-14 — Webhook fixture replay (10 scenarios)
- **Type:** Backend / Test
- **Estimate:** 6h
- `tests/contract/test_stripe_webhook_replay.py` ingests 10 canonical Stripe event fixtures (succeeded, failed, refunded, dispute opened, checkout expired, charge.refunded, customer.subscription.updated, …). Each asserts final domain state.

### W2-15 — Golden-master for parent payment history
- **Type:** Backend / Test
- **Estimate:** 2h
- `tests/interface/test_parent_payments_golden_master.py` + baseline JSON. Documented contract delta vs legacy in `docs/contract-deltas/parent-payments.md`.

## Frontend — Parent route group

### W2-16 — Parent layout + BFF client
- **Type:** Frontend / UI
- **Estimate:** 5h
- `app/(parent)/layout.tsx` (mobile-first; not coach's tab nav — parent has a stepper-flavored shell). `lib/api/parent.ts` typed.

### W2-17 — Onboarding stepper
- **Type:** Frontend / UI
- **Estimate:** 8h
- `app/(parent)/onboarding/page.tsx` + multi-step form (child details, waiver acceptance, session pick). State in TanStack Query w/ `patch_application` autosave.

### W2-18 — Checkout return + payment status polling
- **Type:** Frontend / UI
- **Estimate:** 5h
- `app/(parent)/checkout/return/page.tsx` polls status (TanStack Query refetch interval until terminal state). Confirmation screen on success, retry CTA on failure.

### W2-19 — Payment history
- **Type:** Frontend / UI
- **Estimate:** 4h
- `app/(parent)/payments/page.tsx`. List of own payments with status badges.

### W2-20 — Install prompt on onboarding success
- **Type:** Frontend / UI
- **Estimate:** 2h
- Surface PWA install on the onboarding-success screen (highest-intent moment for the parent persona per ADR-0004).

### W2-21 — Playwright E2E for parent
- **Type:** Test / E2E
- **Estimate:** 6h
- 10 specs per [wave-1a sheet](wave-1a-coach-today.md#verification): onboarding start → waiver → checkout success → checkout failure → retry → view payment history → message coach → install prompt → refund visible → role-rejection (coach token on parent route → 404).

## Ops

### W2-22 — Cutover canary 10% → 100% + 48h soak
- **Type:** Ops
- **Estimate:** 4h elapsed (waiting on soak)
- Same shape as W1A-20. Soak target: 48h with zero double-charge and zero missed confirmations.

## Exit Checklist

- [ ] W2-01 … W2-15 backend merged.
- [ ] W2-16 … W2-21 frontend merged.
- [ ] Stripe webhook fixture replay green on all 10 scenarios.
- [ ] Side-by-side contract diff documented in `docs/contract-deltas/`.
- [ ] Canary 10% passes 1h.
- [ ] 100% held for 48h with no SLO breach.
- [ ] No double-charge in audit log over 48h.
- [ ] Cutover documented in `docs/cutover-w2-parent.md`.
