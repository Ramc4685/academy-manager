# Coach Payroll — Month-First Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Coach Payouts into a month-first payroll workflow: pick a month → see every coach with status and total → open a coach → review/correct session lines → recompute → approve → mark paid → export.

**Architecture:** The **`PayoutPeriod` aggregate (finance context) is the single source of truth.** Month list, detail page, totals, status, and export all read from `payout_periods` / `payout_period_lines`. The legacy derived list (`/admin/finance/payouts` → `MongoPayoutRepository.list_all()`) is **retired from the payouts UI and marked for deletion**. The month list shows coaches with no generated period yet via a `PayoutCalculator` preview — idempotent with generation, so preview total == persisted total.

**Tech Stack:** Backend — FastAPI, MongoDB (Motor), DDD contexts (`finance`, `coaching`, `enrollment`), pytest. Frontend — Next.js App Router, React Query, TypeScript, v2 API client (`frontend/lib/api`).

---

## Architecture Decisions (locked)

1. **Source of truth = `PayoutPeriod`.** No UI surface calls `/admin/finance/payouts` after Phase 2.
2. **Legacy derive list marked for deletion.** `billing/...finance.py::_derive_from_completed_occurrences` and `MongoPayoutRepository.list_all()` are deprecated in Task 2.0 and can be deleted once the route has no callers.
3. **Route prefix confirmed: `/admin`.** Confirmed in `backend/v2/interfaces/admin/router.py:26`: `APIRouter(prefix="/admin")`. New routes live in `payroll_routes.py`, registered in `router.py`. Full URLs: `/admin/payroll/{month}`, `/admin/payroll/{month}/generate`, `/admin/payroll/{month}/recompute`, `/admin/payroll/{month}/export`.
4. **Every payroll route is tenant-scoped.** Every use case call passes `academy_id=claims.academy_id` from the admin JWT. No cross-tenant data is possible.
5. **Edits blocked on approved/paid payouts.** Backend state machine already rejects mutations on non-draft periods. UI hides edit controls and shows "Reopen to correct" when status ≠ draft.
6. **Payroll corrections require a reason.** Coach-change corrections (`PATCH /admin/session-occurrences/{id}/coach`) require `reason` at the API level. The correction drawer UI enforces a non-empty reason before submitting coach changes. Attendance status (present/absent) uses an optional reason.
7. **Audit trail semantics.** `payout_audit_log` captures `"recomputed"` after every recompute (existing). Coach attendance/coach-change writes go to the `coaching` context — they do NOT appear in payout audit. The recompute after a correction produces the audit entry. `overridePayoutLine` produces `"line_overridden"`.
8. **Backward compat.** Old payout detail links using legacy derived IDs will 404 on `getPayoutPeriod`. The detail page catches 404 and redirects to `/admin/payouts` rather than showing a broken page.
9. **Coach-rate gate.** Phase 2 MUST NOT merge until missing-rate count = 0. **Current count: 4 coaches missing rates** (recorded 2026-06-13).

---

## Production Data Audit Results (Phase 0 — completed 2026-06-13)

| Query | Count | Status |
|-------|-------|--------|
| (a) Payable occurrences Jun 2026 | 4 | ✅ Real data to test with |
| (c) Coaches missing rates | **4** | ⚠ **BLOCKER — backfill before Phase 2** |
| (d) Existing payout periods | 0 | ✅ Clean slate |

---

## File Structure

**Backend — new files**
- `backend/v2/contexts/finance/application/use_cases/list_monthly_payroll.py` — `ListMonthlyPayroll`
- `backend/v2/contexts/finance/application/use_cases/bulk_payroll.py` — `BulkGeneratePayroll`, `BulkRecomputePayroll`
- `backend/v2/interfaces/admin/payroll_routes.py` — month-scoped routes
- `backend/v2/tests/application/test_list_monthly_payroll.py`
- `backend/v2/tests/application/test_bulk_payroll.py`
- `backend/v2/tests/interface/test_admin_payroll_month.py`
- `backend/v2/tests/interface/test_admin_payroll_corrections.py`

**Backend — modified files**
- `backend/v2/interfaces/admin/router.py` — include `payroll_routes.router` (exact file, not admin.py)
- `backend/v2/contexts/finance/application/ports.py` — add `MonthlyCoachOccurrenceReader` + `list_for_window`
- `backend/v2/contexts/finance/infrastructure/mongo_payout_period_repo.py` — implement `list_for_window`
- `backend/v2/composition/admin.py` — wire new use cases + adapter
- `backend/v2/interfaces/admin/deps.py` — add new use case fields to `AdminUseCases`
- `backend/v2/interfaces/admin/views.py` — add month payroll views + `BulkPayrollResultView`
- `backend/v2/interfaces/admin/billing_routes.py` — deprecation comment on `get_admin_finance_payouts`

**Frontend — new files**
- `frontend/lib/api/v2/payroll.ts` + `payroll.test.ts`
- `frontend/lib/api/v2/sessions.ts` + `sessions.test.ts`
- `frontend/app/(admin)/admin/payouts/_components/MonthPicker.tsx`
- `frontend/app/(admin)/admin/payouts/_components/CorrectionDrawer.tsx`

**Frontend — modified files**
- `frontend/lib/api/v2/payouts.ts` — add `markPayoutPeriodPaid`; JSDoc-deprecate `listAdminPayouts`
- `frontend/app/(admin)/admin/payouts/page.tsx` — replace flat list with month-first view + warning card
- `frontend/app/(admin)/admin/payouts/[payoutId]/page.tsx` — Mark-paid, load by period_id, 404 redirect, edit-guard

---

## Phase 0 — Production data audit + rate backfill

> ✅ Audit complete (2026-06-13). Results above. Backfill required before Phase 2.

### Gate: Backfill 4 coaches with missing rates

**REQUIRED before Phase 2 can be merged.** 4 coaches have sessions in June 2026 but no active `coach_rate`. Their payout lines compute to $0.

- [ ] **Step 1: Get the 4 missing coach IDs** — run against production via `fly ssh console -a <prod-app>`:

```javascript
const AID="acad_blno_badminton", FROM=ISODate("2026-06-01"), TO=ISODate("2026-07-01");
db.session_occurrences.aggregate([
  { $match: { academy_id: AID, start_at: { $gte: FROM, $lt: TO },
              is_payable: { $ne: false }, status: { $ne: "cancelled" } } },
  { $project: { coach: { $ifNull: ["$actual_coach_id","$scheduled_coach_id"] } } },
  { $group: { _id: "$coach" } },
  { $lookup: { from: "coach_rates", let: { c: "$_id" },
      pipeline: [{ $match: { $expr: { $and: [
        { $eq: ["$academy_id", AID] }, { $eq: ["$coach_id","$$c"] },
        { $eq: ["$status","active"] }
      ] } } }, { $limit: 1 }], as: "rates" } },
  { $match: { rates: { $size: 0 } } },
  { $project: { _id: 1 } }
]);
```

- [ ] **Step 2: Set a rate for each of the 4 coaches** via the admin API (no new code):

```bash
# POST /admin/coaches/{coach_id}/pay-rates  (with admin JWT)
# body: { "billing_unit": "percent_of_revenue", "percent": 60, "currency": "MYR",
#          "effective_from": "2026-06-01T00:00:00Z" }
```

Record the rate type and effective date for each coach in a comment below this step.

- [ ] **Step 3: Re-run query (c) — must return 0 results**

Run the aggregate above again. Expected: empty array `[]`.

- [ ] **Step 4: Commit**

```bash
git add docs/plans/2026-06-13-coach-payroll-month-first.md
git commit -m "docs(payroll): Phase 0 complete — 4 coach rates backfilled, gate cleared"
```

**Phase 2 is gated on Step 3 returning 0.**

---

## Phase 1 — Mark-paid UI

