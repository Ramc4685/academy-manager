# feat-billing-admin-payment-visibility-ledger-convergence-sta

PR: #299

## What changed
Builds on the admin payment-visibility Phase 1 feature and completes the billing-ledger convergence work:

**Admin payment visibility (Phase 1)**
- payment filters, recent-payments feed, last payment per family

**Refund correctness (adversarially reviewed, 15-agent verification pass)**
- `charge.refunded` webhooks on ledger-only payments now propagate to the allocated invoices' `refunded_cents` — idempotent, retry-safe (invoice sync runs before the payment mark, so Stripe redelivery self-heals), and attributed per allocation (a payment split across invoices never soaks another payment's funding)
- dual-write bridge no longer downgrades `partially_refunded` → `succeeded`
- Add/RemoveInvoiceLine derive balances from real `payment_allocations` sums
- `undo_payment_paid` checks the shadowing ledger doc for Stripe linkage

**Legacy Payment retirement (Phase 5a/5b, strangler-fig)**
- `payments` collection frozen for inserts — new payments are ledger-native (`ledger_payments` + `payment_origin` marker); ledger-native autopay/pay-link payments stay invisible to legacy lookups, preserving the refund-sync path
- legacy lookups/lists dual-read marker docs; parent history dedups by payment_id; per-student summary unions marker docs
- admin mark-paid/discount/undo + manual Stripe reconcile operate on ledger-resident docs
- monthly generation extracted to `mongo_monthly_billing.py`; `MongoPaymentRepository` shrinks 1765 → 812 lines toward deletion (remaining step: prod backfill/archive — operator action, see extraction guide)

**Standalone invoicing seam**
- import-linter contract `invoicing-core-independent-of-academy-pricing` (5 contracts kept, 0 broken)
- `docs/architecture/invoicing-standalone-extraction.md`: portable core vs academy pricing plugin map + remaining coupling work items

## Deploy notes
No migration detected in the diff. Confirm no manual env var or manual step is needed before merge.

## Risk / rollback
_Auto-generated stub — author: fill in what breaks if this is wrong and how
to roll back before merge._ Revert the merge commit if this regresses.
