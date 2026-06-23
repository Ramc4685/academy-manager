# Production Billing Legacy Conversion Design

## Scope

Convert production billing off the legacy `payments` collection and onto the
ledger collections:

- `invoices`
- `invoice_lines`
- `ledger_payments`
- `payment_allocations`
- `account_credit_ledger`, where existing credit behavior requires it
- `legacy_payments_archive`, as the immutable archive for removed legacy rows

This design covers billing only. It does not clean up identity legacy fields,
student import fields, waivers, session normalization, coach-rate compatibility,
or communications compatibility paths.

No production write is allowed until the dry-run output and blockers are reviewed.

## Current Behavior Found

Production is already served by the v2 backend, but v2 billing still contains
transition compatibility with legacy payment records.

The active production failure is caused by this split:

- Admin student Billing selects rows from `student.payment_history`.
- Legacy-backed rows use `payment_id` values like `pay_28505f6db2b4a5b11917`.
- The student Billing UI sends that selected id to
  `/api/v2/admin/billing/invoices/{invoice_id}/record-payment`.
- The record-payment use case only accepts a ledger invoice id from `invoices`.
- Result: `invoice 'pay_...' not found`.

The existing repo has the intended retirement path:

- `backend/scripts/backfill_p4_legacy_payments.py`
- `backend/scripts/archive_legacy_payments.py`
- `backend/scripts/launch_readiness_audit.py`
- `docs/runbooks/legacy-payments-retirement.md`

However, the current backfill should be hardened before production use:

- It creates deterministic invoice ids as `inv-from-{payment_id}` but does not
  preserve the visible legacy `invoice_number` such as `BLNO-202605-b11917`.
- Its existing-id check should include `academy_id` so a cross-tenant id cannot
  accidentally short-circuit a backfill.
- Pending/failed balance calculations should use the same final-amount semantics
  as current admin read models, including discounts and amount received.
- The production apply step needs a backup, dry-run review, archive review, and
  smoke/audit gate.

## Goals

1. After conversion, active BLNO billing views use ledger invoices/payments
   rather than legacy `payments` rows.
2. Historical invoice labels remain recognizable to admins and parents.
3. Manual payment, send invoice, charge card, dues, reports, parent payments, and
   student Billing detail operate against ledger invoice ids.
4. Legacy `payments` rows are archived before deletion from `payments`.
5. The launch-readiness audit reports billing legacy retirement as `pass`.

## Non-Goals

- No blind production delete.
- No mutation of Stripe objects.
- No rewriting of non-billing production data.
- No removal of compatibility code before production data is converted and
  smoke-tested.
- No SaaS tenant data model cleanup in this phase.

## Approach

Use a hardened version of the existing runbook.

### Phase 0: Code Hardening

Update `backend/scripts/backfill_p4_legacy_payments.py` and tests before any
production write:

- Copy `doc.invoice_number` onto the new ledger invoice when present.
- Preserve useful provenance:
  - `backfill_source = "legacy_payment"`
  - `backfill_payment_id = <legacy payment_id>`
  - `source_type = "legacy_payment"` on the generated line
  - `source_id = <legacy payment_id>` on the generated line
- Scope idempotency lookup by `academy_id`.
- Compute pending/open balances from the final amount after discount, not raw
  gross amount.
- Support partial legacy rows by carrying paid/received amounts into ledger
  payments and allocations when there is received money.
- Keep unknown or ambiguous statuses blocked, not guessed.

Expected tests:

- mapping preserves `invoice_number`
- pending discounted legacy payment produces open invoice with discounted balance
- partial legacy payment produces partially paid invoice, ledger payment, and
  allocation
- idempotent backfill lookup is academy-scoped
- archive blocks when a legacy row has no backfilled ledger invoice
- launch audit fails before archive and passes after archive in a controlled fixture

### Phase 1: Local Or Staging Rehearsal

Run the hardened scripts against a local/staging copy of production-like data:

```bash
MONGO_URL=... DB_NAME=... \
python -m backend.scripts.backfill_p4_legacy_payments \
  --academy-id acad_blno_badminton --dry-run
```

Then apply only in the rehearsal environment:

