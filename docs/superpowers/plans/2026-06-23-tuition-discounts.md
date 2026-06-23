# Tuition Discounts & Waivers Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement. Steps use checkbox (`- [ ]`) syntax.

**Goal:** First-class, recurring, categorized tuition discounts/waivers stored in a new
`enrollment_discounts` collection and projected onto monthly ledger invoices, visible to admins
(badge + editor) and parents (itemized line), without disturbing legal waivers.

**Architecture:** A `TuitionDiscount` aggregate inside the **billing** bounded context. Admin BFF
sets/removes policies; monthly invoice generation reads the active policy, converts it to a
`monthly_discount_cents` value, feeds the **existing** `FirstMonthProrationPolicy` (subtract-then-
prorate), and writes a discount line + header `discount_cents` on the ledger invoice. Read model
composes a `discount` block onto admin student detail.

**Tech Stack:** Python 3 / Motor (async Mongo) / Pydantic / FastAPI (backend); Next.js / React
Query / TypeScript (frontend). Tests: pytest (backend), node/vitest + Playwright (frontend/E2E).

**Spec:** `docs/superpowers/specs/2026-06-23-tuition-discounts-design.md`

---

## Conventions (verified against codebase)

- Repos extend `TenantScopedRepository` (`backend/v2/shared/tenancy/repository.py`); use
  `_insert_one/_find_one/_find_many/_update_one` which auto-inject `academy_id` via
  `current_academy_id()`. Set `collection_name`.
- Use cases: frozen Pydantic `Command` + a class with `execute()`; repo injected via a `Protocol`
  port. Template: `contexts/billing/application/use_cases/admin_payment_ops.py` (`ApplyPaymentDiscount`).
- Admin routes: `@router.post(...)` with `Depends(require_persona("admin"))` and
  `Depends(get_admin_use_cases)`. Request models in `interfaces/admin/views.py`.
  Template: `interfaces/admin/billing_routes.py`.
- Proration: `FirstMonthProrationPolicy.quote(monthly_price_cents, discount_cents, ...)` already
  applies `base_after_discount = max(monthly_price_cents - discount_cents, 0)` then prorates.
- Ledger: `LedgerInvoice`/`InvoiceLine` are frozen Pydantic; fields stored, no recompute helper.
- Tests: contract tests in `backend/v2/tests/contract/`, fixtures `db` + `acad`.

---

## Chunk 1: Discount domain + net computation

**Files:**
- Create: `backend/v2/contexts/billing/domain/tuition_discount.py`
- Test: `backend/v2/tests/unit/test_tuition_discount_domain.py`

### Task 1.1: Domain model + `monthly_discount_cents`

- [ ] **Step 1: Write the failing test**

```python
# backend/v2/tests/unit/test_tuition_discount_domain.py
import pytest
from backend.v2.contexts.billing.domain.tuition_discount import (
    TuitionDiscount, monthly_discount_cents,
)

def _policy(**kw):
    base = dict(
        discount_id="d1", enrollment_id="e1", student_id="s1",
        category="scholarship", kind="waiver", effective_start="2026-06-01",
    )
    base.update(kw)
    return TuitionDiscount(**base)

@pytest.mark.parametrize("kind,fields,price,expected", [
    ("waiver", {}, 10000, 10000),
    ("percent", {"percent_bps": 1000}, 10000, 1000),
    ("amount_off", {"amount_off_cents": 4000}, 10000, 4000),
    ("amount_off", {"amount_off_cents": 99999}, 10000, 10000),  # floor at price
    ("fixed_net", {"fixed_net_cents": 4000}, 10000, 6000),
    ("fixed_net", {"fixed_net_cents": 0}, 10000, 10000),         # waiver-equivalent
])
def test_monthly_discount_cents(kind, fields, price, expected):
    pol = _policy(kind=kind, **fields)
    assert monthly_discount_cents(pol, monthly_price_cents=price) == expected

def test_other_requires_label():
    with pytest.raises(ValueError):
        _policy(category="other", category_label=None)

def test_percent_requires_bps_in_range():
    with pytest.raises(ValueError):
        _policy(kind="percent", percent_bps=0)
    with pytest.raises(ValueError):
        _policy(kind="percent", percent_bps=10001)
```

- [ ] **Step 2: Run, verify it fails** — `pytest backend/v2/tests/unit/test_tuition_discount_domain.py -v` → import error.

- [ ] **Step 3: Implement** `tuition_discount.py`:

