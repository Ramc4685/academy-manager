# ADR-0011: Separate Storage For Ledger Payments

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** RamC (architect)
**Related:** ADR-0006 (tenant-ready single-tenant), ADR-0012 (LedgerInvoice as billing source of truth)
**Plan:** `docs/plans/2026-06-14-billing-ledger-convergence.md` (Phase 1)

## Context

The `billing` context currently has two payment aggregates that **share a single MongoDB collection**:

- **Legacy `Payment`** (`billing/domain/models.py::Payment`, persisted by `mongo_payment_repo.py`) — backs Stripe checkout, payment-intent webhooks, the monthly generation job, admin manual ops (mark-paid/discount/undo), and parent payment history.
- **`LedgerPayment`** (`billing/domain/ledger.py`, persisted by `mongo_billing_ledger_repo.py`) — the AR-ledger payment, allocated to `LedgerInvoice` via `PaymentAllocation`. Written today only on the session-type `invoice.paid` webhook path.

Both write the **`payments`** collection. The two document shapes are distinguished **only by field presence** — a `LedgerPayment` doc carries `ledger_idempotency_key` / `unapplied_amount_cents`; a legacy `Payment` doc carries `enrollment_id` / `stripe_checkout_session_id`. There is **no explicit discriminator field**.

This is a latent data-integrity hazard independent of any feature work: any query that does not filter on the exact discriminating keys can read or count the wrong shape, and an aggregation across "payments" silently mixes two aggregates with different invariants (e.g. `LedgerPayment.unapplied_amount_cents` does not exist on legacy `Payment`). It is the single most urgent fix surfaced by the 2026-06-14 billing audit.

## Decision

**`LedgerPayment` moves to its own MongoDB collection, `ledger_payments`. Legacy `Payment` retains `payments`. The two aggregates never share a collection again.**

Specifically:

1. `MongoBillingLedgerRepository` reads and writes `LedgerPayment` (and looks up payments during allocation) against **`ledger_payments`**, not `payments`.
2. A one-time, idempotent migration moves every existing `LedgerPayment`-shaped document out of `payments` into `ledger_payments`. It runs in a **safe, reversible order — never delete-before-verify**:
   1. **Snapshot backup** the `payments` collection (point-in-time dump retained until the phase is signed off).
   2. **Copy** all `LedgerPayment`-shaped docs into `ledger_payments` (idempotent on `payment_id`; re-runnable).
   3. **Verify counts**: copied count == `LedgerPayment`-shaped count in `payments` (Phase 0 audit row c); spot-check field integrity on a sample.
   4. **Only then remove** the copied docs from `payments`. If verification fails at step 3, abort before any deletion — the source is untouched and the run can be retried.
   - **Rollback:** because copy precedes delete, an abort before step 4 leaves `payments` intact; an issue found after step 4 is recovered by restoring the step-1 snapshot. No step destroys data that hasn't first been copied and count-verified.
3. Post-migration verification asserts: zero `LedgerPayment`-shaped docs remain in `payments`, and zero legacy-shaped docs leaked into `ledger_payments`. Counts reconcile against the Phase 0 production audit (row c).
4. `PaymentAllocation` continues in `payment_allocations`; `LedgerInvoice`/`InvoiceLine` continue in `invoices`/`invoice_lines`. Only the payment storage changes.
5. This change is **storage-only and ships first** (plan Phase 1). It has no user-facing effect and must pass all existing billing read regressions (parent `/invoices`, admin `/billing/invoices`, session-type `invoice.paid` webhook).

## Enforcement

1. **Repository boundary.** `LedgerPayment` persistence is confined to `MongoBillingLedgerRepository`; legacy `Payment` to `MongoPaymentRepository`. Neither repository references the other's collection name.
2. **Migration verification gate.** Phase 1 cannot merge until the reconciliation query is green (counts match audit row c; no cross-leak).
3. **Tenant scoping unchanged.** Both collections remain `academy_id`-scoped per ADR-0006.

## Options Considered

### Option A: Separate `ledger_payments` collection (chosen)

**Pros:**
- Eliminates ambiguous reads structurally — a collection only ever holds one aggregate shape.
- Cleanest mental model; queries/aggregations cannot mix shapes.
- Makes the eventual legacy-`Payment` deletion (ADR-0012, Phase 5) a collection-level operation.

**Cons:**
- Requires a data migration now (sized by audit row c).
- Two collections to index and operate during the transition.

### Option B: Add a `record_kind` discriminator to the shared `payments` collection

**Pros:** No data move; one collection.

**Cons:**
- Every existing and future query must remember to filter on `record_kind` — easy to forget, and a missed filter is exactly today's bug.
- Backfilling `record_kind` onto existing docs is itself a migration, so the "no migration" advantage is largely illusory.
- Two aggregates with divergent invariants still coexist in one collection.
- Rejected — moves the hazard rather than removing it.

### Option C: Leave the shared collection as-is

**Pros:** No work.

**Cons:** The aliasing hazard remains and worsens as ledger adoption grows. Rejected.

## Consequences

**Becomes easier:**
- Ledger payment queries and aggregations are unambiguous.
- Retiring legacy `Payment` later (ADR-0012, Phase 5) can drop/archive the `payments` collection without touching ledger data.

**Becomes harder:**
- One additional collection to provision indexes for and to include in operational tooling (dump/restore, monitoring).
- The Phase 1 migration must be run (and verified) before any convergence work begins.

**To revisit:**
- If a future need requires a unified physical payments view, build it as a read projection/view, not by re-merging the collections.

## Action Items

1. [x] Write ADR acceptance into the Phase 1 task list of the convergence plan.
2. [x] Point `MongoBillingLedgerRepository` `LedgerPayment` reads/writes at `ledger_payments`.
3. [x] Implement idempotent migration `payments` → `ledger_payments` with dry-run + count reconciliation.
4. [x] Add indexes on `ledger_payments` (`academy_id` leading, plus existing lookup keys).
5. [ ] Run billing read-regression suite; confirm green before merge.
