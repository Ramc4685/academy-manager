# Withdrawal Credits Slice 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add early-withdrawal credit preview, approval, ledger storage, automatic future-invoice application, and subscription cancellation.

**Architecture:** Keep all money math in `backend/v2/contexts/billing/domain`. Application use cases coordinate payment lookup, ledger writes, enrollment status updates, and subscription cancellation. BFF routes only map persona/auth context and shape admin/parent responses.

**Tech Stack:** FastAPI v2 BFF, Pydantic models, Motor/PyMongo repositories, Mongo migrations, Stripe gateway port, Next.js admin/parent UI, pytest, pnpm typecheck/build.

---

## Current Behavior Found

- Payments are the Slice 1 invoice surface and now store `calculation_snapshot_id`.
- First-month snapshots store eligible class counts and included/excluded occurrence IDs.
- Admin refunds already exist in `backend/v2/contexts/billing/application/use_cases/issue_refund.py`.
- Stripe event dedup exists through the v2 webhook path.
- Subscription repository can save/read subscriptions but has no cancel operation yet.
- Enrollment status currently allows `active`, `paused`, and `cancelled`; no `withdrawn` status exists.
- No account credit ledger or credit application collection exists yet.

## Files Likely Affected

- Create `backend/v2/contexts/billing/domain/credits.py`
- Create `backend/v2/contexts/billing/application/use_cases/withdrawal_credit.py`
- Create `backend/v2/contexts/billing/infrastructure/mongo_credit_ledger_repo.py`
- Modify `backend/v2/contexts/billing/application/ports.py`
- Modify `backend/v2/contexts/billing/infrastructure/mongo_payment_repo.py`
- Modify `backend/v2/contexts/billing/infrastructure/mongo_subscription_repo.py`
- Modify `backend/v2/contexts/billing/infrastructure/stripe_gateway.py`
- Modify `backend/v2/contexts/billing/domain/models.py`
- Modify `backend/v2/contexts/enrollment/domain/models.py`
- Modify `backend/v2/composition/admin.py`
- Modify `backend/v2/composition/parent.py`
- Modify `backend/v2/interfaces/admin/billing_routes.py`
- Modify `backend/v2/interfaces/admin/views.py`
- Modify `backend/v2/interfaces/parent/payment_routes.py`
- Modify `backend/v2/interfaces/parent/views.py`
- Modify `backend/v2/migrations/`
- Modify `frontend/lib/api/admin.ts`
- Modify `frontend/lib/api/parent.ts`
- Modify `frontend/app/(admin)/admin/sessions/[id]/page.tsx`
- Modify `frontend/app/(parent)/parent/payments/page.tsx`
- Add/update tests under `backend/v2/tests/unit`, `backend/v2/tests/application`, `backend/v2/tests/contract`, and `backend/v2/tests/interface`.
- Update `test_result.md`.

## Risks

- Credit basis must use the original payment snapshot, not current schedule.
- Refund-then-withdraw must use net paid tuition, not gross invoice.
- Credit application can race with monthly invoice generation unless remaining balance updates are atomic.
- Subscription cancellation needs a Stripe port method and a DB state update; webhook reconciliation must remain idempotent.
- UI must not imply cash refunds are automatic.

---

### Task 1: Domain Credit Policy

**Files:**
- Create: `backend/v2/contexts/billing/domain/credits.py`
- Test: `backend/v2/tests/unit/test_withdrawal_credit_policy.py`

- [ ] **Step 1: Write failing unit tests**