```python
from __future__ import annotations
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, model_validator

DiscountCategory = Literal["owner_child", "coach_child", "scholarship", "sibling", "other"]
DiscountKind = Literal["waiver", "percent", "amount_off", "fixed_net"]
DiscountStatus = Literal["active", "superseded", "ended"]

class TuitionDiscount(BaseModel):
    model_config = {"frozen": True}

    discount_id: str
    academy_id: str | None = None
    enrollment_id: str
    student_id: str
    category: DiscountCategory
    category_label: str | None = None
    kind: DiscountKind
    percent_bps: int | None = None
    amount_off_cents: int | None = None
    fixed_net_cents: int | None = None
    effective_start: date
    effective_end: date | None = None
    note: str | None = None
    status: DiscountStatus = "active"
    set_by: str | None = None
    set_at: datetime | None = None
    ended_by: str | None = None
    ended_at: datetime | None = None

    @model_validator(mode="after")
    def _check(self) -> "TuitionDiscount":
        if self.category == "other" and not (self.category_label or "").strip():
            raise ValueError("category_label is required when category is 'other'")
        if self.kind == "percent":
            if self.percent_bps is None or not (0 < self.percent_bps <= 10000):
                raise ValueError("percent_bps must be in (0, 10000]")
        if self.kind == "amount_off" and (self.amount_off_cents is None or self.amount_off_cents < 0):
            raise ValueError("amount_off_cents must be >= 0")
        if self.kind == "fixed_net" and (self.fixed_net_cents is None or self.fixed_net_cents < 0):
            raise ValueError("fixed_net_cents must be >= 0")
        if self.effective_end is not None and self.effective_end < self.effective_start:
            raise ValueError("effective_end must be >= effective_start")
        return self

def monthly_discount_cents(policy: TuitionDiscount, *, monthly_price_cents: int) -> int:
    """Discount at monthly scale; floored into [0, monthly_price_cents]."""
    if policy.kind == "waiver":
        d = monthly_price_cents
    elif policy.kind == "percent":
        d = round(monthly_price_cents * (policy.percent_bps or 0) / 10000)
    elif policy.kind == "amount_off":
        d = min(policy.amount_off_cents or 0, monthly_price_cents)
    elif policy.kind == "fixed_net":
        d = max(monthly_price_cents - (policy.fixed_net_cents or 0), 0)
    else:  # pragma: no cover
        d = 0
    return max(0, min(d, monthly_price_cents))

def display_label(policy: TuitionDiscount) -> str:
    return {
        "owner_child": "Owner child",
        "coach_child": "Coach child",
        "scholarship": "Scholarship",
        "sibling": "Sibling discount",
        "other": (policy.category_label or "Discount"),
    }[policy.category]
```

- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit** — `feat(billing): tuition discount domain model + net computation (#244)`

---

## Chunk 2: Repository + use cases

**Files:**
- Create: `backend/v2/contexts/billing/infrastructure/mongo_tuition_discount_repo.py`
- Create: `backend/v2/contexts/billing/application/use_cases/tuition_discounts.py`
- Modify: `backend/v2/contexts/billing/application/ports.py` (add `TuitionDiscountPort`)
- Test: `backend/v2/tests/contract/test_mongo_tuition_discount_repo.py`

### Task 2.1: Repo — set (supersede) / remove / get-active / batch active

- [ ] **Step 1: Failing contract test** asserting:
  - `set_active` inserts an `active` policy; a second `set_active` supersedes the first
    (old `status=="superseded"`, exactly one `active`).
  - `get_active(enrollment_id)` returns the active policy or `None`.
  - `remove(enrollment_id, ended_by)` marks active → `ended`.
  - tenant isolation: a policy under academy A is not visible under academy B.
  - `active_by_enrollments([...])` returns a dict keyed by enrollment_id (batch, no N+1).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement repo** extending `TenantScopedRepository`:

```python
class MongoTuitionDiscountRepository(TenantScopedRepository):
    collection_name = "enrollment_discounts"

    def __init__(self, db, *, clock=lambda: datetime.now(UTC)) -> None:
        super().__init__(db)
        self._clock = clock

    async def set_active(self, policy: TuitionDiscount, *, set_by: str) -> TuitionDiscount:
        now = self._clock()
        await self._update_one(
            {"enrollment_id": policy.enrollment_id, "status": "active"},
            {"$set": {"status": "superseded", "updated_at": now}},
        )
        doc = policy.model_dump(mode="json")
        doc.update(status="active", set_by=set_by, set_at=now, updated_at=now)
        await self._insert_one(doc)
        saved = await self._find_one({"discount_id": policy.discount_id})
        return _to_domain(saved)

    async def get_active(self, enrollment_id: str) -> TuitionDiscount | None:
        doc = await self._find_one({"enrollment_id": enrollment_id, "status": "active"})
        return _to_domain(doc) if doc else None

    async def active_by_enrollments(self, enrollment_ids: list[str]) -> dict[str, TuitionDiscount]:
        out: dict[str, TuitionDiscount] = {}
        cursor = self._find_many({"enrollment_id": {"$in": enrollment_ids}, "status": "active"})
        async for doc in cursor:
            out[doc["enrollment_id"]] = _to_domain(doc)
        return out

    async def remove(self, enrollment_id: str, *, ended_by: str) -> None:
        now = self._clock()
        await self._update_one(
            {"enrollment_id": enrollment_id, "status": "active"},
            {"$set": {"status": "ended", "ended_by": ended_by, "ended_at": now, "updated_at": now}},
        )
```