Backend (`POST /admin/payout-periods/{id}/mark-paid`), types, and audit action all exist. This phase adds only the API client wrapper and the dialog.

### Task 1.1: API client `markPayoutPeriodPaid`

**Files:**
- Modify: `frontend/lib/api/v2/payouts.ts`
- Create (if absent): `frontend/lib/api/v2/payouts.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { markPayoutPeriodPaid } from "./payouts";
import * as client from "../client";

describe("markPayoutPeriodPaid", () => {
  beforeEach(() => vi.restoreAllMocks());
  it("POSTs to the mark-paid route with payment body", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ period_id: "p1", status: "paid" } as never);
    await markPayoutPeriodPaid("p1", {
      method: "bank_transfer", paid_at: "2026-07-01T00:00:00Z", amount_cents: 45000, reference: "py_1",
    });
    expect(spy).toHaveBeenCalledWith(
      "/admin/payout-periods/p1/mark-paid",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
```

- [ ] **Step 2: Run → fail**

Run: `cd frontend && npx vitest run lib/api/v2/payouts.test.ts`
Expected: FAIL — `markPayoutPeriodPaid is not exported`.

- [ ] **Step 3: Implement** (append to `payouts.ts`)

```ts
export interface MarkPayoutPaidInput {
  method: "bank_transfer" | "cash" | "check" | "other";
  paid_at: string; // ISO-8601
  amount_cents: number;
  reference?: string | null;
}

export async function markPayoutPeriodPaid(
  periodId: string,
  input: MarkPayoutPaidInput,
): Promise<AdminPayoutPeriodView> {
  return apiFetch<AdminPayoutPeriodView>(
    `/admin/payout-periods/${encodeURIComponent(periodId)}/mark-paid`,
    { method: "POST", body: JSON.stringify(input) },
  );
}
```

- [ ] **Step 4: Run → pass**

Run: `cd frontend && npx vitest run lib/api/v2/payouts.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/api/v2/payouts.ts frontend/lib/api/v2/payouts.test.ts
git commit -m "feat(payroll): add markPayoutPeriodPaid API client wrapper"
```

### Task 1.2: Mark-paid button + dialog on payout detail

**Files:**
- Modify: `frontend/app/(admin)/admin/payouts/[payoutId]/page.tsx`

- [ ] **Step 1: Add mutation + dialog state** to the `Actions` component:

```tsx
const [showPaid, setShowPaid] = useState(false);
const markPaid = useMutation({
  mutationFn: (input: MarkPayoutPaidInput) => markPayoutPeriodPaid(period.period_id, input),
  onSuccess: (updated) => { setError(null); setShowPaid(false); onChanged(updated); },
  onError: (err: Error) => setError(err.message),
});
```

Import `markPayoutPeriodPaid` and `MarkPayoutPaidInput` from `@/lib/api/v2/payouts`.

- [ ] **Step 2: Show button only when `status === "approved"`**

```tsx
{period.status === "approved" && (
  <ActionButton
    icon={<CheckCircle2 className="size-4" aria-hidden="true" />}
    label="Mark paid"
    title="Record that this approved payout has been paid out."
    disabled={markPaid.isPending}
    onClick={() => setShowPaid(true)}
    primary
  />
)}
```

- [ ] **Step 3: `MarkPaidDialog` component** (local, same file)

Form fields: `method` (select: Bank transfer / Cash / Check / Other → values `bank_transfer|cash|check|other`), `paid_at` (date input, default today serialized to ISO), `amount_cents` (number input prefilled `defaultAmountCents/100`, converted to cents on submit), optional `reference` (text). Submit calls `onSubmit`. Follow the existing `OccurrenceReplacementDialog` pattern in `sessions/[id]/page.tsx` for styling.

```tsx
{showPaid && (
  <MarkPaidDialog
    defaultAmountCents={period.total_amount_cents}
    pending={markPaid.isPending}
    onCancel={() => setShowPaid(false)}
    onSubmit={(input) => markPaid.mutate(input)}
  />
)}
```

- [ ] **Step 4: Typecheck + lint**

Run: `cd frontend && npx tsc --noEmit && npx eslint "app/(admin)/admin/payouts/[payoutId]/page.tsx"`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add "frontend/app/(admin)/admin/payouts/[payoutId]/page.tsx"
git commit -m "feat(payroll): add Mark-paid action + dialog to payout detail"
```

---

## Phase 2 — Month-level payout page

**Gate: Phase 0 Step 3 must confirm 0 coaches with missing rates before this phase is accepted into main.**

### Task 2.0: Mark legacy billing route for deletion

**Files:**
- Modify: `backend/v2/interfaces/admin/billing_routes.py`
- Modify: `frontend/lib/api/v2/payouts.ts`

No behavior change. This signals that no new code should call these surfaces.

- [ ] **Step 1: Add deprecation comment in `billing_routes.py`**

Find the route decorated `@router.get("/finance/payouts", ...)`. Add directly above it:

```python
# DEPRECATED — retire after feat/coach-payroll-month-first ships.
# Replaced by: GET /admin/payroll/{month} in payroll_routes.py
# No UI surface should call this route once Phase 2 is merged.
```

- [ ] **Step 2: Add JSDoc deprecation to `listAdminPayouts` in `payouts.ts`**

```ts
/**
 * @deprecated Use `listMonthlyPayroll()` from `v2/payroll.ts` instead.
 * Calls the legacy derived-list route which will be removed after
 * feat/coach-payroll-month-first ships.
 */
export async function listAdminPayouts() {
  return listPayouts();
}
```

- [ ] **Step 3: Commit**

```bash
git add backend/v2/interfaces/admin/billing_routes.py frontend/lib/api/v2/payouts.ts
git commit -m "chore(payroll): deprecate legacy /finance/payouts route and listAdminPayouts"
```

### Task 2.1: `list_for_window` on the repository

**Files:**
- Modify: `backend/v2/contexts/finance/application/ports.py`
- Modify: `backend/v2/contexts/finance/infrastructure/mongo_payout_period_repo.py`
- Test: `backend/v2/tests/application/test_list_monthly_payroll.py`

- [ ] **Step 1: Add protocol method** to `PayoutPeriodRepository` in `ports.py`:

```python
async def list_for_window(
    self,
    *,
    academy_id: str,
    period_start: datetime,
    period_end: datetime,
) -> list[PayoutPeriod]:
    """All periods for this academy whose window exactly matches [period_start, period_end)."""
    ...
```

- [ ] **Step 2: Implement in Mongo repo** — open `mongo_payout_period_repo.py`, find `find_by_window` (the single-coach version), and reuse its tenant-scoped collection find helper without the `coach_id` filter:

```python
async def list_for_window(
    self, *, academy_id: str, period_start: datetime, period_end: datetime
) -> list[PayoutPeriod]:
    cursor = self._collection.find(
        {
            "academy_id": academy_id,
            "period_start": period_start,
            "period_end": period_end,
        },
        sort=[("coach_id", 1)],
    )
    return [self._hydrate(doc) async for doc in cursor]
```

Replace `self._collection.find` and `self._hydrate` with the exact names used in the existing `find_by_window` method — do not rename helpers.

- [ ] **Step 3: Write the test** with `FakePayoutPeriodRepository` (in-memory filtering):

```python
@pytest.mark.asyncio
async def test_list_for_window_returns_only_matching_month():
    repo = FakePayoutPeriodRepository()
    june_start = datetime(2026, 6, 1, tzinfo=UTC)
    june_end = datetime(2026, 7, 1, tzinfo=UTC)
    july_start = datetime(2026, 7, 1, tzinfo=UTC)
    july_end = datetime(2026, 8, 1, tzinfo=UTC)
    p_june_a = make_fake_period(coach_id="c1", period_start=june_start, period_end=june_end, academy_id="a1")
    p_june_b = make_fake_period(coach_id="c2", period_start=june_start, period_end=june_end, academy_id="a1")
    p_july  = make_fake_period(coach_id="c1", period_start=july_start,  period_end=july_end,  academy_id="a1")
    for p in [p_june_a, p_june_b, p_july]:
        await repo.save(p)
    results = await repo.list_for_window(academy_id="a1", period_start=june_start, period_end=june_end)
    assert {r.coach_id for r in results} == {"c1", "c2"}
    assert len(results) == 2
