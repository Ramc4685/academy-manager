# Invoicing Core — Standalone Extraction Guide

*Status: seam established 2026-07-11. The billing context imports nothing from
other bounded contexts; this document maps what is portable, what stays, and
what remains before the invoicing core can ship as a standalone product.*

## The seam

The extraction unit is the **invoicing core** inside
`backend/v2/contexts/billing`. It is already ports-and-adapters clean: every
cross-context need is a `Protocol` port in `application/ports.py`, filled by
the composition layer. The import-linter contract
`invoicing-core-independent-of-academy-pricing` (backend/pyproject.toml)
enforces that the core domain never grows a dependency on academy pricing
policy.

## Portable core (~65–70% of the context)

| Area | Files |
|---|---|
| AR ledger | `domain/ledger.py` (LedgerInvoice/InvoiceLine/LedgerPayment/PaymentAllocation, allocation + overpayment→credit math, invoice numbering format) |
| Payments/credits/dunning | `domain/models.py`, `domain/credits.py`, `domain/dunning.py`, `domain/fees.py`, `domain/ach_returns.py`, `domain/autopay_status.py`, `domain/billing_settings.py`, `domain/billing_audit.py`, `domain/connected_account.py`, `domain/product.py` |
| Use cases | invoice numbering, add/remove line, start_checkout, record_manual_payment, issue_refund, send_invoice, dunning retries, reconcile, finance, admin_payment_ops, charge_invoice_via_autopay, handle_webhook_event, checkout_allocation |
| Stripe | `infrastructure/stripe_gateway.py` — Checkout, Customer Portal, SetupIntents, off-session PIs, refunds, webhook verification, **Connect Accounts v2 + destination charges** |
| Persistence | all `infrastructure/mongo_*` repos for billing-owned collections (invoices, invoice_lines, ledger_payments, payment_allocations(+reversals), account_credit_ledger, billing_counters, billing_settings, dunning_states, autopay_*, academy_connected_accounts, billing_audit_log, billing_reconciliation_runs) |

## Academy plugin (stays behind, ~25–30%)

Pricing policy that turns "student enrolled in Tuesday badminton" into generic
invoice lines:

- `domain/proration.py`, `domain/session_type.py`,
  `domain/session_type_proration.py`, `domain/tuition_discount.py`
- use cases: `enroll_child_in_session_type.py`, `quote_enrollment.py`,
  `session_type_ops.py`, `tuition_discounts.py`
- repos: `mongo_session_type_repo.py`,
  `mongo_student_billing_enrollment_repo.py`, `mongo_tuition_discount_repo.py`
- monthly generation (`infrastructure/mongo_monthly_billing.py`) — consumes
  sessions/enrollments to mint ledger invoices

In a standalone deployment the host application implements the existing ports
(`SessionLoader`, `OccurrenceCatalog`, `SnapshotWriter`, `CapacityReservation`,
`EnrollmentBillingIdentityRepository`, `InvoiceEmailPort`,
`DunningNotificationPort`) and emits `InvoiceLine`s; the core never needs to
know what a "session type" is.

## Known remaining coupling (work items)

1. **Webhook handler session-type hooks** — `handle_webhook_event.py` contains
   subscription/session-type paths (`_cancel_student_billing_enrollment`,
   student-billing-enrollment activation). Extract these into a
   host-registered event hook before lifting the webhook machine.
2. **Nullable academy fields on ledger models** — `student_id`,
   `enrollment_id`, `session_id`, `period` on LedgerInvoice/Payment. The math
   never depends on them; replace with `customer_id` + the existing
   `source_type`/`source_id`/`metadata` at extraction time (schema migration).
3. **Direct cross-collection reads in billing infrastructure** — the legacy
   payment repo reads `enrollments`/`sessions`/`students`/`users`. This repo
   is being retired (see below); do not add new such reads.
4. **Enrollment→refund event bridge** — `composition/event_handlers.py`
   (`on_capacity_exceeded`, enrollment cancellation) is host integration code,
   not part of the core.
5. **Tenancy** — `academy_id` scoping via `shared/tenancy` maps 1:1 to a
   standalone tenant/organisation id; the ambient-tenant pattern travels as-is.
6. **Auth/email stay behind** — Firebase auth lives in `shared/auth` +
   interface deps; email (Resend) is injected via ports. Neither is a core
   dependency. `contexts/platform/billing` (SaaS metering) is orthogonal and
   does not travel.

## Legacy Payment retirement status (strangler-fig)

- **Done (2026-07-11):** inserts frozen — new payments are ledger-native
  (`ledger_payments` with `payment_origin: "legacy_payment"`); all legacy
  lookups/lists dual-read; admin manual ops and the manual Stripe reconcile
  work on ledger-resident docs; monthly generation writes ledger invoices only.
- **Remaining before deleting `MongoPaymentRepository` and the `payments`
  collection:** run `scripts/backfill_p4_legacy_payments.py` +
  `scripts/archive_legacy_payments.py` (+ migration
  `0131_legacy_payment_retirement_cleanup.py`) against production data, then
  drop the legacy read halves (parent history merge, revenue fallback,
  invoice-detail fallback, dues follow-up) and delete the repo. Production
  data operation — requires an operator decision, not just code.
