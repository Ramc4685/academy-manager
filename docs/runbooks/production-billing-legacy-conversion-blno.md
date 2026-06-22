# BLNO Production Billing Legacy Conversion Runbook

## Scope

Convert BLNO production billing from legacy `payments` rows to ledger invoices,
payments, and allocations. This runbook is billing-only.

## Hard Gates

1. Code hardening merged and deployed.
2. Production dry-run output reviewed.
3. Mongo backup or Atlas restore point confirmed.
4. Backfill apply explicitly approved.
5. Archive dry-run output reviewed.
6. Archive apply explicitly approved.

## Commands

### Backfill Dry Run

```bash
MONGO_URL="${MONGO_URL:?Set production Mongo URL before running}" \
  DB_NAME=academy_manager \
  python -m backend.scripts.backfill_p4_legacy_payments \
  --academy-id acad_blno_badminton --dry-run
```

Stop unless:

- `Total mismatches: 0`
- no `ERROR:` lines
- invoice, line, ledger payment, and allocation counts match expectations

### Backfill Apply

```bash
MONGO_URL="${MONGO_URL:?Set production Mongo URL before running}" \
  DB_NAME=academy_manager \
  python -m backend.scripts.backfill_p4_legacy_payments \
  --academy-id acad_blno_badminton
```

### Archive Dry Run

```bash
MONGO_URL="${MONGO_URL:?Set production Mongo URL before running}" \
  DB_NAME=academy_manager \
  python -m backend.scripts.archive_legacy_payments \
  --academy-id acad_blno_badminton
```

Stop unless JSON output has `"status": "ready"` and `"blockers": []`.

### Archive Apply

```bash
MONGO_URL="${MONGO_URL:?Set production Mongo URL before running}" \
  DB_NAME=academy_manager \
  python -m backend.scripts.archive_legacy_payments \
  --academy-id acad_blno_badminton --apply
```

### Launch Audit

```bash
MONGO_URL="${MONGO_URL:?Set production Mongo URL before running}" \
  DB_NAME=academy_manager \
  PRIMARY_ACADEMY_ID=acad_blno_badminton \
  python -m backend.scripts.launch_readiness_audit
```

Required:

- `legacy_payment_retirement.status == "pass"`
- `active_legacy_payment_rows == 0`
- `legacy_rows_missing_backfill == 0`
- `ledger_shaped_payment_rows == 0`
- `ledger_shaped_missing_copy == 0`

## Manual Smoke

- Admin student Billing tab for Adhvik Saran or another previously failing row.
- Record manual payment against converted pending invoice.
- Confirm visible invoice label stays `BLNO-202605-b11917`, not only
  `inv-from-pay_28505f6db2b4a5b11917`.
- Admin Payments list loads.
- Admin Dues follow-up loads.
- Parent Payments page loads for a family with paid and pending history.
- Reports/collections totals for April, May, and June 2026 look plausible.

## Rollback

Before archive apply, legacy `payments` remain intact. After archive apply,
restore rows from `legacy_payments_archive` or Atlas point-in-time restore.