```

- [ ] **Step 4: Run → pass**

Run: `cd backend && pytest v2/tests/application/test_list_monthly_payroll.py::test_list_for_window_returns_only_matching_month -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/v2/contexts/finance/application/ports.py backend/v2/contexts/finance/infrastructure/mongo_payout_period_repo.py backend/v2/tests/application/test_list_monthly_payroll.py
git commit -m "feat(payroll): repository list_for_window for month-scoped periods"
```

### Task 2.2: `MonthlyCoachOccurrenceReader` port + adapter

**Files:**
- Modify: `backend/v2/contexts/finance/application/ports.py`
- Modify: `backend/v2/composition/admin.py`

- [ ] **Step 1: Add the port** to `ports.py`:

```python
class CoachMonthOccurrences(Protocol):
    @property
    def coach_id(self) -> str: ...
    @property
    def session_count(self) -> int: ...


class MonthlyCoachOccurrenceReader(Protocol):
    """Coaches with payable, non-cancelled occurrences in a month window.

    Paying coach = actual_coach_id when set, else scheduled_coach_id.
    Clock-derived completion: end_at < now OR status == 'completed'.
    Never filters on stored status == 'completed' alone.
    """
    async def coaches_with_occurrences(
        self, *, academy_id: str, period_start: datetime, period_end: datetime
    ) -> list[CoachMonthOccurrences]: ...
```

Add both to `__all__`.

- [ ] **Step 2: Implement adapter** in `composition/admin.py`. Copy the exact match expression from `billing/application/use_cases/finance.py::_derive_from_completed_occurrences` (the `is_payable`, `status != cancelled`, clock-completion `$or` block) so semantics match the calculator:

```python
class _MonthlyCoachOccurrenceReaderAdapter:
    def __init__(self, collection) -> None:
        self._col = collection

    async def coaches_with_occurrences(
        self, *, academy_id: str, period_start: datetime, period_end: datetime
    ) -> list:
        from dataclasses import dataclass
        from datetime import timezone

        @dataclass(frozen=True)
        class _Row:
            coach_id: str
            session_count: int

        now = datetime.now(tz=timezone.utc)
        pipeline = [
            {"$match": {
                "academy_id": academy_id,
                "start_at": {"$gte": period_start, "$lt": period_end},
                "is_payable": {"$ne": False},
                "status": {"$ne": "cancelled"},
                "$or": [{"status": "completed"}, {"end_at": {"$lt": now}}],
            }},
            {"$project": {"coach": {"$ifNull": ["$actual_coach_id", "$scheduled_coach_id"]}}},
            {"$group": {"_id": "$coach", "session_count": {"$sum": 1}}},
        ]
        return [
            _Row(coach_id=doc["_id"], session_count=doc["session_count"])
            async for doc in self._col.aggregate(pipeline)
        ]
```

- [ ] **Step 3: Typecheck**

Run: `cd backend && python -m mypy v2/composition/admin.py --ignore-missing-imports`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add backend/v2/contexts/finance/application/ports.py backend/v2/composition/admin.py
git commit -m "feat(payroll): MonthlyCoachOccurrenceReader port + occurrence adapter"
```

### Task 2.3: `ListMonthlyPayroll` use case

**Files:**
- Create: `backend/v2/contexts/finance/application/use_cases/list_monthly_payroll.py`
- Test: `backend/v2/tests/application/test_list_monthly_payroll.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from datetime import datetime, timezone
from backend.v2.contexts.finance.application.use_cases.list_monthly_payroll import (
    ListMonthlyPayroll, MonthlyPayrollRow,
)

UTC = timezone.utc
START = datetime(2026, 6, 1, tzinfo=UTC)
END   = datetime(2026, 7, 1, tzinfo=UTC)

@pytest.mark.asyncio
async def test_lists_generated_and_ungenerated_coaches(fake_reader, fake_periods, fake_calculator):
    # fake_reader: coach "c1" (4 sessions), "c2" (2 sessions)
    # fake_periods: c1 has APPROVED period total_minor=40000 currency MYR; c2 none
    # fake_calculator: c2 preview total_minor=18000 currency MYR
    uc = ListMonthlyPayroll(reader=fake_reader, periods=fake_periods, calculator=fake_calculator)
    rows = await uc.execute(academy_id="a1", period_start=START, period_end=END)
    by_coach = {r.coach_id: r for r in rows}
    assert by_coach["c1"].status == "approved"
    assert by_coach["c1"].total_minor == 40000
    assert by_coach["c1"].period_id is not None
    assert by_coach["c2"].status == "not_generated"
    assert by_coach["c2"].total_minor == 18000
    assert by_coach["c2"].period_id is None

@pytest.mark.asyncio
async def test_reader_receives_correct_academy_id(fake_reader_spy, fake_periods, fake_calculator):
    uc = ListMonthlyPayroll(reader=fake_reader_spy, periods=fake_periods, calculator=fake_calculator)
    await uc.execute(academy_id="acad_blno_badminton", period_start=START, period_end=END)
    assert fake_reader_spy.last_call_academy_id == "acad_blno_badminton"
```

- [ ] **Step 2: Run → fail**

Run: `cd backend && pytest v2/tests/application/test_list_monthly_payroll.py -v`
Expected: FAIL — module not defined.

- [ ] **Step 3: Implement**

```python
"""List one row per coach with occurrences in a month, sourced from PayoutPeriod."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from backend.v2.contexts.finance.application.ports import (
    MonthlyCoachOccurrenceReader, PayoutPeriodRepository, PayoutCalculator,
)


@dataclass(frozen=True)
class MonthlyPayrollRow:
    coach_id: str
    session_count: int
    total_minor: int
    currency: str
    status: str  # "not_generated" | "draft" | "approved" | "paid"
    period_id: str | None


class ListMonthlyPayroll:
    def __init__(
        self, *, reader: MonthlyCoachOccurrenceReader,
        periods: PayoutPeriodRepository, calculator: PayoutCalculator,
    ) -> None:
        self._reader = reader
        self._periods = periods
        self._calculator = calculator

    async def execute(
        self, *, academy_id: str, period_start: datetime, period_end: datetime
    ) -> list[MonthlyPayrollRow]:
        coaches = await self._reader.coaches_with_occurrences(
            academy_id=academy_id, period_start=period_start, period_end=period_end
        )
        existing = {
            p.coach_id: p
            for p in await self._periods.list_for_window(
                academy_id=academy_id, period_start=period_start, period_end=period_end
            )
        }
        rows: list[MonthlyPayrollRow] = []
        for c in coaches:
            period = existing.get(c.coach_id)
            if period is not None:
                rows.append(MonthlyPayrollRow(
                    coach_id=c.coach_id, session_count=c.session_count,
                    total_minor=period.total_minor, currency=period.currency,
                    status=period.status, period_id=period.period_id,
                ))
            else:
                calc = await self._calculator.calculate(
                    coach_id=c.coach_id, academy_id=academy_id,
                    period_start=period_start, period_end=period_end,
                )
                rows.append(MonthlyPayrollRow(
                    coach_id=c.coach_id, session_count=c.session_count,
                    total_minor=calc.total_minor, currency=calc.currency,
                    status="not_generated", period_id=None,
                ))
        return sorted(rows, key=lambda r: r.coach_id)
```

- [ ] **Step 4: Run → pass**

