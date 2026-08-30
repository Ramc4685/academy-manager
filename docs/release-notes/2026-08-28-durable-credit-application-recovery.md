# durable-credit-application-recovery

PR: #487

## What changed
Monthly billing could overcharge a family after a crash: account credit was
decremented atomically, but orphan-invoice recovery read the already-applied
amount from audit rows written afterwards, so a crash in between made recovery
bill the invoice at gross. The credit document now records the applied amount in
the same atomic write as the decrement, recovery prices from that, and lost
audit rows are rebuilt. Credit that was spent but whose amount is unrecoverable
now fails the repair loudly (invoice key `repair_failed` + Sentry) instead of
silently billing gross, and the launch-readiness audit reports credit drift.
Also fixes recovery ignoring an enrollment's tuition discount, which overcharged
discounted families by the discount and let their credit cover tuition they
never owed.

## Deploy notes
Migration `0153_credit_application_recovery_indexes` adds two indexes on
`account_credit_ledger` (`applied_invoice_ids`, `applications.invoice_id`). It
runs automatically on boot — `V2_RUN_MIGRATIONS_ON_BOOT = "true"` in
`backend/fly.toml`. No manual step, no env var, no backfill: existing credits
keep working through the `credit_applications` fallback.

## Risk / rollback
Backend-only, confined to the billing credit path. If wrong, monthly generation
could under-bill (credit counted twice against one invoice) or refuse to repair
an orphan invoice, which surfaces as `failed_repair` in the generation result
rather than as a bad charge. Roll back by reverting the PR; the new embedded
`applications` records are additive and harmless to older code, which ignores
the field. The indexes can be left in place.
