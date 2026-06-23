# Legacy Payments Retirement Runbook

Use this only after `LedgerInvoice`, `LedgerPayment`, and `PaymentAllocation`
are the billing source of truth.

## Goal

Retire the old `payments` collection without losing historical evidence.

Target state:

- `invoices` and `invoice_lines` explain what was owed.
- `ledger_payments` and `payment_allocations` explain what was paid.
- `account_credit_ledger` explains credits/overpayments.
- `parent_billing_customers` owns parent Stripe customer IDs.
- `users` has no `stripe_customer_id`.
- `payments` is empty or archived, not an active billing store.

## Steps

1. Run the non-destructive ledger backfill dry run:

   ```bash
   MONGO_URL=... DB_NAME=... \
   python -m backend.scripts.backfill_p4_legacy_payments \
     --academy-id <academy_id> --dry-run
   ```

2. If the dry run reconciles, apply the backfill:

   ```bash
   MONGO_URL=... DB_NAME=... \
   python -m backend.scripts.backfill_p4_legacy_payments \
     --academy-id <academy_id>
   ```

3. Apply pending v2 migrations, including `0131_legacy_payment_retirement_cleanup`.
   This copies any remaining `users.stripe_customer_id` values to
   `parent_billing_customers`, unsets them from `users`, and drops stale indexes.

4. Dry-run the archive/delete step:

   ```bash
   MONGO_URL=... DB_NAME=... \
   python -m backend.scripts.archive_legacy_payments \
     --academy-id <academy_id>
   ```

   Stop if `status` is `blocked`. Every blocker must be explained before
   continuing.

5. Apply the archive/delete step:

   ```bash
   MONGO_URL=... DB_NAME=... \
   python -m backend.scripts.archive_legacy_payments \
     --academy-id <academy_id> --apply
   ```

   This copies rows into `legacy_payments_archive` before deleting from
   `payments`.

6. Run launch readiness audit:

   ```bash
   MONGO_URL=... DB_NAME=... PRIMARY_ACADEMY_ID=<academy_id> \
   python -m backend.scripts.launch_readiness_audit
   ```

   `database.legacy_payment_retirement.status` must be `pass`.

7. Smoke-test invoice-backed UI surfaces with `payments` empty:

   - `/admin/payments`: open, partial, paid, failed-attempt, invoice detail,
     artifact generation, and reconciliation rows should load from ledger data.
     Ledger invoice rows should not show legacy `Discount`, `Mark paid`,
     `Refund`, or `Undo` actions.
   - `/admin/dues`: families with open or partially paid invoices should be
     listed with balance due.
   - `/admin`: collections KPIs and reports should use `invoices`,
     `ledger_payments`, and `payment_attempts`.
   - `/admin/students` and `/admin/sessions/[id]`: dues chips should reflect
     open invoice balances.
   - Payment-risk campaign audiences should resolve overdue invoice parents.

## Do Not

- Do not manually delete from `payments` before the archive script reports
  `status: ready`.
- Do not use `users.stripe_customer_id` as a billing source after this runbook.
- Do not treat `payments` as billing truth in new code.