Run: `cd backend && pytest v2/tests/application/test_list_monthly_payroll.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/v2/contexts/finance/application/use_cases/list_monthly_payroll.py backend/v2/tests/application/test_list_monthly_payroll.py
git commit -m "feat(payroll): ListMonthlyPayroll use case (PayoutPeriod source of truth)"
```

### Task 2.4: Views + routes + wiring

**Files:**
- Modify: `backend/v2/interfaces/admin/views.py`
- Create: `backend/v2/interfaces/admin/payroll_routes.py`
- Modify: `backend/v2/interfaces/admin/deps.py`
- Modify: `backend/v2/composition/admin.py`
- Modify: `backend/v2/interfaces/admin/router.py` ← exact file, not admin.py
- Test: `backend/v2/tests/interface/test_admin_payroll_month.py`

- [ ] **Step 1: Add views** to `views.py`:

```python
class AdminMonthlyPayrollRow(BaseModel):
    coach_id: str
    coach_name: str | None = None
    session_count: int
    total_amount_cents: int
    currency: str
    status: str  # not_generated|draft|approved|paid
    period_id: str | None = None


class AdminMonthlyPayrollView(BaseModel):
    month: str             # "2026-06"
    period_start: datetime
    period_end: datetime
    rows: list[AdminMonthlyPayrollRow]
    total_amount_cents: int


class BulkPayrollResultView(BaseModel):
    month: str
    generated: int = 0
    skipped: int = 0
    recomputed: int = 0
```

- [ ] **Step 2: Create `payroll_routes.py`** with all four routes. Every route passes `academy_id=claims.academy_id`:

```python
"""Admin month-scoped payroll routes.

Registered in router.py under prefix /admin. Full paths:
  GET  /admin/payroll/{month}
  POST /admin/payroll/{month}/generate
  POST /admin/payroll/{month}/recompute
  GET  /admin/payroll/{month}/export
"""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminMonthlyPayrollRow, AdminMonthlyPayrollView, BulkPayrollResultView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.payroll"])


def _month_window(month: str) -> tuple[datetime, datetime]:
    try:
        year_s, mon_s = month.split("-")
        year, mon = int(year_s), int(mon_s)
        if not 1 <= mon <= 12:
            raise ValueError
        start = datetime(year, mon, 1, tzinfo=timezone.utc)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="month must be YYYY-MM") from exc
    end = datetime(year + (1 if mon == 12 else 0), (mon % 12) + 1, 1, tzinfo=timezone.utc)
    return start, end


@router.get("/payroll/{month}", response_model=AdminMonthlyPayrollView)
async def get_monthly_payroll(
    month: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminMonthlyPayrollView:
    uc = use_cases.list_monthly_payroll
    if uc is None:
        raise HTTPException(status_code=503, detail="Monthly payroll is not configured")
    start, end = _month_window(month)
    rows = await uc.execute(academy_id=claims.academy_id, period_start=start, period_end=end)
    view_rows = [
        AdminMonthlyPayrollRow(
            coach_id=r.coach_id, session_count=r.session_count,
            total_amount_cents=r.total_minor, currency=r.currency,
            status=r.status, period_id=r.period_id,
        )
        for r in rows
    ]
    return AdminMonthlyPayrollView(
        month=month, period_start=start, period_end=end,
        rows=view_rows,
        total_amount_cents=sum(r.total_amount_cents for r in view_rows),
    )


@router.post("/payroll/{month}/generate", response_model=BulkPayrollResultView)
async def bulk_generate_payroll(
    month: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> BulkPayrollResultView:
    uc = use_cases.bulk_generate_payroll
    if uc is None:
        raise HTTPException(status_code=503, detail="Bulk generate is not configured")
    start, end = _month_window(month)
    result = await uc.execute(academy_id=claims.academy_id, period_start=start, period_end=end)
    return BulkPayrollResultView(month=month, generated=result.generated, skipped=result.skipped)


@router.post("/payroll/{month}/recompute", response_model=BulkPayrollResultView)
async def bulk_recompute_payroll(
    month: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> BulkPayrollResultView:
    uc = use_cases.bulk_recompute_payroll
    if uc is None:
        raise HTTPException(status_code=503, detail="Bulk recompute is not configured")
    start, end = _month_window(month)
    result = await uc.execute(
        academy_id=claims.academy_id, period_start=start, period_end=end,
        actor_id=claims.user_id,
    )
    return BulkPayrollResultView(month=month, recomputed=result.recomputed, skipped=result.skipped)


@router.get("/payroll/{month}/export")
async def export_monthly_payroll_xlsx(
    month: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
):
    import io
    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook

    repo = use_cases.payout_periods
    if repo is None:
        raise HTTPException(status_code=503, detail="Payout periods are not configured")
    start, end = _month_window(month)
    periods = await repo.list_for_window(
        academy_id=claims.academy_id, period_start=start, period_end=end
    )
    wb = Workbook()
    ws = wb.active
    ws.title = "Payroll"
    ws.append(["Coach Payroll", month])
    ws.append([])
    grand_total = 0
    for period in periods:
        ws.append([f"Coach: {period.coach_id}", f"Status: {period.status}"])
        ws.append(["Date", "Session", "Role", "Pay"])
        for line in period.lines:
            ws.append([
                str(line.occurred_at.date()) if getattr(line, "occurred_at", None) else "",
                getattr(line, "session_title", None) or line.occurrence_id,
                "Replacement" if line.basis == "substitute" else "Scheduled",
                line.amount_minor / 100,
            ])
        ws.append(["", "", "Subtotal", period.total_minor / 100])
        grand_total += period.total_minor
        ws.append([])
    ws.append(["", "", "Grand total", grand_total / 100])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="payroll-{month}.xlsx"'},
    )
```

- [ ] **Step 3: Wire into `deps.py`** — add to `AdminUseCases` (next to existing payout fields):

```python
list_monthly_payroll: ListMonthlyPayroll | None = None
bulk_generate_payroll: BulkGeneratePayroll | None = None
bulk_recompute_payroll: BulkRecomputePayroll | None = None
```

- [ ] **Step 4: Wire in `composition/admin.py`** — construct the three use cases with `payout_period_repo`, `_PayoutCalculatorAdapter`, the new `_MonthlyCoachOccurrenceReaderAdapter`, and existing `generate_use_case` / `recompute_use_case` objects.

- [ ] **Step 5: Register in `router.py`** — add to `backend/v2/interfaces/admin/router.py`:

```python
from .payroll_routes import router as payroll_router
```

And after `router.include_router(payout_period_router)`:

```python
router.include_router(payroll_router)
```

- [ ] **Step 6: Write interface tests** in `test_admin_payroll_month.py`:

```python
@pytest.mark.asyncio
async def test_get_monthly_payroll_returns_rows(admin_client, seed_occurrences_and_rates):
    resp = await admin_client.get("/admin/payroll/2026-06")
    assert resp.status_code == 200
    body = resp.json()
    assert body["month"] == "2026-06"
    assert body["total_amount_cents"] == sum(r["total_amount_cents"] for r in body["rows"])
    assert {r["status"] for r in body["rows"]} <= {"not_generated", "draft", "approved", "paid"}

@pytest.mark.asyncio
async def test_get_monthly_payroll_tenant_scoped(admin_client_academy_b, seed_occurrences_and_rates):
    # Admin from a different academy sees no rows from academy A
    resp = await admin_client_academy_b.get("/admin/payroll/2026-06")
    assert resp.status_code == 200
    assert resp.json()["rows"] == []

@pytest.mark.asyncio
async def test_get_monthly_payroll_rejects_bad_month(admin_client):
    assert (await admin_client.get("/admin/payroll/2026-13")).status_code == 422
    assert (await admin_client.get("/admin/payroll/june")).status_code == 422

@pytest.mark.asyncio
async def test_bulk_generate_then_list_shows_drafts(admin_client, seed_occurrences_and_rates):
    gen = await admin_client.post("/admin/payroll/2026-06/generate")
    assert gen.status_code == 200 and gen.json()["generated"] >= 1
    rows = (await admin_client.get("/admin/payroll/2026-06")).json()["rows"]
    assert all(r["status"] in {"draft", "approved", "paid"} for r in rows if r["session_count"] > 0)

@pytest.mark.asyncio
async def test_month_export_returns_xlsx(admin_client, seed_occurrences_and_rates):
    await admin_client.post("/admin/payroll/2026-06/generate")
    resp = await admin_client.get("/admin/payroll/2026-06/export")
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]
```

