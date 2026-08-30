# ledger-double-count

PR: #559

## What changed
Legacy Stripe-subscription `invoice.paid` events were writing the same charge
into `ledger_payments` twice: once as the ledger-native payment recorded by
the subscription-ledger sync, and again as the legacy `Payment` projection
row (`payment_origin="legacy_payment"`) inserted by
`MongoPaymentRepository.save`. Every ledger-based revenue read model
(revenue-by-month, dashboard cash collected, deposit slips) double-counted
these charges. The webhook handler now skips the legacy projection whenever
the ledger already holds a payment for the same `stripe_payment_intent_id`,
and the payment repository refuses to insert a brand-new `ledger_payments`
row for a PI the academy's ledger already records. Because no legacy-shape
row is written anymore, `charge.refunded` for these charges routes through
the ledger refund path, so the ledger payment and its invoices' refunded
amounts stay in sync with Stripe instead of only the projection row being
marked refunded.

## Deploy notes
No migration ships here. Rows already duplicated in production data are NOT
merged by this change — a one-off merge of existing duplicate
`ledger_payments` rows (and the partial unique index on
`(academy_id, stripe_payment_intent_id)` that becomes possible afterwards)
is tracked as a follow-up in #505.

## Risk / rollback
Legacy subscription charges no longer produce a legacy `Payment` projection,
so the `PaymentSucceeded` outbox event for those renewals is no longer
emitted; its only consumer no-ops for renewal payments (the onboarding
transition is keyed to the original checkout payment), and the ledger payment
remains the source of truth for reporting. The duplicate-PI guard in
`MongoPaymentRepository.save` skips (and logs) inserts instead of raising, so
no webhook path gains a new failure mode. Roll back by reverting the merge
commit; charges recorded while it was live simply have the single
ledger-native row, which is the correct state.