```python
from datetime import datetime, timezone

from backend.v2.contexts.billing.domain.credits import EarlyWithdrawalCreditPolicy


def test_withdrawal_credit_uses_net_paid_and_original_class_count() -> None:
    result = EarlyWithdrawalCreditPolicy().preview(
        paid_tuition_cents=4000,
        refunded_tuition_cents=2000,
        unused_eligible_classes=3,
        paid_period_eligible_classes=8,
        calculated_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        calculated_by="admin-1",
    )

    assert result.credit_amount_cents == 750
    assert result.formula == "max(4000 - 2000, 0) * 3 / 8"
    assert result.no_credit_reason is None


def test_withdrawal_credit_zero_guard_when_paid_period_has_no_classes() -> None:
    result = EarlyWithdrawalCreditPolicy().preview(
        paid_tuition_cents=4000,
        refunded_tuition_cents=0,
        unused_eligible_classes=3,
        paid_period_eligible_classes=0,
        calculated_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        calculated_by="admin-1",
    )

    assert result.credit_amount_cents == 0
    assert result.no_credit_reason == "NO_PAID_PERIOD_ELIGIBLE_CLASSES"
```

- [ ] **Step 2: Run tests and confirm failure**

```bash
cd backend
.venv/bin/python -m pytest v2/tests/unit/test_withdrawal_credit_policy.py -q
```

Expected: import failure for missing `credits.py`.

- [ ] **Step 3: Implement domain policy**

Create `backend/v2/contexts/billing/domain/credits.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pydantic import BaseModel


class WithdrawalCreditPreview(BaseModel):
    credit_amount_cents: int
    paid_tuition_cents: int
    refunded_tuition_cents: int
    net_paid_tuition_cents: int
    unused_eligible_classes: int
    paid_period_eligible_classes: int
    formula: str
    rounding_mode: str = "HALF_UP_FINAL_CENT"
    no_credit_reason: str | None = None
    calculated_at: datetime
    calculated_by: str


@dataclass(frozen=True)
class EarlyWithdrawalCreditPolicy:
    def preview(
        self,
        *,
        paid_tuition_cents: int,
        refunded_tuition_cents: int,
        unused_eligible_classes: int,
        paid_period_eligible_classes: int,
        calculated_at: datetime,
        calculated_by: str,
    ) -> WithdrawalCreditPreview:
        net_paid = max(paid_tuition_cents - refunded_tuition_cents, 0)
        formula = (
            f"max({paid_tuition_cents} - {refunded_tuition_cents}, 0) "
            f"* {unused_eligible_classes} / {paid_period_eligible_classes}"
        )
        if paid_period_eligible_classes == 0:
            return WithdrawalCreditPreview(
                credit_amount_cents=0,
                paid_tuition_cents=paid_tuition_cents,
                refunded_tuition_cents=refunded_tuition_cents,
                net_paid_tuition_cents=net_paid,
                unused_eligible_classes=unused_eligible_classes,
                paid_period_eligible_classes=paid_period_eligible_classes,
                formula=formula,
                no_credit_reason="NO_PAID_PERIOD_ELIGIBLE_CLASSES",
                calculated_at=calculated_at,
                calculated_by=calculated_by,
            )
        amount = _round_half_up_rational(net_paid * unused_eligible_classes, paid_period_eligible_classes)
        reason = "ZERO_UNUSED_CLASSES" if unused_eligible_classes == 0 else None
        if amount == 0 and reason is None:
            reason = "ZERO_NET_PAID_TUITION"
        return WithdrawalCreditPreview(
            credit_amount_cents=amount,
            paid_tuition_cents=paid_tuition_cents,
            refunded_tuition_cents=refunded_tuition_cents,
            net_paid_tuition_cents=net_paid,
            unused_eligible_classes=unused_eligible_classes,
            paid_period_eligible_classes=paid_period_eligible_classes,
            formula=formula,
            no_credit_reason=reason,
            calculated_at=calculated_at,
            calculated_by=calculated_by,
        )


def _round_half_up_rational(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    quotient, remainder = divmod(numerator, denominator)
    return quotient + (1 if remainder * 2 >= denominator else 0)
```

- [ ] **Step 4: Run unit tests**

```bash
cd backend
.venv/bin/python -m pytest v2/tests/unit/test_withdrawal_credit_policy.py -q
```

Expected: pass.

---

### Task 2: Credit Ledger Model, Repository, and Indexes