- [ ] **Step 7: Run → pass**

Run: `cd backend && pytest v2/tests/interface/test_admin_payroll_month.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/v2/interfaces/admin/views.py backend/v2/interfaces/admin/payroll_routes.py backend/v2/interfaces/admin/deps.py backend/v2/interfaces/admin/router.py backend/v2/composition/admin.py backend/v2/tests/interface/test_admin_payroll_month.py
git commit -m "feat(payroll): GET /admin/payroll/{month} + bulk routes + month export + router registration"
```

### Task 2.5: Frontend month API client

**Files:**
- Create: `frontend/lib/api/v2/payroll.ts`
- Create: `frontend/lib/api/v2/payroll.test.ts`

- [ ] **Step 1: Failing test**

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { listMonthlyPayroll, generateMonthlyPayroll, recomputeMonthlyPayroll } from "./payroll";
import * as client from "../client";

describe("payroll client", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("listMonthlyPayroll GETs the month route", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ month: "2026-06", rows: [] } as never);
    await listMonthlyPayroll("2026-06");
    expect(spy).toHaveBeenCalledWith("/admin/payroll/2026-06", { method: "GET" });
  });

  it("generateMonthlyPayroll POSTs to generate", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ month: "2026-06" } as never);
    await generateMonthlyPayroll("2026-06");
    expect(spy).toHaveBeenCalledWith("/admin/payroll/2026-06/generate", { method: "POST" });
  });

  it("recomputeMonthlyPayroll POSTs to recompute", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ month: "2026-06" } as never);
    await recomputeMonthlyPayroll("2026-06");
    expect(spy).toHaveBeenCalledWith("/admin/payroll/2026-06/recompute", { method: "POST" });
  });
});
```

- [ ] **Step 2: Run → fail**

Run: `cd frontend && npx vitest run lib/api/v2/payroll.test.ts`

- [ ] **Step 3: Implement**

```ts
import { apiFetch, apiFetchBlob } from "../client";

export type MonthlyPayrollStatus = "not_generated" | "draft" | "approved" | "paid";

export interface AdminMonthlyPayrollRow {
  coach_id: string;
  coach_name: string | null;
  session_count: number;
  total_amount_cents: number;
  currency: string;
  status: MonthlyPayrollStatus;
  period_id: string | null;
}

export interface AdminMonthlyPayrollView {
  month: string;
  period_start: string;
  period_end: string;
  rows: AdminMonthlyPayrollRow[];
  total_amount_cents: number;
}

export interface BulkPayrollResult {
  month: string;
  generated: number;
  skipped: number;
  recomputed: number;
}

export async function listMonthlyPayroll(month: string): Promise<AdminMonthlyPayrollView> {
  return apiFetch<AdminMonthlyPayrollView>(
    `/admin/payroll/${encodeURIComponent(month)}`, { method: "GET" });
}

export async function generateMonthlyPayroll(month: string): Promise<BulkPayrollResult> {
  return apiFetch<BulkPayrollResult>(
    `/admin/payroll/${encodeURIComponent(month)}/generate`, { method: "POST" });
}

export async function recomputeMonthlyPayroll(month: string): Promise<BulkPayrollResult> {
  return apiFetch<BulkPayrollResult>(
    `/admin/payroll/${encodeURIComponent(month)}/recompute`, { method: "POST" });
}

export async function exportMonthlyPayrollXlsx(month: string): Promise<Blob> {
  return apiFetchBlob(
    `/admin/payroll/${encodeURIComponent(month)}/export`, { method: "GET" });
}
```

- [ ] **Step 4: Run → pass. Step 5: Commit**

```bash
git add frontend/lib/api/v2/payroll.ts frontend/lib/api/v2/payroll.test.ts
git commit -m "feat(payroll): month payroll API client (list/generate/recompute/export)"
```

### Task 2.6: Month-first list page + backward-compat detail + warning card

**Files:**
- Create: `frontend/app/(admin)/admin/payouts/_components/MonthPicker.tsx`
- Modify: `frontend/app/(admin)/admin/payouts/page.tsx`
- Modify: `frontend/app/(admin)/admin/payouts/[payoutId]/page.tsx`

- [ ] **Step 1: `MonthPicker` component**

```tsx
"use client";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface MonthPickerProps { value: string; onChange: (month: string) => void; }