```bash
MONGO_URL=... DB_NAME=... \
python -m backend.scripts.backfill_p4_legacy_payments \
  --academy-id acad_blno_badminton
```

Then dry-run archive:

```bash
MONGO_URL=... DB_NAME=... \
python -m backend.scripts.archive_legacy_payments \
  --academy-id acad_blno_badminton
```

Rehearsal must prove:

- zero reconciliation mismatches
- zero archive blockers
- active student Billing rows select ledger invoice ids
- `invoice_number` remains visible as `BLNO-...`
- manual payment works on a converted formerly-legacy pending invoice

### Phase 2: Production Dry Run

Production dry run is read-only.

Run:

```bash
MONGO_URL=... DB_NAME=academy_manager \
python -m backend.scripts.backfill_p4_legacy_payments \
  --academy-id acad_blno_badminton --dry-run
```

Review together before continuing:

- legacy row count
- rows by status
- invoices that would be created
- ledger payments and allocations that would be created
- parent balance reconciliation
- every mismatch or mapping error

Stop if any mismatch or error appears.

### Phase 3: Production Backfill Apply

Before applying, capture a Mongo backup/snapshot or Atlas point-in-time restore
marker.

Apply:

```bash
MONGO_URL=... DB_NAME=academy_manager \
python -m backend.scripts.backfill_p4_legacy_payments \
  --academy-id acad_blno_badminton
```

Immediate checks:

- backfill exits zero
- sample legacy `pay_*` has a corresponding `invoices.backfill_payment_id`
- sample visible invoice number is preserved
- sample paid legacy row has a `ledger_payments` row and `payment_allocations`
  row
- sample pending legacy row has an open ledger invoice with correct balance

### Phase 4: Production Archive Review And Apply

First dry-run:

```bash
MONGO_URL=... DB_NAME=academy_manager \
python -m backend.scripts.archive_legacy_payments \
  --academy-id acad_blno_badminton
```

Review blockers together. Apply only if `status` is `ready`:

```bash
MONGO_URL=... DB_NAME=academy_manager \
python -m backend.scripts.archive_legacy_payments \
  --academy-id acad_blno_badminton --apply
```

Expected result:

- every legacy row copied to `legacy_payments_archive`
- archived rows retain original identifiers and provenance
- `payments` has zero active legacy rows for BLNO

### Phase 5: Production Audit And Smoke

Run:

```bash
MONGO_URL=... DB_NAME=academy_manager PRIMARY_ACADEMY_ID=acad_blno_badminton \
python -m backend.scripts.launch_readiness_audit
```

Required result:

- `database.legacy_payment_retirement.status == "pass"`
- `active_legacy_payment_rows == 0`
- `legacy_rows_missing_backfill == 0`
- `ledger_shaped_payment_rows == 0`
- `ledger_shaped_missing_copy == 0`

Manual smoke:

- Admin student Billing tab for a previously failing pending invoice.
- Record manual payment against a converted pending invoice.
- Admin Payments list.
- Admin Dues follow-up.
- Parent Payments page for a family with historical paid and pending invoices.
- Reports/collections totals for April, May, and June 2026.

## Risks

- Historical data can contain ambiguous statuses or stale balances. These must
  become blockers, not guessed conversions.
- Existing UI tests may assume legacy `payment_id` values in student history.
  Tests should be updated to assert ledger invoice ids after conversion.
- Production archive/delete is destructive if run without backup and blocker
  review. The archive script must be applied only after the dry run reports
  `ready`.
- Removing compatibility code too early can break old historical views. Code
  deletion is a later phase after production data conversion and smoke passes.

## Rollback

Before backfill apply:

- No rollback needed; dry run is read-only.

After backfill apply but before archive apply:

- Leave the added ledger rows in place or remove only the specific
  `backfill_source="legacy_payment"` rows after review.
- Do not delete legacy `payments`; they still exist.

After archive apply:

- Restore `payments` from `legacy_payments_archive` or Atlas point-in-time
  restore if a critical issue is found.
- Since archive copies before delete, each row has an archived source document.

## Approval Gates

1. Approve this design.
2. Approve the implementation plan.
3. Approve production dry-run execution.
4. Approve production backfill apply after dry-run output.
5. Approve production archive apply after archive dry-run output.

No gate can be skipped.
