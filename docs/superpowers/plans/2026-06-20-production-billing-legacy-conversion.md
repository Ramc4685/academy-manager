# Production Billing Legacy Conversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden and rehearse the billing-only legacy `payments` conversion so production BLNO billing can move to ledger invoices/payments without losing invoice labels, balances, or historical evidence.

**Architecture:** Keep the existing strangler path: legacy `Payment` rows are mapped into ledger `invoices`, `invoice_lines`, `ledger_payments`, and `payment_allocations`, then archived from `payments` only after review. The code change is deliberately small: improve the existing backfill script and tests before any production dry run.

**Tech Stack:** Python 3.12, FastAPI/v2 billing context, Motor/MongoDB, pytest, existing scripts under `backend/scripts/`, existing runbook `docs/runbooks/legacy-payments-retirement.md`.

---

## File Structure

- Modify: `backend/scripts/backfill_p4_legacy_payments.py`
  - Owns legacy-payment mapping, balance reconciliation, idempotent ledger write batches, CLI dry-run/apply.
- Modify: `backend/v2/tests/unit/test_backfill_p4_mapping.py`
  - Pure mapping coverage for invoice number, discounts, partial payments, status normalization, and balance reconciliation.
- Modify: `backend/v2/tests/contract/test_archive_legacy_payments.py`
  - Archive safety coverage remains here; add proof that invoice-number-preserving backfilled rows are archiveable.
- Modify: `backend/v2/tests/contract/test_launch_readiness_audit.py`
  - Add the post-archive pass fixture for legacy payment retirement.
- Create: `docs/runbooks/production-billing-legacy-conversion-blno.md`
  - Operator runbook with approval gates, exact dry-run/apply commands, backup requirement, and manual smoke checklist.
- Modify: `docs/test-results/active/2026-06-19-production-legacy-conversion-review.md`
  - Log implementation and verification results with `scripts/dev/test_result.py`; do not manually edit.

## Task 1: Add Failing Mapping Tests

**Files:**
- Modify: `backend/v2/tests/unit/test_backfill_p4_mapping.py`

- [ ] **Step 1: Add tests for preserved invoice numbers and discounted pending balances**

Append these tests near the existing discount/status tests:

```python
def test_mapping_preserves_legacy_invoice_number() -> None:
    doc = _base_doc(
        status="pending",
        payment_id="pay_28505f6db2b4a5b11917",
        invoice_number="BLNO-202605-b11917",
    )
    result = map_legacy_payment(doc)

    assert result is not None
    assert result["invoice"]["invoice_id"] == "inv-from-pay_28505f6db2b4a5b11917"
    assert result["invoice"]["invoice_number"] == "BLNO-202605-b11917"


def test_pending_discount_uses_final_amount_as_balance() -> None:
    doc = _base_doc(status="pending", amount_cents=7000, discount_cents=1000)
    result = map_legacy_payment(doc)

    assert result is not None
    inv = result["invoice"]
    assert inv["subtotal_cents"] == 7000
    assert inv["discount_cents"] == 1000
    assert inv["total_cents"] == 6000
    assert inv["balance_due_cents"] == 6000
```

- [ ] **Step 2: Replace the obsolete discount expectation**

Replace the old `test_discount_reduces_total_not_balance_for_pending` with the new discounted-balance expectation above. The old expectation says pending balance remains gross amount; that is the production risk this plan fixes.

- [ ] **Step 3: Add tests for partial legacy payments**

Append:

