# Autopay Opt-in at Payment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A default-checked "Enroll in autopay for future invoices" checkbox under every parent Pay button; when left checked, the one-time invoice payment also saves the payment method and activates autopay for the covered enrollment(s).

**Architecture:** Thread an `enroll_autopay` boolean from the parent BFF through the invoice-payment use cases into the Stripe gateway (`setup_future_usage=off_session` + metadata `autopay_optin`/`enrollment_ids`); complete activation on both the `checkout.session.completed` webhook and the `GetCheckoutStatus` poll via a new `CompleteAutopaySetup.execute_from_payment_checkout`. Frontend renders the checkbox and sends the flag.

**Tech Stack:** FastAPI + Pydantic (backend/v2 DDD billing context), Stripe Python SDK, Motor/Mongo, Next.js App Router + React Query (frontend), pytest + existing fake_stripe fixtures.

**Spec:** docs/superpowers/specs/2026-07-05-autopay-optin-at-payment-design.md (read it first — it is the source of truth).

## Global Constraints

- Branch: `feat/autopay-optin-at-payment` off `origin/main` (worktree `.worktrees/autopay-optin`).
- `enroll_autopay` defaults to `False` server-side; unchecked/absent flag must leave the payment flow byte-identical to today.
- Never pass `payment_method_types` to Stripe. Do not modify the dedicated autopay-setup (mode=setup) flow, the `allow_platform_charge_fallback` logic, or connected-account routing.
- Activation failure must NOT fail a succeeded payment's status response — log and let the webhook worker retry.
- Checkbox label copy, exact: "Enroll in autopay for future invoices".
- Metadata keys, exact: `autopay_optin` = `"true"`, `enrollment_ids` = comma-joined distinct ids (respect Stripe's 500-char value cap: truncate whole ids, log a warning).
- TDD per task; run `ruff format` on touched Python files before committing; conventional commits.

---

### Task 1: BFF request/response models + route plumbing

**Files:**
- Modify: `backend/v2/interfaces/parent/views.py` (StartInvoicePaymentRequest, StartBalancePaymentRequest, ParentInvoiceView ~L196)
- Modify: `backend/v2/interfaces/parent/invoice_routes.py` (`_invoice_view`, `start_invoice_payment`, `start_balance_payment` — pass the flag through)
- Modify: `backend/v2/composition/parent.py` (the `start_invoice_payment_for_parent` / balance-payment lambdas: accept + forward `enroll_autopay`)
- Test: the existing parent invoice interface test module under `backend/v2/tests/interface/` (extend it)

**Interfaces:**
- Produces: `StartInvoicePaymentRequest.enroll_autopay: bool = False`; `StartBalancePaymentRequest.enroll_autopay: bool = False`; `ParentInvoiceView.enrollment_id: str | None = None`; route handlers forward `enroll_autopay=body.enroll_autopay` to the use-case callables.

- [ ] Write failing interface tests: (a) invoice list/detail includes `enrollment_id`; (b) POST pay body without `enroll_autopay` still 200s (back-compat) and the use case receives `enroll_autopay=False`; (c) with `enroll_autopay=true` the use case receives `True`.
- [ ] Implement model fields + `_invoice_view(..., enrollment_id=invoice.enrollment_id)` + route/composition forwarding.
- [ ] Run the interface test module; then commit `feat(billing): expose enrollment_id and enroll_autopay on parent invoice payment API`.

### Task 2: Use cases + Stripe gateway session params

**Files:**
- Modify: `backend/v2/contexts/billing/application/use_cases/parent_billing.py` (StartInvoicePayment / StartBalancePayment use cases — find the classes backing the composition lambdas; add `enroll_autopay: bool = False` to their commands/params and forward to the gateway; collect distinct non-null `enrollment_id`s of the invoices being paid)
- Modify: `backend/v2/contexts/billing/infrastructure/stripe_gateway.py` (`create_invoice_checkout_session`: new kwargs `save_payment_method_for_autopay: bool = False` + `autopay_enrollment_ids: list[str] | None = None`; when set → `payment_intent_data["setup_future_usage"]="off_session"`, `customer_creation="always"`, metadata `autopay_optin`/`enrollment_ids`)
- Modify: `backend/v2/contexts/billing/application/ports.py` (InvoiceStripeGateway protocol signature parity where this method is declared)
- Test: the existing Stripe gateway request-shape suite under `backend/v2/tests/contract/` + the parent_billing unit/application test modules

**Interfaces:**
- Consumes: Task 1's `enroll_autopay` flag.
- Produces: gateway kwarg `save_payment_method_for_autopay`, metadata contract used by Task 3 (`autopay_optin == "true"`, `enrollment_ids` comma-joined).

- [ ] Failing tests: gateway payload contains `setup_future_usage`/`customer_creation`/metadata only when the flag is set; absent otherwise (assert existing payload unchanged to prove parity); enrollment_ids deduped; 500-char truncation logs and drops whole ids.
- [ ] Implement; keep `SendInvoice`'s calls unchanged (default False).
- [ ] Run billing/stripe test subset; commit `feat(billing): pay-and-save checkout sessions for autopay opt-in`.

### Task 3: Activation from a payment checkout (webhook + poll)

**Files:**
- Modify: `backend/v2/contexts/billing/application/use_cases/parent_billing.py` (`CompleteAutopaySetup.execute_from_payment_checkout(checkout: dict)` — retrieve payment intent via gateway, extract `payment_method` + `customer`, set default payment method, capture consent with source `invoice_payment_optin`, loop `mark_autopay_active_from_setup` per metadata enrollment id; per-id failure → log + continue, never raise past the payment result; also branch `GetCheckoutStatus` to detect `mode=="payment"` + `autopay_optin=="true"` sessions and run it synchronously after the existing payment bookkeeping, wrapped so failure doesn't alter the returned payment status)
- Modify: `backend/v2/contexts/billing/application/use_cases/handle_webhook_event.py` (`checkout.session.completed` handler: same branch)
- Modify (if needed): `backend/v2/contexts/billing/infrastructure/stripe_gateway.py` — add `retrieve_payment_intent` mirroring `retrieve_setup_intent` if absent.
- Test: CompleteAutopaySetup + GetCheckoutStatus modules under `backend/v2/tests/application/`, plus the handle_webhook_event test module

**Interfaces:**
- Consumes: Task 2's metadata contract; existing `mark_autopay_active_from_setup` (idempotent), consent-capture port.
- Produces: nothing downstream; terminal backend task.

- [ ] Failing tests: happy path (single + multi enrollment ids → all active, consent recorded, default PM set); missing `student_billing_enrollments` doc → logged, payment status still returned as success; idempotent replay (second webhook no-op); plain payment session (no metadata) → branch not taken.
- [ ] Implement; run application + interface suites; commit `feat(billing): activate autopay from opted-in invoice payments`.

### Task 4: Frontend checkbox + API client

**Files:**
- Modify: `frontend/lib/api/` parent invoices client (add `enroll_autopay` to the two pay POST bodies; add `enrollment_id` to invoice types)
- Modify: `frontend/app/(parent)/parent/payments/page.tsx` (pay-all button) and the invoice detail pay UI (find via the "View detail" / pay action for an open invoice)
- Test: follow repo convention for component/unit tests adjacent to the page or lib

**Interfaces:**
- Consumes: Task 1's API contract.
- Behavior: checkbox "Enroll in autopay for future invoices", default checked, rendered under the Pay button ONLY when at least one covered enrollment has `autopay_enrollment_status` NOT in {active, setup_started, paused} (single-invoice: that invoice's enrollment; pay-all: any open invoice's enrollment). Unchecked → `enroll_autopay: false`.

- [ ] Failing tests: default-checked; hidden when all covered enrollments enrolled; request body carries the flag both ways.
- [ ] Implement; run `pnpm typecheck && pnpm lint` + the touched tests; commit `feat(parent): autopay opt-in checkbox on invoice payment`.

### Task 5: Full verification + PR

- [ ] Backend: full `pytest` (repo task runner) green; `ruff format --check` clean.
- [ ] Frontend: `pnpm typecheck`, `pnpm lint`, unit tests green.
- [ ] Push branch (pre-push hook runs the 7-check suite); open PR to `main` titled `feat(billing): autopay opt-in at invoice payment time`, body links the spec and summarizes UX + Stripe mechanics + back-compat guarantees.