**Files:**
- Modify: `backend/v2/contexts/billing/domain/models.py`
- Modify: `backend/v2/contexts/billing/application/ports.py`
- Create: `backend/v2/contexts/billing/infrastructure/mongo_credit_ledger_repo.py`
- Create: `backend/v2/migrations/0071_account_credit_ledger_indexes.py`
- Test: `backend/v2/tests/contract/test_mongo_credit_ledger_repo.py`

- [ ] **Step 1: Add failing repository tests**

```python
from datetime import datetime, timezone

import pytest

from backend.v2.contexts.billing.domain.models import CreditLedgerEntry
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import MongoCreditLedgerRepository


@pytest.mark.asyncio
async def test_credit_ledger_fifo_application_is_atomic(db, acad) -> None:
    repo = MongoCreditLedgerRepository(db)
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    await repo.create(
        CreditLedgerEntry(
            credit_id="credit-1",
            academy_id=acad,
            parent_id="parent-1",
            student_id="student-1",
            enrollment_id="enroll-1",
            type="EARLY_WITHDRAWAL_CREDIT",
            status="APPROVED",
            amount_cents=3750,
            remaining_amount_cents=3750,
            currency="usd",
            reason="withdrawal",
            calculation_snapshot_id="snap-1",
            expires_at=datetime(2027, 5, 31, tzinfo=timezone.utc),
            created_at=now,
            updated_at=now,
        )
    )

    applied = await repo.apply_available_credits(parent_id="parent-1", invoice_id="pay-1", amount_due_cents=1000)

    assert applied == 1000
    balance = await repo.balance_for_parent("parent-1")
    assert balance == 2750
```

- [ ] **Step 2: Extend domain model**

Add `CreditLedgerEntry` to `backend/v2/contexts/billing/domain/models.py`:

```python
CreditEntryType = Literal[
    "EARLY_WITHDRAWAL_CREDIT", "MANUAL_CREDIT", "CREDIT_APPLIED", "CREDIT_VOIDED"
]
CreditStatus = Literal["PENDING", "APPROVED", "APPLIED", "EXPIRED", "VOIDED"]


class CreditLedgerEntry(BaseModel):
    model_config = {"frozen": True}

    credit_id: str
    academy_id: str
    parent_id: str
    student_id: str | None = None
    enrollment_id: str | None = None
    invoice_id: str | None = None
    type: CreditEntryType
    status: CreditStatus
    amount_cents: int = Field(ge=0)
    remaining_amount_cents: int = Field(ge=0)
    currency: str = Field(default="usd", min_length=3, max_length=3)
    reason: str
    calculation_snapshot_id: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    expires_at: datetime | None = None
    stripe_credit_note_id: str | None = None
    stripe_customer_balance_txn_id: str | None = None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 3: Add repository port**

Add to `backend/v2/contexts/billing/application/ports.py`:

```python
class CreditLedgerRepository(Protocol):
    async def create(self, entry: CreditLedgerEntry) -> None: ...
    async def list_for_parent(self, parent_id: str) -> list[CreditLedgerEntry]: ...
    async def balance_for_parent(self, parent_id: str) -> int: ...
    async def apply_available_credits(self, *, parent_id: str, invoice_id: str, amount_due_cents: int) -> int: ...
```

- [ ] **Step 4: Implement Mongo repository**

Implement `MongoCreditLedgerRepository` with:

- `collection_name = "account_credit_ledger"`
- `create(entry)` inserts the Pydantic dump.
- `list_for_parent(parent_id)` returns non-voided entries sorted by `created_at desc`.
- `balance_for_parent(parent_id)` sums approved, unexpired `remaining_amount_cents`.
- `apply_available_credits(...)`:
  - sorts approved credits by `expires_at` then `created_at`.
  - inserts into `credit_applications` with unique `(credit_id, invoice_id)`.
  - atomically decrements `remaining_amount_cents` with a filter requiring enough positive balance.
  - inserts a `CREDIT_APPLIED` ledger entry for each application.

- [ ] **Step 5: Add migration indexes**

Create `backend/v2/migrations/0071_account_credit_ledger_indexes.py`:

```python
from __future__ import annotations