`_to_domain(doc)` strips Mongo `_id`/`updated_at` extras and builds `TuitionDiscount(**doc)`.

- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit** — `feat(billing): enrollment_discounts repository (#244)`

### Task 2.2: Use cases `SetTuitionDiscount` / `RemoveTuitionDiscount`

- [ ] **Step 1: Failing test** (application) covering set + remove and category/value validation
  surfacing as `ValueError`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** the `TuitionDiscountPort` Protocol in `ports.py` and the two use cases
  in `tuition_discounts.py`, mirroring `ApplyPaymentDiscount`. `SetTuitionDiscountCommand` carries
  the policy fields + `set_by`; constructs a `TuitionDiscount` and calls `repo.set_active`.
  `RemoveTuitionDiscountCommand` carries `enrollment_id` + `ended_by`.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(billing): set/remove tuition discount use cases (#244)`

---

## Chunk 3: Invoice projection (the billing-critical core)

**Files:**
- Modify: `backend/v2/contexts/billing/infrastructure/mongo_payment_repo.py`
  (`_resolve_charge_for_enrollment`, `_dual_write_ledger_invoice`, `generate_monthly_payments`)
- Test: `backend/v2/tests/contract/test_mongo_payment_repo.py` (new discount cases)

### Task 3.1: Thread discount into charge resolution

- [ ] **Step 1: Failing tests** (model on existing `test_generate_monthly_*`):
  1. Full-month + `percent 10%` on `$100` → payment `gross_amount_cents==10000`,
     `discount_cents==1000`, `amount_cents==9000`; ledger invoice `subtotal_cents==10000`,
     `discount_cents==1000`, `total_cents==9000`; a `line_type=="discount"` line with
     `amount_cents==-1000`, `source_type=="tuition_discount"`.
  2. Full-month + `waiver` → `discount_cents==10000`, `total_cents==0`.
  3. First-month proration (`enroll-1`/`3_333` scenario) + `amount_off $40` → net/discount per §6
     (gross_prorated − net_prorated, exact).
  4. **Idempotent re-run:** running generation twice yields one invoice with the same discount.
  5. **No policy** → unchanged behavior (`discount_cents==0`).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement.** Inject a `MongoTuitionDiscountRepository` into `MongoPaymentRepository`
  (optional ctor arg, default constructed from `db`). In `_resolve_charge_for_enrollment`:
  - resolve `monthly_price = _session_amount_cents(session_doc)`.
  - `policy = await discount_repo.get_active(enrollment_id)`; if `policy` and its effective window
    overlaps the period (§5 rule), `mdc = monthly_discount_cents(policy, monthly_price_cents=monthly_price)` else `mdc = 0`.
  - **Full month:** `gross = monthly_price`, `net = gross - mdc`.
  - **First month:** `gross_prorated = quote(discount_cents=0).final_amount_cents`,
    `net_prorated = quote(discount_cents=mdc).final_amount_cents`, `discount = gross_prorated - net_prorated`,
    `net = net_prorated`, `gross = gross_prorated`.
  - Return a small `ResolvedCharge` (gross, net, discount, snapshot_id, policy). Update
    `generate_monthly_payments` to write `gross_amount_cents`, `discount_cents`, `amount_cents=net`
    and pass discount context to the ledger dual-write.
- [ ] **Step 4: Implement ledger discount line** in `_dual_write_ledger_invoice`: when `discount>0`,
  append `InvoiceLine(line_type="discount", description=f"{label} discount", quantity=1,
  unit_amount_cents=-discount, amount_cents=-discount, source_type="tuition_discount",
  source_id=policy.discount_id)` and build `LedgerInvoice(subtotal_cents=gross,
  discount_cents=discount, total_cents=gross-discount, balance_due_cents=gross-discount, ...)`.
  `subtotal_cents == gross` (tuition only).
- [ ] **Step 5: Run all billing tests, verify pass + no regressions** —
  `pytest backend/v2/tests/contract/test_mongo_payment_repo.py -v`.
- [ ] **Step 6: Commit** — `feat(billing): apply tuition discount to monthly invoices (#244)`

### Task 3.2: Finalized-invoice guard

- [ ] Failing test: re-running generation for a `paid` invoice does not change `total_cents`.
- [ ] Implement: skip discount mutation when existing invoice status is finalized/paid (mirror the
  existing finalized-state guard in the generator). Commit.

---

## Chunk 4: Admin BFF — routes + read model

**Files:**
- Modify: `backend/v2/interfaces/admin/views.py` (request + view models)
- Modify: `backend/v2/interfaces/admin/sessions_routes.py` (new routes + gross-override guard)
- Modify: admin use-case wiring (`get_admin_use_cases`)
- Modify: `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py`
  + the admin student-detail composition to attach `discount` + `needs_review`
- Test: `backend/v2/tests/interface/test_admin_tuition_discount_routes.py`, contract test for the
  read-model `discount` block.

### Task 4.1: Set/remove routes + gross-override guard
- [ ] Failing interface tests: `PUT /api/v2/admin/enrollments/{id}/tuition-discount` creates a
  policy (category required → 422; `other` without label → 422; percent out of range → 422);
  `DELETE` ends it; non-admin persona → 403.
- [ ] Implement `SetTuitionDiscountRequest` in `views.py` + the two routes wired to the new use
  cases (follow `billing_routes.py`).
- [ ] Add gross-override guard to `POST .../fee`: reject `amount_cents < session price_cents` with
  a 400 directing to the discount endpoint (§8). Add a test.
- [ ] Run, verify pass. Commit.

### Task 4.2: Read-model `discount` + `needs_review`
- [ ] Failing contract test: admin student detail returns `enrolled_sessions[].discount` with
  `{category, kind, gross_cents, discount_cents, net_cents, label, status}`, and
  `needs_review==true` for a legacy `amount_cents < session price` with no policy.
- [ ] Implement: extend `AdminStudentSessionSummary` (repo) + `AdminStudentSessionSummaryView`
  (views) with optional `discount` + `needs_review`. In the admin student-detail composition,
  batch-load `active_by_enrollments(enrolled_ids)` and attach; derive `needs_review` per §8.
- [ ] Run, verify pass. Commit.

---

## Chunk 5: Admin UI — badge + editor

**Files:**
- Modify: `frontend/lib/api/v2/students.ts` (types + `setTuitionDiscount`/`removeTuitionDiscount`)
- Modify: `frontend/app/(admin)/admin/students/[studentId]/page.tsx`
- Test: frontend unit/node tests for badge render + submit payload; typecheck.

- [ ] Add `AdminStudentSessionDiscount` type + extend `AdminStudentSessionSummary` with
  `discount?` and `needs_review?`.
- [ ] Add `setTuitionDiscount(enrollmentId, body)` / `removeTuitionDiscount(enrollmentId)` via
  `apiFetch`.
- [ ] Build a `DiscountEditor` dialog (category required; type = Waive/% off/$ off/Set final price;
  live `Gross → Net` preview; dates default today/none; private note) using the React Query
  mutation + `queryClient.invalidateQueries` pattern (see `SessionsPanel`).
- [ ] Render badge `formatCurrencyCents(net) · {label}` next to the fee; "Needs review" chip opens
  the editor pre-filled. Replace the "Use 0.00 to waive" copy.
- [ ] `npm run typecheck` + tests green. Commit.

---

## Chunk 6: Parent itemization + finance reporting

**Files:**
- Modify: parent BFF invoice/payment view(s) to expose discount `InvoiceLine`s as `{label,
  amount_cents}`, stripping `note`/snapshot internals.
- Modify: parent frontend invoice/payment surface to render the itemized discount line.
- Add: `tuition_discount_summary(period)` billing query (gross vs discount by category) reading
  `invoice_lines` where `source_type=="tuition_discount"`.
- Tests: parent contract test (label present, note absent); reporting query test.

- [ ] Parent view: itemized discount line; note never present. Test + commit.
- [ ] Reporting query + test. Commit.

---

## Chunk 7: Backfill listing + E2E

**Files:**
- Add: read-only script/use case listing enrollments with `amount_cents < session price` and no
  active policy (count + list; never mutates).
- Add: Playwright E2E — set scholarship full waiver + coach-child partial; assert admin badge +
  admin invoice + parent invoice line.

- [ ] Backfill listing + test (assert no writes). Commit.
- [ ] E2E spec green. Commit.

---

## Verification (run before declaring done)

- Backend: `pytest backend/v2/tests/unit backend/v2/tests/contract backend/v2/tests/interface -k "discount or payment or student"`
- Import boundaries: repo's `import-linter` passes — enrollment must not import billing.
- Frontend: `npm run typecheck` + unit tests + the E2E spec.
- Manual: monthly generation on a discounted enrollment yields gross/discount/net consistent with §6.