```python
def test_partially_paid_creates_partial_invoice_payment_and_allocation() -> None:
    doc = _base_doc(
        status="partially_paid",
        amount_cents=10000,
        paid_amount_cents=None,
        amount_received_cents=4000,
        payment_method="cash",
    )
    result = map_legacy_payment(doc)

    assert result is not None
    inv = result["invoice"]
    assert inv["status"] == "partially_paid"
    assert inv["total_cents"] == 10000
    assert inv["balance_due_cents"] == 6000
    assert result["ledger_payment"] is not None
    assert result["ledger_payment"]["payment_id"] == "lp-from-pay-001"
    assert result["ledger_payment"]["amount_cents"] == 4000
    assert result["ledger_payment"]["payment_method"] == "cash"
    assert result["allocation"] is not None
    assert result["allocation"]["amount_cents"] == 4000


def test_partial_status_alias_maps_to_partially_paid() -> None:
    doc = _base_doc(status="partial", amount_cents=10000, amount_received_cents=2500)
    result = map_legacy_payment(doc)

    assert result is not None
    assert result["invoice"]["status"] == "partially_paid"
    assert result["invoice"]["balance_due_cents"] == 7500
```

- [ ] **Step 4: Add balance reconciliation test**

Append:

```python
def test_legacy_balance_uses_final_amount_minus_received_money() -> None:
    docs = [
        _base_doc(status="pending", amount_cents=7000, discount_cents=1000),
        _base_doc(status="partially_paid", amount_cents=10000, amount_received_cents=4000),
        _base_doc(status="succeeded", amount_cents=8000),
        _base_doc(status="waived", amount_cents=5000),
    ]

    assert _legacy_balance_for_parent(docs) == 12000
```