async def up(db) -> None:
    await db.account_credit_ledger.create_index([("academy_id", 1), ("parent_id", 1), ("status", 1)])
    await db.account_credit_ledger.create_index([("academy_id", 1), ("expires_at", 1)])
    await db.credit_applications.create_index(
        [("academy_id", 1), ("credit_id", 1), ("invoice_id", 1)],
        unique=True,
    )
```

- [ ] **Step 6: Run contract tests**

```bash
cd backend
.venv/bin/python -m pytest v2/tests/contract/test_mongo_credit_ledger_repo.py -q
```

Expected: pass.

---

### Task 3: Withdrawal Preview and Approval Use Cases

**Files:**
- Create: `backend/v2/contexts/billing/application/use_cases/withdrawal_credit.py`
- Modify: `backend/v2/contexts/billing/infrastructure/mongo_payment_repo.py`
- Modify: `backend/v2/contexts/billing/infrastructure/mongo_subscription_repo.py`
- Modify: `backend/v2/contexts/billing/application/ports.py`
- Modify: `backend/v2/contexts/billing/infrastructure/stripe_gateway.py`
- Test: `backend/v2/tests/application/test_withdrawal_credit_use_cases.py`

- [ ] **Step 1: Add failing application tests**

Cover:

- preview uses original snapshot `total_eligible_classes`
- refund-then-withdraw uses `payment.amount_cents - payment.refunded_cents`
- zero credit preview creates no approved ledger entry
- approve creates approved credit entry
- approve marks enrollment withdrawn/cancelled
- approve cancels Stripe subscription at period end by default

- [ ] **Step 2: Add payment lookup helpers**

Add repository methods:

```python
async def latest_paid_payment_for_enrollment(self, enrollment_id: str) -> Payment | None: ...
async def get_snapshot(self, snapshot_id: str) -> BillingCalculationSnapshot | None: ...
```

The payment lookup must require `status in ["succeeded", "partially_refunded"]` and choose the latest paid period.

- [ ] **Step 3: Add subscription cancellation port**

In `StripeGateway`:

```python
async def cancel_subscription(self, stripe_subscription_id: str, *, at_period_end: bool) -> None: ...
```

In `RealStripeGateway`:

```python
if at_period_end:
    self._stripe.Subscription.modify(stripe_subscription_id, cancel_at_period_end=True)
else:
    self._stripe.Subscription.delete(stripe_subscription_id)
```

In fake gateway, record the cancellation call.

- [ ] **Step 4: Implement use cases**

Create commands/results:

```python
class PreviewWithdrawalCreditCommand(BaseModel):
    enrollment_id: str
    withdrawal_date: datetime
    actor_id: str


class ApproveWithdrawalCreditCommand(BaseModel):
    enrollment_id: str
    withdrawal_date: datetime
    actor_id: str
    admin_note: str = ""
    cancel_subscription_immediately: bool = False