function shiftMonth(month: string, delta: 1 | -1): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1 + delta);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function MonthPicker({ value, onChange }: MonthPickerProps) {
  return (
    <div className="flex items-center gap-2">
      <button onClick={() => onChange(shiftMonth(value, -1))} aria-label="Previous month">
        <ChevronLeft className="size-4" />
      </button>
      <input type="month" value={value}
        onChange={(e) => onChange(e.target.value)}
        className="border rounded px-2 py-1 text-sm" />
      <button onClick={() => onChange(shiftMonth(value, 1))} aria-label="Next month">
        <ChevronRight className="size-4" />
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Rewrite `page.tsx`** — month-first list with warning card and bulk toolbar:

```tsx
"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  listMonthlyPayroll, generateMonthlyPayroll,
  recomputeMonthlyPayroll, exportMonthlyPayrollXlsx,
} from "@/lib/api/v2/payroll";
import { generatePayoutPeriod } from "@/lib/api/v2/payouts";
import { MonthPicker } from "./_components/MonthPicker";

export default function PayoutsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));

  const { data, isLoading } = useQuery({
    queryKey: ["admin", "payroll", month],
    queryFn: () => listMonthlyPayroll(month),
  });

  const generateOne = useMutation({
    mutationFn: (args: { coach_id: string; period_start: string; period_end: string }) =>
      generatePayoutPeriod(args),
    onSuccess: (period) => {
      qc.invalidateQueries({ queryKey: ["admin", "payroll", month] });
      router.push(`/admin/payouts/${period.period_id}`);
    },
  });
  const bulkGenerate  = useMutation({ mutationFn: () => generateMonthlyPayroll(month),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "payroll", month] }) });
  const bulkRecompute = useMutation({ mutationFn: () => recomputeMonthlyPayroll(month),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "payroll", month] }) });
  const bulkExport    = useMutation({
    mutationFn: () => exportMonthlyPayrollXlsx(month),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `payroll-${month}.xlsx`; a.click();
      URL.revokeObjectURL(url);
    },
  });

  const rows = data?.rows ?? [];
  // Coaches with sessions but $0 total have no active pay rate — warn the admin
  const missingRates = rows.filter(r => r.session_count > 0 && r.total_amount_cents === 0);

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Coach Payroll</h1>
        <MonthPicker value={month} onChange={setMonth} />
      </div>

      {/* Missing-rates warning card — disappears once rates are set */}
      {missingRates.length > 0 && (
        <div className="rounded-md border border-yellow-300 bg-yellow-50 px-4 py-3 text-sm text-yellow-800">
          <strong>{missingRates.length} coach{missingRates.length > 1 ? "es" : ""}</strong>
          {" "}have sessions this month but no active pay rate — payout will show $0.{" "}
          <a href="/admin/coaches" className="underline font-medium">Set rates →</a>
        </div>
      )}

      <div className="flex gap-2">
        <button className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
          disabled={bulkGenerate.isPending} onClick={() => bulkGenerate.mutate()}>
          Generate all
        </button>
        <button className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
          disabled={bulkRecompute.isPending} onClick={() => bulkRecompute.mutate()}>
          Recompute all
        </button>
        <button className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
          disabled={bulkExport.isPending} onClick={() => bulkExport.mutate()}>
          Export month
        </button>
      </div>

      {isLoading ? <p className="text-sm text-muted-foreground">Loading…</p> : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="py-2 pr-4 font-medium">Coach</th>
              <th className="py-2 pr-4 font-medium">Sessions</th>
              <th className="py-2 pr-4 font-medium">Total</th>
              <th className="py-2 pr-4 font-medium">Status</th>
              <th className="py-2 font-medium" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.coach_id} className="border-b hover:bg-muted/30">
                <td className="py-2 pr-4">{row.coach_name ?? row.coach_id}</td>
                <td className="py-2 pr-4">{row.session_count}</td>
                <td className="py-2 pr-4">
                  {(row.total_amount_cents / 100).toFixed(2)} {row.currency}
                </td>
                <td className="py-2 pr-4"><StatusChip status={row.status} /></td>
                <td className="py-2">
                  {row.period_id ? (
                    <a href={`/admin/payouts/${row.period_id}`} className="text-primary underline">
                      Open
                    </a>
                  ) : (
                    <button className="text-primary underline disabled:opacity-50"
                      disabled={generateOne.isPending}
                      onClick={() => generateOne.mutate({
                        coach_id: row.coach_id,
                        period_start: data!.period_start,
                        period_end: data!.period_end,
                      })}>
                      Generate
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function StatusChip({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    not_generated: { label: "Not generated", cls: "bg-gray-100 text-gray-600" },
    draft:         { label: "Draft",         cls: "bg-blue-100 text-blue-700" },
    approved:      { label: "Approved",      cls: "bg-yellow-100 text-yellow-700" },
    paid:          { label: "Paid",          cls: "bg-green-100 text-green-700" },
  };
  const { label, cls } = map[status] ?? { label: status, cls: "" };
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>{label}</span>;
}
```

- [ ] **Step 3: Update detail page — load by `period_id` + 404 backward-compat redirect**

In `[payoutId]/page.tsx`, replace the section that calls `listAdminPayouts()` to bridge to a period. After this change the file must not import `listAdminPayouts`:

```tsx
// Load the period directly by its ID
const { data: period, isLoading, error } = useQuery({
  queryKey: ["admin", "payout-period", payoutId],
  queryFn: () => getPayoutPeriod(payoutId),
  retry: (failureCount, err) => {
    // Stale links (legacy derived IDs) return 404 — don't retry
    if ((err as { status?: number })?.status === 404) return false;
    return failureCount < 2;
  },
});

// Backward compat: old links with legacy-derived IDs 404 — redirect gracefully
if (error && (error as { status?: number })?.status === 404) {
  return (
    <div className="space-y-3 p-6">
      <p className="text-sm text-muted-foreground">
        This payout link is outdated. Use the month-first payroll view to find it.
      </p>
      <a href="/admin/payouts" className="text-sm text-primary underline">
        Go to Coach Payroll →
      </a>
    </div>
  );
}
```

- [ ] **Step 4: Typecheck + lint**

Run: `cd frontend && npx tsc --noEmit && npx eslint "app/(admin)/admin/payouts"`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add "frontend/app/(admin)/admin/payouts"
git commit -m "feat(payroll): month-first list + warning card + detail by period_id + 404 compat"
```

---

## Phase 3 — Bulk use cases

> Routes already exist in `payroll_routes.py` (Task 2.4). This phase adds the use cases they call.

### Task 3.1: `BulkGeneratePayroll` + `BulkRecomputePayroll`

**Files:**
- Create: `backend/v2/contexts/finance/application/use_cases/bulk_payroll.py`
- Test: `backend/v2/tests/application/test_bulk_payroll.py`

- [ ] **Step 1: Failing tests**

```python
import pytest
from datetime import datetime, timezone
from backend.v2.contexts.finance.application.use_cases.bulk_payroll import (
    BulkGeneratePayroll, BulkRecomputePayroll,
)

UTC = timezone.utc
START = datetime(2026, 6, 1, tzinfo=UTC)
END   = datetime(2026, 7, 1, tzinfo=UTC)

@pytest.mark.asyncio
async def test_bulk_generate_is_idempotent(fake_reader, fake_periods, generate_use_case):
    uc = BulkGeneratePayroll(reader=fake_reader, periods=fake_periods, generate=generate_use_case)
    first  = await uc.execute(academy_id="a1", period_start=START, period_end=END)
    assert first.generated == 2 and first.skipped == 0
    second = await uc.execute(academy_id="a1", period_start=START, period_end=END)
    assert second.generated == 0 and second.skipped == 2

@pytest.mark.asyncio
async def test_bulk_recompute_skips_non_draft(fake_periods_mixed_statuses, recompute_use_case):
    # fake_periods: c1=draft, c2=approved, c3=paid
    uc = BulkRecomputePayroll(periods=fake_periods_mixed_statuses, recompute=recompute_use_case)
    result = await uc.execute(
        academy_id="a1", period_start=START, period_end=END, actor_id="admin-1")
    assert result.recomputed == 1  # only draft
    assert result.skipped == 2     # approved + paid are skipped
```

- [ ] **Step 2: Run → fail**

Run: `cd backend && pytest v2/tests/application/test_bulk_payroll.py -v`

- [ ] **Step 3: Implement**

```python
"""Bulk month-level payroll operations."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from backend.v2.contexts.finance.application.ports import (
    MonthlyCoachOccurrenceReader, PayoutPeriodRepository,
)
from backend.v2.contexts.finance.application.use_cases.generate_payout_period import GeneratePayoutPeriod
from backend.v2.contexts.finance.application.use_cases.manage_payout_period import RecomputePayoutPeriod


@dataclass(frozen=True)
class BulkGenerateResult:
    generated: int
    skipped: int


@dataclass(frozen=True)
class BulkRecomputeResult:
    recomputed: int
    skipped: int


class BulkGeneratePayroll:
    def __init__(self, *, reader: MonthlyCoachOccurrenceReader,
                 periods: PayoutPeriodRepository, generate: GeneratePayoutPeriod) -> None:
        self._reader = reader
        self._periods = periods
        self._generate = generate

    async def execute(
        self, *, academy_id: str, period_start: datetime, period_end: datetime
    ) -> BulkGenerateResult:
        coaches = await self._reader.coaches_with_occurrences(
            academy_id=academy_id, period_start=period_start, period_end=period_end)
        generated = skipped = 0
        for c in coaches:
            existing = await self._periods.find_by_window(
                coach_id=c.coach_id, period_start=period_start, period_end=period_end)
            if existing is not None:
                skipped += 1
                continue
            await self._generate.execute(
                coach_id=c.coach_id, academy_id=academy_id,
                period_start=period_start, period_end=period_end)
            generated += 1
        return BulkGenerateResult(generated=generated, skipped=skipped)


class BulkRecomputePayroll:
    def __init__(self, *, periods: PayoutPeriodRepository,
                 recompute: RecomputePayoutPeriod) -> None:
        self._periods = periods
        self._recompute = recompute

    async def execute(
        self, *, academy_id: str, period_start: datetime,
        period_end: datetime, actor_id: str
    ) -> BulkRecomputeResult:
        periods = await self._periods.list_for_window(
            academy_id=academy_id, period_start=period_start, period_end=period_end)
        recomputed = skipped = 0
        for p in periods:
            if p.status != "draft":
                skipped += 1
                continue
            await self._recompute.execute(period_id=p.period_id, actor_id=actor_id)
            recomputed += 1
        return BulkRecomputeResult(recomputed=recomputed, skipped=skipped)
```

- [ ] **Step 4: Run → pass. Step 5: Commit**

```bash
git add backend/v2/contexts/finance/application/use_cases/bulk_payroll.py backend/v2/tests/application/test_bulk_payroll.py
git commit -m "feat(payroll): BulkGeneratePayroll + BulkRecomputePayroll use cases"
```

---

## Phase 4 — Payroll correction drawer

Wire three existing-but-unused correction endpoints into the payout detail page. Corrections are **only available when `status === "draft"`**.

### Task 4.1: v2 correction API client wrappers

**Files:**
- Create: `frontend/lib/api/v2/sessions.ts`
- Create: `frontend/lib/api/v2/sessions.test.ts`

- [ ] **Step 1: Failing tests**

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  updateOccurrenceCoachAttendance,
  updateSessionOccurrenceCoach,
  updateOccurrenceReplacement,
} from "./sessions";
import * as client from "../client";

describe("sessions correction client", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("updateOccurrenceCoachAttendance PATCHes coach-attendance", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);
    await updateOccurrenceCoachAttendance("o1", { coach_id: "c1", status: "absent" });
    expect(spy).toHaveBeenCalledWith(
      "/admin/session-occurrences/o1/coach-attendance",
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("updateSessionOccurrenceCoach PATCHes /coach with required reason", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);
    await updateSessionOccurrenceCoach("o1", { actual_coach_id: "c2", reason: "Substituted" });
    expect(spy).toHaveBeenCalledWith(
      "/admin/session-occurrences/o1/coach",
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("updateOccurrenceReplacement PATCHes /replacement", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);
    await updateOccurrenceReplacement("o1", { replacement_coach_id: "c3" });
    expect(spy).toHaveBeenCalledWith(
      "/admin/session-occurrences/o1/replacement",
      expect.objectContaining({ method: "PATCH" }),
    );
  });
});
```

- [ ] **Step 2: Run → fail**

Run: `cd frontend && npx vitest run lib/api/v2/sessions.test.ts`

- [ ] **Step 3: Implement**

```ts
import { apiFetch } from "../client";

export interface UpdateCoachAttendanceInput {
  coach_id: string;
  status: "present" | "absent";
  role?: "lead" | "assistant";
  rate_override_minor?: number | null;
  note?: string;
}

export interface UpdateSessionCoachInput {
  actual_coach_id?: string | null;
  substitute_coach_id?: string | null;
  reason: string; // required at the API level
}

export interface UpdateOccurrenceReplacementInput {
  replacement_coach_id?: string | null;
  reason?: string | null;
}

export async function updateOccurrenceCoachAttendance(
  occurrenceId: string, input: UpdateCoachAttendanceInput,
): Promise<unknown> {
  return apiFetch(
    `/admin/session-occurrences/${encodeURIComponent(occurrenceId)}/coach-attendance`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}

export async function updateSessionOccurrenceCoach(
  occurrenceId: string, input: UpdateSessionCoachInput,
): Promise<unknown> {
  return apiFetch(
    `/admin/session-occurrences/${encodeURIComponent(occurrenceId)}/coach`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}

export async function updateOccurrenceReplacement(
  occurrenceId: string, input: UpdateOccurrenceReplacementInput,
): Promise<unknown> {
  return apiFetch(
    `/admin/session-occurrences/${encodeURIComponent(occurrenceId)}/replacement`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}
```

- [ ] **Step 4: Run → pass. Step 5: Commit**

```bash
git add frontend/lib/api/v2/sessions.ts frontend/lib/api/v2/sessions.test.ts
git commit -m "feat(payroll): v2 client wrappers for coach-attendance/coach/replacement corrections"
```

### Task 4.2: `CorrectionDrawer` + edit-guard on detail page

**Files:**
- Create: `frontend/app/(admin)/admin/payouts/_components/CorrectionDrawer.tsx`
- Modify: `frontend/app/(admin)/admin/payouts/[payoutId]/page.tsx`

- [ ] **Step 1: Build `CorrectionDrawer`**

Props:
```ts
interface CorrectionDrawerProps {
  occurrenceId: string;
  scheduledCoachId: string;
  actualCoachId: string | null;
  attendanceStatus: "present" | "absent" | null;
  coaches: { id: string; name: string }[];
  onApplied: () => void;
  onClose: () => void;
}
```

**Section A — Present / Absent** (no required reason; attendance is low-ceremony):

```tsx
const toggleAttendance = useMutation({
  mutationFn: (status: "present" | "absent") =>
    updateOccurrenceCoachAttendance(occurrenceId, {
      coach_id: actualCoachId ?? scheduledCoachId, status,
    }),
  onSuccess: onApplied,
});

<div className="flex gap-2">
  {(["present", "absent"] as const).map((s) => (
    <button key={s}
      className={`rounded border px-3 py-1 text-sm capitalize
        ${attendanceStatus === s ? "bg-primary text-primary-foreground" : ""}`}
      disabled={toggleAttendance.isPending}
      onClick={() => toggleAttendance.mutate(s)}>
      {s}
    </button>
  ))}
</div>
```

**Section B — Actual coach** (reason is **required** — disabled submit until non-empty):

```tsx
const [coachId, setCoachId] = useState(actualCoachId ?? scheduledCoachId);
const [coachReason, setCoachReason] = useState("");
const canSubmitCoach = coachId !== "" && coachReason.trim().length > 0;

const applyCoach = useMutation({
  mutationFn: () => updateSessionOccurrenceCoach(occurrenceId, {
    actual_coach_id: coachId, reason: coachReason,
  }),
  onSuccess: () => { setCoachReason(""); onApplied(); },
});

<select value={coachId} onChange={(e) => setCoachId(e.target.value)}>
  {coaches.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
</select>
<input type="text" placeholder="Reason (required)"
  value={coachReason} onChange={(e) => setCoachReason(e.target.value)}
  required aria-label="Reason for coach change" />
<button disabled={!canSubmitCoach || applyCoach.isPending}
  onClick={() => applyCoach.mutate()}>
  Apply coach change
</button>
```

**Section C — Replacement coach** (optional reason):

```tsx
const [replacementId, setReplacementId] = useState("");
const [replacementReason, setReplacementReason] = useState("");
const applyReplacement = useMutation({
  mutationFn: () => updateOccurrenceReplacement(occurrenceId, {
    replacement_coach_id: replacementId || null,
    reason: replacementReason || null,
  }),
  onSuccess: onApplied,
});
```

- [ ] **Step 2: Wire edit-guard into detail page**

In the line table in `[payoutId]/page.tsx`, make the "Correct" trigger conditional on draft status:

```tsx
{period.status === "draft" ? (
  <button
    className="text-muted-foreground hover:text-foreground"
    onClick={() => setCorrectingOccurrenceId(line.occurrence_id)}
    aria-label="Correct this line">
    <Pencil className="size-3.5" />
  </button>
) : (
  <span className="text-xs italic text-muted-foreground">
    {period.status === "approved" ? "Reopen to correct" : "Locked"}
  </span>
)}
```

When `period.status === "approved"` or `"paid"`, no edit control is shown. The existing **Reopen** button (in `Actions`) lets the admin transition back to draft.

`onApplied` triggers recompute and refreshes:

```tsx
const handleCorrectionApplied = async () => {
  const updated = await recomputePayoutPeriod(period.period_id);
  setCorrectingOccurrenceId(null);
  onChanged(updated);
};
```

- [ ] **Step 3: Note on audit entries**

Coach attendance writes go to the `coaching` context — they do NOT produce a `payout_audit_log` entry. The recompute that follows a correction produces a `"recomputed"` audit entry. This is by design and is verified in Phase 5 Task 5.2.

- [ ] **Step 4: Typecheck + lint + component tests**

Run: `cd frontend && npx tsc --noEmit && npx eslint "app/(admin)/admin/payouts"`

Write `CorrectionDrawer.test.tsx` asserting:
- With `period.status === "approved"`, the Pencil button is absent
- With `period.status === "draft"`, the Pencil button is present
- Coach-reason submit button is disabled when `coachReason` is empty string

- [ ] **Step 5: Commit**

```bash
git add "frontend/app/(admin)/admin/payouts"
git commit -m "feat(payroll): CorrectionDrawer (attendance/coach/replacement); edit-guard on approved/paid"
```

---

## Phase 5 — Tests & audit coverage

### Task 5.1: List/detail/preview parity regression

**Files:**
- Test: `backend/v2/tests/interface/test_admin_payroll_month.py`

- [ ] **Step 1: Add parity test** (locks the no-mismatch guarantee)

```python
@pytest.mark.asyncio
async def test_month_row_total_matches_detail_and_preview(admin_client, seed_occurrences_and_rates):
    # Before generation: all rows are previews (not_generated)
    pre = {r["coach_id"]: r for r in (await admin_client.get("/admin/payroll/2026-06")).json()["rows"]}
    assert all(r["status"] == "not_generated" for r in pre.values())

    await admin_client.post("/admin/payroll/2026-06/generate")

    post = {r["coach_id"]: r for r in (await admin_client.get("/admin/payroll/2026-06")).json()["rows"]}
    for coach_id, row in post.items():
        assert row["status"] != "not_generated"

        # List total == detail total — no list/detail mismatch
        detail = (await admin_client.get(f"/admin/payout-periods/{row['period_id']}")).json()
        assert row["total_amount_cents"] == detail["total_amount_cents"], (
            f"coach {coach_id}: list={row['total_amount_cents']} detail={detail['total_amount_cents']}"
        )

        # Preview total == persisted total — PayoutCalculator is idempotent
        assert pre[coach_id]["total_amount_cents"] == row["total_amount_cents"], (
            f"coach {coach_id}: preview={pre[coach_id]['total_amount_cents']} persisted={row['total_amount_cents']}"
        )
```

- [ ] **Step 2: Run → pass. Step 3: Commit**

```bash
git add backend/v2/tests/interface/test_admin_payroll_month.py
git commit -m "test(payroll): lock list/detail/preview total parity — no mismatch"
```

### Task 5.2: Correction → recompute → audit trail

**Files:**
- Create: `backend/v2/tests/interface/test_admin_payroll_corrections.py`

- [ ] **Step 1: Absence round-trip + audit confirmation**

```python
@pytest.mark.asyncio
async def test_absence_then_recompute_drops_line_and_audits(admin_client, seed_occurrences_and_rates):
    gen = await admin_client.post("/admin/payout-periods/generate", json={
        "coach_id": "coach-1",
        "period_start": "2026-06-01T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z",
    })
    assert gen.status_code == 200
    period = gen.json()
    pid = period["period_id"]
    occ_id = period["lines"][0]["occurrence_id"]
    before_total = period["total_amount_cents"]

    att = await admin_client.patch(
        f"/admin/session-occurrences/{occ_id}/coach-attendance",
        json={"coach_id": "coach-1", "status": "absent"},
    )
    assert att.status_code == 200

    after = (await admin_client.post(f"/admin/payout-periods/{pid}/recompute")).json()
    assert occ_id not in [line["occurrence_id"] for line in after["lines"]]
    assert after["total_amount_cents"] < before_total

    # Payout audit log: recomputed entry comes from RecomputePayoutPeriod.
    # The attendance PATCH goes to the coaching context and does NOT appear here.
    audit = (await admin_client.get(f"/admin/payout-periods/{pid}/audit")).json()
    assert any(e["action"] == "recomputed" for e in audit["entries"]), (
        "Expected 'recomputed' audit entry after attendance correction + recompute"
    )


@pytest.mark.asyncio
async def test_present_again_restores_total(admin_client, seed_occurrences_and_rates):
    gen = await admin_client.post("/admin/payout-periods/generate", json={
        "coach_id": "coach-1",
        "period_start": "2026-06-01T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z",
    })
    period = gen.json()
    pid = period["period_id"]
    occ_id = period["lines"][0]["occurrence_id"]
    original_total = period["total_amount_cents"]

    await admin_client.patch(
        f"/admin/session-occurrences/{occ_id}/coach-attendance",
        json={"coach_id": "coach-1", "status": "absent"},
    )
    await admin_client.post(f"/admin/payout-periods/{pid}/recompute")

    await admin_client.patch(
        f"/admin/session-occurrences/{occ_id}/coach-attendance",
        json={"coach_id": "coach-1", "status": "present"},
    )
    restored = (await admin_client.post(f"/admin/payout-periods/{pid}/recompute")).json()

    assert occ_id in [line["occurrence_id"] for line in restored["lines"]]
    assert restored["total_amount_cents"] == original_total

    audit = (await admin_client.get(f"/admin/payout-periods/{pid}/audit")).json()
    recomputed = [e for e in audit["entries"] if e["action"] == "recomputed"]
    assert len(recomputed) >= 2  # one per recompute call
```

- [ ] **Step 2: Run → pass. Step 3: Commit**

```bash
git add backend/v2/tests/interface/test_admin_payroll_corrections.py
git commit -m "test(payroll): absence/present round-trip + audit trail confirmation"
```

### Task 5.3: Full suite gate

- [ ] **Step 1: Backend**

Run: `cd backend && pytest && ruff check .`
Expected: all green.

- [ ] **Step 2: Frontend**

Run: `cd frontend && npx tsc --noEmit && npx eslint . && npx vitest run`
Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore(payroll): suite green — coach payroll month-first workflow complete"
```

---

## Self-Review

**10 required changes — all addressed:**

| # | Requirement | Where |
|---|-------------|-------|
| 1 | Split by phase | Phases 0–5, each self-contained with a gate |
| 2 | Phase 0 audit first | Phase 0 updated with actual results (4/4/0) |
| 3 | No UI until rates verified | Phase 0 backfill gate + Phase 2 gate note |
| 4 | Confirm exact API route prefix | `/admin/payroll/{month}` confirmed; `router.py:26` cited |
| 5 | Tenant scoping on every query | `academy_id=claims.academy_id` shown in every route handler |
| 6 | Old links not breaking | Task 2.6 Step 3: 404 → redirect to `/admin/payouts` |
| 7 | Missing-data warning cards | Task 2.6 Step 2: yellow card when session_count>0 && total==0 |
| 8 | Prevent edits on approved/paid | Task 4.2 Step 2: pencil hidden; "Reopen to correct" hint shown |
| 9 | Require reason for corrections | Task 4.2 Step 1: `canSubmitCoach` guard + `required` attribute |
| 10 | Confirm audit entries | Architecture Decision 7; Task 5.2 with assertion comment |

**Spec coverage (13-step flow):**
1→Task 2.6 list page | 2→MonthPicker | 3+4→Tasks 2.3/2.4 | 5→row nav to period_id | 6→existing line table | 7+8+9→Task 4.2 drawer | 10→existing recompute + `handleCorrectionApplied` | 11→existing approve button | 12→Phase 1 mark-paid | 13→Task 2.4 export route + Task 2.6 "Export month" button. ✅ All 13 covered.

**Type consistency:** `MonthlyPayrollRow.total_minor` → `AdminMonthlyPayrollRow.total_amount_cents` → TS `total_amount_cents` (follows existing `amount_minor→amount_cents` convention). `status` values `not_generated|draft|approved|paid` consistent across use case, view, and TS. `BulkGenerateResult{generated,skipped}` / `BulkRecomputeResult{recomputed,skipped}` → `BulkPayrollResultView` → TS `BulkPayrollResult`. `MarkPayoutPaidInput.amount_cents` matches backend `MarkPayoutPeriodPaidRequest.amount_cents`.