- [ ] **Step 5: Run tests to verify they fail before implementation**

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/unit/test_backfill_p4_mapping.py -q
```

Expected before implementation: failures for missing `invoice_number`, gross pending balance, unsupported partial statuses, and reconciliation mismatch.

## Task 2: Harden The Backfill Mapper

**Files:**
- Modify: `backend/scripts/backfill_p4_legacy_payments.py`
- Test: `backend/v2/tests/unit/test_backfill_p4_mapping.py`

- [ ] **Step 1: Update status constants**

Replace:

```python
LEGACY_STATUSES = {"succeeded", "pending", "failed", "waived"}
```

With:

```python
PAID_STATUSES = {"succeeded", "paid"}
OPEN_STATUSES = {"pending", "failed", "unpaid", "expired"}
PARTIAL_STATUSES = {"partially_paid", "partial"}
VOID_STATUSES = {"waived"}
LEGACY_STATUSES = PAID_STATUSES | OPEN_STATUSES | PARTIAL_STATUSES | VOID_STATUSES
```

- [ ] **Step 2: Add amount helpers near `_parent_id_from`**

Add:

```python
def _int_cents(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _legacy_total_cents(doc: dict[str, Any]) -> int:
    if doc.get("final_amount_cents") is not None:
        return max(_int_cents(doc.get("final_amount_cents")), 0)
    amount_cents = _int_cents(doc.get("amount_cents"))
    discount_cents = _int_cents(doc.get("discount_cents"))
    return max(amount_cents - discount_cents, 0)


def _legacy_paid_cents(doc: dict[str, Any], *, total_cents: int, status: str) -> int:
    explicit_paid = doc.get("amount_received_cents")
    if explicit_paid is None:
        explicit_paid = doc.get("paid_amount_cents")
    if explicit_paid is None and status in PAID_STATUSES:
        return total_cents
    return min(max(_int_cents(explicit_paid), 0), total_cents)


def _invoice_status_from_legacy(status: str, *, total_cents: int, paid_cents: int) -> str:
    if status in VOID_STATUSES:
        return "void"
    if total_cents == 0 or paid_cents >= total_cents:
        return "paid"
    if paid_cents > 0 or status in PARTIAL_STATUSES:
        return "partially_paid"
    return "open"
```

- [ ] **Step 3: Update `map_legacy_payment` amount and status logic**

Replace the amount/status section in `map_legacy_payment` with:

```python
    amount_cents: int = _int_cents(doc.get("amount_cents"))
    discount_cents: int = _int_cents(doc.get("discount_cents"))
    total_cents: int = _legacy_total_cents(doc)
    paid_cents = _legacy_paid_cents(doc, total_cents=total_cents, status=status)
    balance_due_cents = 0 if status in VOID_STATUSES else max(total_cents - paid_cents, 0)
    invoice_status = _invoice_status_from_legacy(
        status,
        total_cents=total_cents,
        paid_cents=paid_cents,
    )
```

Remove the old `if status in {"pending", "failed"}` status mapping block.

- [ ] **Step 4: Preserve visible invoice number**

Inside the `invoice` dict, after `"invoice_id": invoice_id,` add:

```python
        "invoice_number": doc.get("invoice_number") or invoice_id,
```

- [ ] **Step 5: Use paid amount for partial/succeeded ledger payment creation**

Replace:

```python
    if status == "succeeded":
```

With:

```python
    if paid_cents > 0 and status not in VOID_STATUSES:
```

Replace:

```python
        lp_amount_cents = int(doc.get("paid_amount_cents") or amount_cents)
```

With:

```python
        lp_amount_cents = paid_cents
```

- [ ] **Step 6: Run focused unit tests**

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/unit/test_backfill_p4_mapping.py -q
```

Expected: all mapping tests pass.

## Task 3: Make Backfill Idempotency Tenant-Scoped And Testable

**Files:**
- Modify: `backend/scripts/backfill_p4_legacy_payments.py`
- Create or modify test: `backend/v2/tests/contract/test_backfill_p4_legacy_payments.py`

- [ ] **Step 1: Create a contract test file if it does not exist**

Create `backend/v2/tests/contract/test_backfill_p4_legacy_payments.py` with:

```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.scripts.backfill_p4_legacy_payments import backfill_legacy_payments


@pytest.mark.asyncio
async def test_backfill_idempotency_is_scoped_by_academy(db) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await db["payments"].insert_one(
        {
            "academy_id": "acad-request",
            "payment_id": "pay-shared",
            "parent_id": "parent-1",
            "amount_cents": 6000,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": "other-acad",
            "invoice_id": "inv-from-pay-shared",
            "backfill_payment_id": "pay-shared",
        }
    )

    result = await backfill_legacy_payments(db, academy_id="acad-request", dry_run=False)

    assert result["fatal_count"] == 0
    assert result["already_backfilled"] == 0
    invoice = await db["invoices"].find_one(
        {"academy_id": "acad-request", "invoice_id": "inv-from-pay-shared"}
    )
    assert invoice is not None
    assert invoice["balance_due_cents"] == 6000
```

- [ ] **Step 2: Refactor script body into testable function**

In `backend/scripts/backfill_p4_legacy_payments.py`, add this function signature before
`run_backfill`:

```python
async def backfill_legacy_payments(
    db: Any,
    *,
    academy_id: str,
    dry_run: bool,
) -> dict[str, Any]:
```

Move every statement in the current `run_backfill` body from the `raw_cursor =
db[PAYMENTS_COLLECTION].find({"academy_id": academy_id})` line through the final
report printing into `backfill_legacy_payments`. At the end of that moved body,
replace the current integer return with:

```python
    return {
        "fatal_count": len(errors) + total_mismatches,
        "total": counts["total"],
        "skipped_deleted": skipped_deleted,
        "skipped_unknown": skipped_unknown,
        "already_backfilled": already_backfilled,
        "to_write": {
            "invoices": len(invoices_to_write),
            "invoice_lines": len(lines_to_write),
            "ledger_payments": len(lp_to_write),
            "payment_allocations": len(alloc_to_write),
        },
        "total_mismatches": total_mismatches,
        "errors": errors,
    }
```

Keep the current printed report behavior inside this function so CLI output remains familiar.

Then simplify `run_backfill` to:

```python
async def run_backfill(
    *,
    academy_id: str,
    dry_run: bool,
) -> int:
    s = get_settings()
    client = motor.motor_asyncio.AsyncIOMotorClient(s.mongo_url)
    try:
        result = await backfill_legacy_payments(
            client[s.mongo_db],
            academy_id=academy_id,
            dry_run=dry_run,
        )
        return int(result["fatal_count"])
    finally:
        client.close()
```

- [ ] **Step 3: Scope existing invoice lookup by academy**

Replace:

```python
        existing = await db[INVOICES_COLLECTION].find_one({"invoice_id": invoice_id})
```

With:

```python
        existing = await db[INVOICES_COLLECTION].find_one(
            {"academy_id": academy_id, "invoice_id": invoice_id}
        )
```

- [ ] **Step 4: Run contract and unit tests**

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/unit/test_backfill_p4_mapping.py \
  v2/tests/contract/test_backfill_p4_legacy_payments.py -q
```

Expected: all tests pass.

## Task 4: Strengthen Archive And Launch Audit Coverage

**Files:**
- Modify: `backend/v2/tests/contract/test_archive_legacy_payments.py`
- Modify: `backend/v2/tests/contract/test_launch_readiness_audit.py`

- [ ] **Step 1: Add archive test for preserved invoice-number backfill**

Append to `test_archive_legacy_payments.py`:

```python
@pytest.mark.asyncio
async def test_archive_allows_invoice_number_preserving_backfill(db) -> None:
    now = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
    await db["payments"].insert_one(
        {
            "academy_id": "acad-1",
            "payment_id": "pay_28505f6db2b4a5b11917",
            "invoice_number": "BLNO-202605-b11917",
            "parent_id": "parent-1",
            "amount_cents": 6000,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": "acad-1",
            "invoice_id": "inv-from-pay_28505f6db2b4a5b11917",
            "invoice_number": "BLNO-202605-b11917",
            "backfill_payment_id": "pay_28505f6db2b4a5b11917",
        }
    )

    result = await archive_legacy_payments(db, academy_id="acad-1", apply=False)

    assert result["status"] == "ready"
    assert result["archiveable"] == 1
    assert result["blockers"] == []
```

- [ ] **Step 2: Add post-archive launch audit pass test**

Append to `test_launch_readiness_audit.py`:

```python
@pytest.mark.asyncio
async def test_launch_readiness_audit_passes_after_legacy_payment_archive(db) -> None:
    await identity_membership_indexes.up(db)
    await _create_launch_specific_indexes(db)
    await db["invoices"].insert_one(
        {
            "academy_id": "acad_blno_badminton",
            "invoice_id": "inv-from-legacy-pay-1",
            "backfill_payment_id": "legacy-pay-1",
        }
    )
    await db["legacy_payments_archive"].insert_one(
        {
            "academy_id": "acad_blno_badminton",
            "payment_id": "legacy-pay-1",
            "archive_reason": "legacy_payment_collection_retired",
            "original_collection": "payments",
        }
    )

    result = await launch_readiness_audit.audit_database(
        db, primary_academy_id="acad_blno_badminton"
    )

    retirement = result["legacy_payment_retirement"]
    assert retirement["status"] == "pass"
    assert retirement["active_legacy_payment_rows"] == 0
    assert retirement["legacy_rows_missing_backfill"] == 0
```

- [ ] **Step 3: Run focused contract tests**

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/contract/test_archive_legacy_payments.py \
  v2/tests/contract/test_launch_readiness_audit.py -q
```

Expected: all tests pass.

## Task 5: Add BLNO Production Operator Runbook

**Files:**
- Create: `docs/runbooks/production-billing-legacy-conversion-blno.md`
- Modify: `docs/test-results/active/2026-06-19-production-legacy-conversion-review.md` via CLI only

- [ ] **Step 1: Create runbook**

Create `docs/runbooks/production-billing-legacy-conversion-blno.md`:

````markdown
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
: "${MONGO_URL:?Set production Mongo URL before running}"
DB_NAME=academy_manager python -m backend.scripts.backfill_p4_legacy_payments \
  --academy-id acad_blno_badminton --dry-run
```

Stop unless:

- `Total mismatches: 0`
- no `ERROR:` lines
- invoice, line, ledger payment, and allocation counts match expectations

### Backfill Apply

```bash
: "${MONGO_URL:?Set production Mongo URL before running}"
DB_NAME=academy_manager python -m backend.scripts.backfill_p4_legacy_payments \
  --academy-id acad_blno_badminton
```

### Archive Dry Run

```bash
: "${MONGO_URL:?Set production Mongo URL before running}"
DB_NAME=academy_manager python -m backend.scripts.archive_legacy_payments \
  --academy-id acad_blno_badminton
```

Stop unless JSON output has `"status": "ready"` and `"blockers": []`.

### Archive Apply

```bash
: "${MONGO_URL:?Set production Mongo URL before running}"
DB_NAME=academy_manager python -m backend.scripts.archive_legacy_payments \
  --academy-id acad_blno_badminton --apply
```

### Launch Audit

```bash
: "${MONGO_URL:?Set production Mongo URL before running}"
DB_NAME=academy_manager PRIMARY_ACADEMY_ID=acad_blno_badminton \
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
````

- [ ] **Step 2: Log runbook creation**

Run:

```bash
scripts/dev/test_result.py log production-legacy-conversion-review \
  --agent main \
  --status working \
  --message "Added BLNO billing legacy conversion operator runbook; no production commands run."
```

## Task 6: Run Verification Before Any Production Dry Run

**Files:**
- No new source files beyond prior tasks.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/unit/test_backfill_p4_mapping.py \
  v2/tests/contract/test_backfill_p4_legacy_payments.py \
  v2/tests/contract/test_archive_legacy_payments.py \
  v2/tests/contract/test_launch_readiness_audit.py -q
```

Expected: all pass.

- [ ] **Step 2: Run formatting/lint for touched Python files**

Run:

```bash
cd backend
source .venv/bin/activate
ruff format --check scripts/backfill_p4_legacy_payments.py \
  v2/tests/unit/test_backfill_p4_mapping.py \
  v2/tests/contract/test_backfill_p4_legacy_payments.py \
  v2/tests/contract/test_archive_legacy_payments.py \
  v2/tests/contract/test_launch_readiness_audit.py
ruff check scripts/backfill_p4_legacy_payments.py \
  v2/tests/unit/test_backfill_p4_mapping.py \
  v2/tests/contract/test_backfill_p4_legacy_payments.py \
  v2/tests/contract/test_archive_legacy_payments.py \
  v2/tests/contract/test_launch_readiness_audit.py
```

Expected: both pass.

- [ ] **Step 3: Record verification**

Run:

```bash
scripts/dev/test_result.py verify production-legacy-conversion-review \
  --message "Focused backfill/archive/audit tests passed; ruff format/check passed for touched Python files. No production commands run."
```

- [ ] **Step 4: Commit only related files**

Review status:

```bash
git status --short --branch
git diff -- backend/scripts/backfill_p4_legacy_payments.py \
  backend/v2/tests/unit/test_backfill_p4_mapping.py \
  backend/v2/tests/contract/test_backfill_p4_legacy_payments.py \
  backend/v2/tests/contract/test_archive_legacy_payments.py \
  backend/v2/tests/contract/test_launch_readiness_audit.py \
  docs/runbooks/production-billing-legacy-conversion-blno.md \
  docs/superpowers/specs/2026-06-20-production-billing-legacy-conversion-design.md \
  docs/superpowers/plans/2026-06-20-production-billing-legacy-conversion.md \
  docs/test-results/active/2026-06-19-production-legacy-conversion-review.md
```

Commit only these related files if the user asks for a commit:

```bash
git add backend/scripts/backfill_p4_legacy_payments.py \
  backend/v2/tests/unit/test_backfill_p4_mapping.py \
  backend/v2/tests/contract/test_backfill_p4_legacy_payments.py \
  backend/v2/tests/contract/test_archive_legacy_payments.py \
  backend/v2/tests/contract/test_launch_readiness_audit.py \
  docs/runbooks/production-billing-legacy-conversion-blno.md \
  docs/superpowers/specs/2026-06-20-production-billing-legacy-conversion-design.md \
  docs/superpowers/plans/2026-06-20-production-billing-legacy-conversion.md \
  docs/test-results/active/2026-06-19-production-legacy-conversion-review.md \
  test_result.md
git commit -m "fix: harden legacy billing backfill"
```

## Task 7: Production Dry Run Gate

**Files:**
- No code changes in this task.

- [ ] **Step 1: Ask for explicit production dry-run approval**

Ask the user for approval to run the read-only production dry run. Do not proceed from prior approval; this is a separate gate.

- [ ] **Step 2: Run production dry run only after approval**

Run from the backend environment with production Mongo credentials available:

```bash
: "${MONGO_URL:?Set production Mongo URL before running}"
DB_NAME=academy_manager python -m backend.scripts.backfill_p4_legacy_payments \
  --academy-id acad_blno_badminton --dry-run
```

- [ ] **Step 3: Paste summarized dry-run output into ledger**

Run:

```bash
DRY_RUN_SUMMARY="Production backfill dry run: record the actual total rows, status counts, write counts, mismatch count, and error count from the reviewed terminal output. No production writes run."
scripts/dev/test_result.py verify production-legacy-conversion-review \
  --message "$DRY_RUN_SUMMARY"
```

- [ ] **Step 4: Stop for review**

Do not run backfill apply in the same step. Review the dry-run output with the user.

## Task 8: Production Apply And Archive Gates

**Files:**
- No code changes in this task.

- [ ] **Step 1: Ask for explicit backfill apply approval**

Confirm backup/restore point exists before asking.

- [ ] **Step 2: Apply backfill only after approval**

Run:

```bash
: "${MONGO_URL:?Set production Mongo URL before running}"
DB_NAME=academy_manager python -m backend.scripts.backfill_p4_legacy_payments \
  --academy-id acad_blno_badminton
```

- [ ] **Step 3: Run archive dry run**

Run:

```bash
: "${MONGO_URL:?Set production Mongo URL before running}"
DB_NAME=academy_manager python -m backend.scripts.archive_legacy_payments \
  --academy-id acad_blno_badminton
```

- [ ] **Step 4: Stop for archive review**

Do not run archive apply unless the user approves the archive dry-run output.

- [ ] **Step 5: Apply archive only after approval**

Run:

```bash
: "${MONGO_URL:?Set production Mongo URL before running}"
DB_NAME=academy_manager python -m backend.scripts.archive_legacy_payments \
  --academy-id acad_blno_badminton --apply
```

- [ ] **Step 6: Run launch audit and manual smoke**

Run:

```bash
: "${MONGO_URL:?Set production Mongo URL before running}"
DB_NAME=academy_manager PRIMARY_ACADEMY_ID=acad_blno_badminton \
  python -m backend.scripts.launch_readiness_audit
```

Then manually verify the smoke checklist in `docs/runbooks/production-billing-legacy-conversion-blno.md`.

- [ ] **Step 7: Record final production results**

Run:

```bash
CONVERSION_SUMMARY="Production conversion result: record the actual backfill result, archive result, launch audit result, and manual smoke result from the reviewed terminal and browser checks."
scripts/dev/test_result.py verify production-legacy-conversion-review \
  --message "$CONVERSION_SUMMARY"
```

## Self-Review Notes

- Spec coverage: this plan implements the approved Approach B: harden, rehearse/test, then use production dry-run/apply/archive approval gates.
- Scope: billing-only. Non-billing legacy cleanup is excluded.
- Production safety: no production write task can run without a separate approval gate.