```

Use case behavior:

- Load enrollment by `enrollment_id`.
- Load latest paid payment for enrollment.
- Load original snapshot from `payment.calculation_snapshot_id`.
- Derive `paid_period_eligible_classes` from that snapshot.
- Count unused eligible classes from the snapshot’s included occurrence IDs where class start is after withdrawal date.
- Preview through `EarlyWithdrawalCreditPolicy`.
- Approval creates no entry when preview amount is `0`.
- Approval creates `CreditLedgerEntry(type="EARLY_WITHDRAWAL_CREDIT", status="APPROVED")` when amount is positive.
- Approval updates enrollment status to `cancelled` and stores `withdrawal_date`.
- Approval cancels active subscription at period end unless the command says immediate.

- [ ] **Step 5: Run use case tests**

```bash
cd backend
.venv/bin/python -m pytest v2/tests/application/test_withdrawal_credit_use_cases.py -q
```

Expected: pass.

---

### Task 4: Apply Credits During Monthly Generation

**Files:**
- Modify: `backend/v2/contexts/billing/infrastructure/mongo_payment_repo.py`
- Modify: `backend/v2/composition/admin.py`
- Test: `backend/v2/tests/contract/test_mongo_payment_repo.py`

- [ ] **Step 1: Write failing monthly generation test**

Add a test where parent has `3750` approved credit and monthly invoice amount is `10000`; generated payment should store:

```python
assert payment["amount_cents"] == 6250
assert payment["applied_credit_cents"] == 3750
```

And ledger should have `remaining_amount_cents == 0`.

- [ ] **Step 2: Apply credit after amount calculation and before insert**

In monthly generation:

- acquire `billing_invoice_keys` first
- calculate gross amount
- call `credit_repo.apply_available_credits(parent_id, invoice_id=payment_id, amount_due_cents=gross)`
- insert payment with:

```python
"gross_amount_cents": gross_amount_cents,
"applied_credit_cents": applied_credit_cents,
"amount_cents": gross_amount_cents - applied_credit_cents,
```

- [ ] **Step 3: Run tests**

```bash
cd backend
.venv/bin/python -m pytest v2/tests/contract/test_mongo_payment_repo.py -q
```

Expected: pass.

---

### Task 5: Admin BFF Endpoints

**Files:**
- Modify: `backend/v2/interfaces/admin/views.py`
- Modify: `backend/v2/interfaces/admin/billing_routes.py`
- Modify: `backend/v2/interfaces/admin/deps.py`
- Modify: `backend/v2/composition/admin.py`
- Test: `backend/v2/tests/interface/test_admin_withdrawal_credit.py`

- [ ] **Step 1: Add endpoint tests**

Tests:

- `POST /api/v2/admin/enrollments/{id}/withdrawal-credit/preview` returns credit amount and class counts.
- `POST /api/v2/admin/enrollments/{id}/withdrawal-credit/approve` creates approved credit.
- parent persona on admin endpoint returns 404.

- [ ] **Step 2: Add DTOs**

```python
class WithdrawalCreditPreviewRequest(BaseModel):
    withdrawal_date: datetime


class WithdrawalCreditPreviewResponse(BaseModel):
    credit_amount_cents: int
    display_amount: str
    total_classes: int
    unused_classes: int
    formula: str
    message: str
    no_credit_reason: str | None = None


class WithdrawalCreditApproveRequest(BaseModel):
    withdrawal_date: datetime
    admin_note: str = ""
    cancel_subscription_immediately: bool = False


class WithdrawalCreditApproveResponse(BaseModel):
    status: str
    credit_amount_cents: int
    credit_balance_cents: int
```

- [ ] **Step 3: Add routes**

Add:

- `POST /api/v2/admin/enrollments/{enrollment_id}/withdrawal-credit/preview`
- `POST /api/v2/admin/enrollments/{enrollment_id}/withdrawal-credit/approve`

- [ ] **Step 4: Run interface tests**

```bash
cd backend
.venv/bin/python -m pytest v2/tests/interface/test_admin_withdrawal_credit.py -q
```

Expected: pass.

---

### Task 6: Parent Credit Balance Endpoint and UI

**Files:**
- Modify: `backend/v2/interfaces/parent/views.py`
- Modify: `backend/v2/interfaces/parent/payment_routes.py`
- Modify: `backend/v2/composition/parent.py`
- Modify: `frontend/lib/api/parent.ts`
- Modify: `frontend/app/(parent)/parent/payments/page.tsx`
- Test: `backend/v2/tests/interface/test_parent_credit_balance.py`

- [ ] **Step 1: Add parent endpoint**

Add:

```http
GET /api/v2/parent/credits
```

Response:

```python
class ParentCreditBalanceResponse(BaseModel):
    balance_cents: int
    credits: list[ParentCreditView]
