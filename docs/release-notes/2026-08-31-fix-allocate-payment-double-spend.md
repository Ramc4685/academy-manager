# allocate-payment-double-spend

PR: #602

## What changed
`MongoBillingLedgerRepository.allocate_payment` CAS-guarded the invoice-side
update but wrote the payment's `unapplied_amount_cents` with an unconditional
`$set` computed from the snapshot read at the top of the method. The invoice CAS
only protects two writers hitting the same invoice, so two writers allocating one
payment to *different* invoices both passed the domain funds check and both
marked their invoice paid with the same money. Eight call sites allocate under
their own idempotency keys (webhook handlers, admin legacy match, reconciler,
manual payment, checkout), and `checkout_allocation` deliberately spreads one
payment across several invoices, so this is a normal shape rather than a corner
case. The trailing repair already recomputed the correct negative balance and
then discarded it with `max(0, ...)`, so the over-allocation was invisible.

The `ledger_payments` write is now a conditional `$inc` guarded by
`{unapplied_amount_cents: {$gte: consumed}}`; a mismatch rolls the allocation
back and raises `payment funds changed during allocation; retry`. The payment is
debited *before* the invoice is posted, so the scarce resource is reserved first.
Both rollback branches re-derive the balance from the allocation rows that
survive rather than dropping the row (which stranded the money) or blindly
`$inc`-ing it back (which double-refunded whatever a concurrent repair had
already restored). `_repair_allocation_projection` now subtracts the real
`refunded_cents` — ignoring it re-inflated the balance the guard had just
reserved, letting refunded money be allocated a second time with no race at all.
Both repair paths now flag a negative recomputed balance as `over_allocated_cents`
and log at ERROR instead of flooring it to 0; that flag is derived without
refunds, because allocations survive a refund by design and folding refunds in
would mark every refunded-but-allocated payment as a double-spend.

Covered by 10 regression tests in
`backend/v2/tests/contract/test_billing_allocation_double_spend.py`, which
interleave two allocators mid-call (at the snapshot read and at the debit) rather
than asserting an error on a serial second call.

## Deploy notes
No migration required. `over_allocated_cents` is a new optional field on
`ledger_payments` documents, written only by the repair paths; migration 0132's
validator does not set `additionalProperties: false`, and `_payment_from_doc`
maps fields explicitly, so existing readers ignore it.

After deploy, audit for pre-existing double-spends — this change flags them but
does not correct them:

    db.ledger_payments.find({over_allocated_cents: {$gt: 0}})

Alert on that field rather than on the log line: the flag is re-derived on every
repair, so a value that appears while a concurrent allocation is still in flight
clears itself once that allocation commits or rolls back. A payment that stays
flagged means two invoices were paid with one payment's money and needs manual
reconciliation — append a correcting allocation reversal; invoice lines are
`$setOnInsert` and cannot be edited in place.

Expect a new error in webhook handling: `payment funds changed during
allocation; retry`. It is fail-closed and correct (a genuine race was rejected)
but surfaces as event retry/quarantine rather than a silent success, so it may
look like a new failure mode on day one. `allocate_checkout_payment_across_invoices`
swallows it on its best-effort overflow arm and logs at WARNING instead.

## Risk / rollback
Medium risk, money-integrity path. Behaviour change: an allocation that
previously succeeded wrongly now raises, and nothing retries it automatically.
The `$inc`+`$gte` form was chosen over an exact-value CAS specifically to keep
spurious failures down — legitimate split allocations of one payment across
several invoices still both succeed.

Verified with mongomock-motor, not a real mongod. The `$gte` filter, `$inc` and
`matched_count` semantics are standard, but the guarantee this leans on is real
Mongo single-document atomicity, which mongomock cannot exercise (the tests
achieve the interleaving by construction). A staging smoke against real Mongo is
worth doing before trusting it in production.

There is no cross-document transaction, so the sequence is still insert-row →
guarded debit → guarded invoice post. A crash mid-sequence leaves funds reserved
with the invoice unposted: conservative and self-healing via the repair paths,
but a real state a human may observe.

Rollback: revert the PR. The change is confined to
`mongo_billing_ledger_repo.py` plus its tests, adds no schema or migration, and
`over_allocated_cents` left behind on documents is inert to all readers.