```

Only show active parent-owned approved credits, with reason, amount, remaining amount, and expiry.

- [ ] **Step 2: Add parent payments page display**

In `frontend/app/(parent)/parent/payments/page.tsx`, add a quiet top summary:

```tsx
{creditBalance > 0 && (
  <section>
    <h2>Available credit</h2>
    <p>{money(creditBalance, "USD")} applies automatically to your next invoice.</p>
  </section>
)}
```

- [ ] **Step 3: Verify**

```bash
cd backend
.venv/bin/python -m pytest v2/tests/interface/test_parent_credit_balance.py -q
cd frontend
pnpm typecheck
pnpm build
```

Expected: pass.

---

### Task 7: Admin UI Withdrawal Flow

**Files:**
- Modify: `frontend/lib/api/admin.ts`
- Modify: `frontend/app/(admin)/admin/sessions/[id]/page.tsx`

- [ ] **Step 1: Add API client methods**

```ts
export function previewWithdrawalCredit(enrollmentId: string, payload: { withdrawal_date: string }) {
  return apiFetch<WithdrawalCreditPreviewResponse>(
    `/admin/enrollments/${enrollmentId}/withdrawal-credit/preview`,
    { method: "POST", body: JSON.stringify(payload) }
  );
}

export function approveWithdrawalCredit(
  enrollmentId: string,
  payload: { withdrawal_date: string; admin_note?: string; cancel_subscription_immediately?: boolean }
) {
  return apiFetch<WithdrawalCreditApproveResponse>(
    `/admin/enrollments/${enrollmentId}/withdrawal-credit/approve`,
    { method: "POST", body: JSON.stringify(payload) }
  );
}
```

- [ ] **Step 2: Add Withdraw action in roster**

Add a `Withdraw` button per active roster row that opens a dialog with:

- withdrawal date
- preview button
- credit amount
- used/unused class counts
- admin note
- approve button

- [ ] **Step 3: Run frontend checks**

```bash
cd frontend
pnpm typecheck
pnpm build
```

Expected: pass.

---

### Task 8: Final Verification and Handoff

**Files:**
- Modify: `test_result.md`

- [ ] **Step 1: Run focused backend checks**

```bash
cd backend
.venv/bin/python -m pytest \
  v2/tests/unit/test_withdrawal_credit_policy.py \
  v2/tests/application/test_withdrawal_credit_use_cases.py \
  v2/tests/contract/test_mongo_credit_ledger_repo.py \
  v2/tests/interface/test_admin_withdrawal_credit.py \
  v2/tests/interface/test_parent_credit_balance.py \
  -q
```

Expected: all pass.

- [ ] **Step 2: Run full v2 suite**

```bash
cd backend
.venv/bin/python -m pytest v2/tests -q
```

Expected: all pass.

- [ ] **Step 3: Run frontend checks**

```bash
cd frontend
pnpm typecheck
pnpm build
```

Expected: both pass.

- [ ] **Step 4: Run diff hygiene**

```bash
git diff --check
git status --short --branch
```

Expected: no whitespace errors; only intended files changed plus pre-existing dirty files noted separately.

- [ ] **Step 5: Update `test_result.md`**

Record:

- Slice 2 credit ledger implemented.
- Withdrawal preview/approval implemented.
- Parent credit display implemented.
- Commands run and pass/fail status.
- Any skipped browser smoke.

---

## Acceptance Mapping

- Admin can preview withdrawal credit: Task 5.
- Credit uses unused eligible classes: Tasks 1 and 3.
- Credit requires approval: Tasks 3 and 5.
- Credit posts to parent account: Task 2 and Task 3.
- Credit applies to future invoices: Task 4.
- No automatic cash refund happens: Task 3, separate from `IssueRefund`.
- Paid invoices remain unchanged: Tasks 3 and 4 do not update paid payment rows.
- Credit ledger stores audit trail: Task 2.
- Parent sees available credit: Task 6.
- Subscription cancellation on withdrawal: Task 3.

## Out Of Scope For This Slice

- Stripe credit balance mirroring. Ledger is source of truth first; Stripe mirror can be a later hardening slice.
- Cash refund replacement UI. Existing admin refund flow remains separate.
- Paid invoice mutation. Existing payments are preserved.
- Tax treatment.
