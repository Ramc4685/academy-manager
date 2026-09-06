# Payments Buckets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the admin Payments page into a six-bucket "work the money list" fed by one backend read model that reuses the autopay worker's own eligibility checks; keep the old invoice table under an "All invoices" tab.

**Architecture:** A pure `autopay_eligibility` module (application layer) is extracted from the dunning repository and the charge use case, and both the worker and the new `MongoCollectionsReadModel` (infrastructure) call it. Pure bucket rules live in `application/collections_buckets.py`; the read model only fetches facts in a fixed number of batched Mongo queries. A new composition module wires the read model onto `app.state.admin_collections` (no change to `composition/admin.py`); a new admin interface route exposes `GET /admin/payments/collections`. The frontend gets one money formatter (`lib/money.ts`), one invoice status vocabulary (`lib/billing-status.ts`), a bucket page, and three dashboard tiles fed by the same totals.

**Tech Stack:** FastAPI + Motor (mongomock-motor in tests), Pydantic v2, pytest-asyncio; Next.js 15 App Router, React 19, TanStack Query, Tailwind, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-05-payments-buckets-design.md` (read it first).

## Global Constraints

- Worktree: `/Users/ramc/Documents/Code/academy-manager/.worktrees/payments-buckets`, branch `feat/payments-buckets`. Run backend commands from `backend/` with `.venv/bin/pytest` (`.venv` is a symlink). Run frontend commands from `frontend/` with `pnpm`.
- `backend/v2/composition/admin.py` is at 4797/4800 lines. **Do not edit it.** New wiring goes in `backend/v2/composition/collections.py`, attached in `backend/v2/main.py`.
- Tenancy: read `current_academy_id()` at request time inside repositories/read models. Never capture an academy id at composition time. Scope every Mongo query with `"academy_id": academy_id`.
- Layering (import-linter): domain imports nothing from application/infrastructure; application never imports infrastructure; interfaces never import infrastructure or domain directly; contexts/shared never import composition.
- No new write endpoints. Row actions call: `POST /admin/dues-reminders`, `POST /admin/billing/invoices/{id}/record-payment`, `POST /admin/enrollments/{id}/resume`, `POST /admin/billing/invoices/{id}/void`.
- The bucket rules and their order are exactly spec §2. Actions per bucket: failed_autopay → `["message","record_payment"]`; past_due, awaiting → `["send_reminder","record_payment"]`; autopay_scheduled → `["skip_month"]`; paused → `["resume"]`; paid → `[]`.
- Invoice status vocabulary in the UI: `draft | open | partially_paid | paid | void`. Map `succeeded/refunded/partially_refunded → paid`, `pending/failed → open`, `waived/cancelled/expired → void`.
- One money formatter: `formatCents` in `frontend/lib/money.ts`.
- Existing e2e stubs match `**/api/v2/admin/payments*` and return `{ payments: [] }` for EVERY payments URL, including the new `/admin/payments/collections`. The page MUST render (empty tiles + "No …" lines) with no console errors when the response has no `buckets`.
- Commit after every task with a conventional message ending in `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Never `git stash`, `--amend`, or `rebase`.
- Release note file `docs/release-notes/2026-09-05-feat-payments-buckets.md` with sections `## What changed`, `## Deploy notes`, `## Risk / rollback` and the real PR number (added after the PR exists).

## File Structure

Backend (create):
- `backend/v2/contexts/billing/application/autopay_eligibility.py` — pure predicates: `invoice_is_chargeable`, `ladder_eligibility`, `autopay_eligibility`, `Eligibility`.
- `backend/v2/contexts/billing/application/collections_buckets.py` — pure bucket classification over plain fact dataclasses; `classify_family`, `build_collections_view`.
- `backend/v2/contexts/billing/infrastructure/collections_read_model.py` — `MongoCollectionsReadModel.build(period, debug)`; batched Mongo reads, calls the pure classifier.
- `backend/v2/composition/collections.py` — `compose_admin_collections(db)`.
- `backend/v2/interfaces/admin/collections_routes.py` — `GET /payments/collections`, `get_admin_collections` dependency.
- `backend/v2/interfaces/admin/collections_views.py` — Pydantic response models.
- Tests: `backend/v2/tests/unit/test_autopay_eligibility.py`, `backend/v2/tests/unit/test_collections_buckets.py`, `backend/v2/tests/contract/test_collections_read_model.py`, `backend/v2/tests/interface/test_admin_collections_routes.py`.

Backend (modify):
- `backend/v2/contexts/billing/infrastructure/mongo_dunning_state_repo.py` — `_prepare_batch`, `_invoice_chargeable`, `claim_next_due` autopay check call the extracted predicates.
- `backend/v2/contexts/billing/application/use_cases/charge_invoice_via_autopay.py` — guards use the extracted constants/predicates.
- `backend/v2/interfaces/admin/router.py` — include the new router.
- `backend/v2/main.py` — attach `app.state.admin_collections`.

Frontend (create):
- `frontend/lib/money.ts`, `frontend/lib/money.test.ts`
- `frontend/lib/billing-status.ts`, `frontend/lib/billing-status.test.ts`
- `frontend/app/(admin)/admin/payments/buckets/bucket-view.ts`, `bucket-view.test.ts`
- `frontend/app/(admin)/admin/payments/buckets/CollectionsTab.tsx`
- `frontend/app/(admin)/admin/payments/buckets/RecordPaymentDialog.tsx`
- `frontend/app/(admin)/admin/payments/AllInvoicesTab.tsx` (the current page body, moved)
- `frontend/e2e/specs/admin-payments-buckets.spec.ts`

Frontend (modify):
- `frontend/lib/api/admin.ts` (types + `getAdminCollections`), `frontend/lib/query/keys.ts`
- `frontend/app/(admin)/admin/payments/page.tsx` (tabs shell), `format.ts` (delegate formatters/status)
- `frontend/app/(admin)/admin/page.tsx` (dashboard tiles)
- `frontend/app/(admin)/admin/messages/page.tsx` (`?dm=<parent_id>` prefill)
- `frontend/components/admin/screen-meta.ts` (subtitle)
- `frontend/e2e/specs/admin-shell.spec.ts`, `billing-trust-recovery.spec.ts` (tab + vocabulary updates)

---
### Task 1: Extract `autopay_eligibility` and make the worker use it

**Files:**
- Create: `backend/v2/contexts/billing/application/autopay_eligibility.py`
- Modify: `backend/v2/contexts/billing/infrastructure/mongo_dunning_state_repo.py` (`_prepare_batch` ~L144-216, `claim_next_due` autopay check ~L270-276, `_invoice_chargeable` ~L555)
- Modify: `backend/v2/contexts/billing/application/use_cases/charge_invoice_via_autopay.py` (`_CHARGEABLE_STATUSES`, `_AUTOPAY_ELIGIBLE_STATUS`, guards at L185-262)
- Test: `backend/v2/tests/unit/test_autopay_eligibility.py`

**Interfaces:**
- Produces:
  ```python
  CHARGEABLE_INVOICE_STATUSES: frozenset[str]  # {"open", "partially_paid"}
  AUTOPAY_ACTIVE_STATUS = "active"
  EligibilityStatus = Literal["eligible", "ineligible", "unknown"]
  @dataclass(frozen=True) class Eligibility: status: EligibilityStatus; reason: str | None; eligible -> bool (property)
  def invoice_is_chargeable(status: str | None, balance_due_cents: int) -> bool
  def ladder_eligibility(*, invoice_status, balance_due_cents, enrollment_id, autopay_enrollment_status) -> Eligibility
  def autopay_eligibility(*, invoice_status, balance_due_cents, enrollment_id, autopay_enrollment_status, has_payment_method: bool | None, connected_account_ready: bool | None) -> Eligibility
  ```
  Reasons, in evaluation order: `invoice_not_chargeable`, `no_balance`, `no_enrollment`, `autopay_not_active`, then (autopay_eligibility only) `card_state_unknown` (has_payment_method is None), `no_card_on_file`, `connected_account_unknown` (None), `connected_account_not_ready`.

- [ ] **Step 1: Write the failing unit tests**

`backend/v2/tests/unit/test_autopay_eligibility.py`:
```python
from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.autopay_eligibility import (
    AUTOPAY_ACTIVE_STATUS,
    CHARGEABLE_INVOICE_STATUSES,
    autopay_eligibility,
    invoice_is_chargeable,
    ladder_eligibility,
)


def _eligible(**overrides):
    kwargs = dict(
        invoice_status="open",
        balance_due_cents=7000,
        enrollment_id="enr-1",
        autopay_enrollment_status=AUTOPAY_ACTIVE_STATUS,
        has_payment_method=True,
        connected_account_ready=True,
    )
    kwargs.update(overrides)
    return autopay_eligibility(**kwargs)


def test_constants_match_worker_vocabulary() -> None:
    assert CHARGEABLE_INVOICE_STATUSES == frozenset({"open", "partially_paid"})
    assert AUTOPAY_ACTIVE_STATUS == "active"


@pytest.mark.parametrize(
    ("status", "balance", "expected"),
    [("open", 1, True), ("partially_paid", 1, True), ("paid", 1, False),
     ("void", 1, False), ("draft", 1, False), ("open", 0, False), (None, 1, False)],
)
def test_invoice_is_chargeable(status, balance, expected) -> None:
    assert invoice_is_chargeable(status, balance) is expected


def test_fully_eligible() -> None:
    result = _eligible()
    assert result.status == "eligible" and result.eligible and result.reason is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"invoice_status": "void"}, "invoice_not_chargeable"),
        ({"invoice_status": "draft"}, "invoice_not_chargeable"),
        ({"balance_due_cents": 0}, "no_balance"),
        ({"enrollment_id": None}, "no_enrollment"),
        ({"enrollment_id": ""}, "no_enrollment"),
        ({"autopay_enrollment_status": "paused"}, "autopay_not_active"),
        ({"autopay_enrollment_status": None}, "autopay_not_active"),
        ({"has_payment_method": False}, "no_card_on_file"),
        ({"connected_account_ready": False}, "connected_account_not_ready"),
    ],
)
def test_ineligible_reasons_in_order(overrides, reason) -> None:
    result = _eligible(**overrides)
    assert result.status == "ineligible"
    assert result.reason == reason
    assert not result.eligible


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [({"has_payment_method": None}, "card_state_unknown"),
     ({"connected_account_ready": None}, "connected_account_unknown")],
)
def test_unknown_card_or_account_is_unknown_not_eligible(overrides, reason) -> None:
    result = _eligible(**overrides)
    assert result.status == "unknown"
    assert result.reason == reason
    assert not result.eligible


def test_invoice_problems_win_over_unknown_card_state() -> None:
    result = _eligible(invoice_status="paid", has_payment_method=None)
    assert result.status == "ineligible" and result.reason == "invoice_not_chargeable"


def test_ladder_eligibility_is_the_prepare_predicate() -> None:
    ok = ladder_eligibility(
        invoice_status="open", balance_due_cents=1, enrollment_id="e", autopay_enrollment_status="active"
    )
    assert ok.eligible
    assert not ladder_eligibility(
        invoice_status="open", balance_due_cents=1, enrollment_id="e", autopay_enrollment_status="offered"
    ).eligible
    assert ladder_eligibility(
        invoice_status="open", balance_due_cents=1, enrollment_id=None, autopay_enrollment_status="active"
    ).reason == "no_enrollment"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest v2/tests/unit/test_autopay_eligibility.py -q`
Expected: ImportError (module missing).

- [ ] **Step 3: Implement the module**

`backend/v2/contexts/billing/application/autopay_eligibility.py`:
```python
"""Autopay eligibility — the ONE definition of "the worker would charge this invoice".

Both the dunning worker (``MongoDunningStateRepository.prepare_due_states`` /
``claim_next_due``, ``ChargeInvoiceViaAutopay``) and the admin collections read
model call these predicates. Never re-implement them; the Payments page must
not promise a charge the worker will skip (spec 2026-09-05 §2.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CHARGEABLE_INVOICE_STATUSES: frozenset[str] = frozenset({"open", "partially_paid"})
AUTOPAY_ACTIVE_STATUS = "active"

EligibilityStatus = Literal["eligible", "ineligible", "unknown"]


@dataclass(frozen=True)
class Eligibility:
    status: EligibilityStatus
    reason: str | None = None

    @property
    def eligible(self) -> bool:
        return self.status == "eligible"


ELIGIBLE = Eligibility("eligible")


def invoice_is_chargeable(status: str | None, balance_due_cents: int) -> bool:
    return status in CHARGEABLE_INVOICE_STATUSES and balance_due_cents > 0


def ladder_eligibility(
    *,
    invoice_status: str | None,
    balance_due_cents: int,
    enrollment_id: str | None,
    autopay_enrollment_status: str | None,
) -> Eligibility:
    """The conditions ``prepare_due_states`` applies before opening a ladder."""
    if invoice_status not in CHARGEABLE_INVOICE_STATUSES:
        return Eligibility("ineligible", "invoice_not_chargeable")
    if balance_due_cents <= 0:
        return Eligibility("ineligible", "no_balance")
    if not enrollment_id:
        return Eligibility("ineligible", "no_enrollment")
    if autopay_enrollment_status != AUTOPAY_ACTIVE_STATUS:
        return Eligibility("ineligible", "autopay_not_active")
    return ELIGIBLE


def autopay_eligibility(
    *,
    invoice_status: str | None,
    balance_due_cents: int,
    enrollment_id: str | None,
    autopay_enrollment_status: str | None,
    has_payment_method: bool | None,
    connected_account_ready: bool | None,
) -> Eligibility:
    """Ladder conditions plus the charge-time guards of ``ChargeInvoiceViaAutopay``.

    ``None`` for the card or connected-account state means "could not be
    determined" and yields ``unknown`` — never ``eligible`` (spec §6).
    """
    ladder = ladder_eligibility(
        invoice_status=invoice_status,
        balance_due_cents=balance_due_cents,
        enrollment_id=enrollment_id,
        autopay_enrollment_status=autopay_enrollment_status,
    )
    if not ladder.eligible:
        return ladder
    if has_payment_method is None:
        return Eligibility("unknown", "card_state_unknown")
    if not has_payment_method:
        return Eligibility("ineligible", "no_card_on_file")
    if connected_account_ready is None:
        return Eligibility("unknown", "connected_account_unknown")
    if not connected_account_ready:
        return Eligibility("ineligible", "connected_account_not_ready")
    return ELIGIBLE
```

- [ ] **Step 4: Run unit tests → PASS**

Run: `cd backend && .venv/bin/pytest v2/tests/unit/test_autopay_eligibility.py -q`

- [ ] **Step 5: Make the worker call the predicates (pure extraction)**

In `mongo_dunning_state_repo.py`:
1. Add import: `from backend.v2.contexts.billing.application.autopay_eligibility import (AUTOPAY_ACTIVE_STATUS, invoice_is_chargeable, ladder_eligibility)`.
2. In `prepare_due_states`, extend the projection to `{"invoice_id": 1, "parent_id": 1, "enrollment_id": 1, "due_date": 1, "status": 1, "balance_due_cents": 1}`.
3. In `_prepare_batch`, the `autopay_active` query keeps `"autopay_enrollment_status": AUTOPAY_ACTIVE_STATUS`. Replace
   ```python
   enrollment_id = str(invoice_doc["enrollment_id"])
   if enrollment_id not in autopay_active:
       continue
   ```
   with
   ```python
   enrollment_id = str(invoice_doc["enrollment_id"])
   eligibility = ladder_eligibility(
       invoice_status=invoice_doc.get("status"),
       balance_due_cents=int(invoice_doc.get("balance_due_cents") or 0),
       enrollment_id=enrollment_id,
       autopay_enrollment_status=(
           AUTOPAY_ACTIVE_STATUS if enrollment_id in autopay_active else None
       ),
   )
   if not eligibility.eligible:
       continue
   ```
4. In `claim_next_due`, replace `enrollment.get("autopay_enrollment_status") != "active"` with `enrollment.get("autopay_enrollment_status") != AUTOPAY_ACTIVE_STATUS`.
5. Replace the body of `_invoice_chargeable` with:
   ```python
   if invoice_doc is None:
       return False
   return invoice_is_chargeable(
       invoice_doc.get("status"), int(invoice_doc.get("balance_due_cents") or 0)
   )
   ```

In `charge_invoice_via_autopay.py`:
1. Import `AUTOPAY_ACTIVE_STATUS, CHARGEABLE_INVOICE_STATUSES, invoice_is_chargeable` from the new module.
2. Delete the local `_AUTOPAY_ELIGIBLE_STATUS = "active"` and `_CHARGEABLE_STATUSES = frozenset(...)`; replace every use with the imported names (`_CHARGEABLE_STATUSES` appears in the guard message and two status checks; `fresh.status not in _CHARGEABLE_STATUSES or fresh.balance_due_cents <= 0` becomes `not invoice_is_chargeable(fresh.status, fresh.balance_due_cents)`).
3. Keep every branch and every message otherwise identical.

- [ ] **Step 6: Existing worker tests stay green**

Run: `cd backend && .venv/bin/pytest v2/tests/contract/test_dunning_state_repo.py v2/tests/unit/test_charge_autopay_use_case.py v2/tests/application/test_dunning_worker.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/v2/contexts/billing/application/autopay_eligibility.py backend/v2/contexts/billing/infrastructure/mongo_dunning_state_repo.py backend/v2/contexts/billing/application/use_cases/charge_invoice_via_autopay.py backend/v2/tests/unit/test_autopay_eligibility.py
git commit -m "refactor(billing): extract autopay eligibility predicates shared by the dunning worker

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 2: Pure bucket classifier (`collections_buckets.py`)

**Files:**
- Create: `backend/v2/contexts/billing/application/collections_buckets.py`
- Test: `backend/v2/tests/unit/test_collections_buckets.py`

**Interfaces:**
- Consumes: `autopay_eligibility`, `Eligibility` from Task 1.
- Produces (all plain dataclasses, no Mongo):
  ```python
  BUCKET_ORDER = ("failed_autopay", "past_due", "awaiting", "autopay_scheduled", "paused", "paid")
  BUCKET_ACTIONS: dict[str, list[str]]
  MAX_AUTOPAY_ATTEMPTS = 4

  @dataclass(frozen=True) class InvoiceFacts:
      invoice_id: str; invoice_number: str | None; period: str; status: str; total_cents: int
      balance_due_cents: int; due_date: date; delivery_status: str; last_sent_at: datetime | None
      enrollment_id: str | None; student_id: str | None
      autopay_enrollment_status: str | None      # from student_billing_enrollments
      dunning_status: str | None                 # dunning_states.status
      dunning_attempt_count: int; dunning_next_attempt_at: datetime | None
      latest_attempt_status: str | None; latest_attempt_reason: str | None
      paid_cents: int; paid_method: str | None; paid_at: datetime | None   # from allocations
  @dataclass(frozen=True) class StudentFacts: student_id: str; name: str; session_title: str | None
  @dataclass(frozen=True) class PauseFacts: enrollment_id: str; student_name: str; session_title: str | None; resume_on: date | None; review_on: date | None
  @dataclass(frozen=True) class FamilyFacts:
      parent_id: str; parent_name: str | None; parent_email: str | None
      students: tuple[StudentFacts, ...]; invoices: tuple[InvoiceFacts, ...]   # this period, non-void
      leftover_balance_cents: int; paused: tuple[PauseFacts, ...]
      has_payment_method: bool | None; card_last4: str | None; connected_account_ready: bool | None
  @dataclass(frozen=True) class FamilyRow: bucket: str; payload: dict[str, Any]   # payload == spec family JSON

  def classify_family(family: FamilyFacts, *, today: date) -> FamilyRow | None   # None → no bucket
  def build_collections_view(families: Iterable[FamilyFacts], *, period: str, today: date, timezone: str, generated_at: datetime, unclassified: list[dict] | None = None) -> dict[str, Any]
  ```

Rules (spec §2, evaluated top to bottom on the family's period invoices with status in `{open, partially_paid}` and balance > 0, called "owing"; `draft` invoices with balance count as owing for buckets 2/3 only):
1. `failed_autopay`: any owing invoice with `dunning_status in {"active","processing"} and dunning_attempt_count >= 1`, or `dunning_status == "dunned"`.
2. `past_due`: any owing invoice whose eligibility is not `eligible` and `due_date < today`.
3. `awaiting`: any owing invoice whose eligibility is not `eligible` and `due_date >= today`.
4. `autopay_scheduled`: any owing invoice with eligibility `eligible` (a failed attempt this period was already caught by rule 1).
5. `paused`: `family.paused` non-empty.
6. `paid`: `family.invoices` non-empty.
Otherwise `None`.

Payload (per spec response shape) — `balance_cents` = sum of owing balances this period; `autopay` = `{"status": eligibility.status or reason string, "card_last4", "charge_on": due_date iso of the earliest owing invoice, "notice_sent_at": last_sent_at iso}` for autopay_scheduled and for owing rows whose autopay status is active but ineligible/unknown (so the UI can show "no card on file" / "autopay status unavailable"); else `None`. `failure` = `{"reason": latest_attempt_reason, "attempt_count", "max_attempts": 4, "next_retry_on": next_attempt_at date iso or None, "disabled": dunning_status == "dunned"}`. `pause` = first paused row as `{"enrollment_id","resume_on","review_on","session_title","student_name"}`. `paid` = `{"amount_cents": sum paid_cents, "method": latest paid_method, "paid_at": latest paid_at iso}` when any invoice has `paid_cents > 0`, else, for the paid bucket, `{"amount_cents": sum(total-balance), "method": None, "paid_at": None}`. `last_reminder_at` = max `last_sent_at` over owing invoices. `actions` = `BUCKET_ACTIONS[bucket]`.

Totals: `owed_cents` = Σ balance_cents over buckets 1–3; `autopay_scheduled_cents/count` = bucket 4; `needs_action_count` = count(bucket 1) + count(bucket 2); `collected_cents` = Σ `paid.amount_cents` over all rows that have `paid` (paid_cents from allocations count in any bucket).

- [ ] **Step 1: Write failing tests** covering: one family per bucket; failed beats autopay; two students one row; paused family with leftover; a family with only a void invoice → `None`; autopay active but no card → awaiting with `autopay.status == "no_card_on_file"`; unknown card → awaiting with `"card_state_unknown"`; past due days computed by caller (row carries `due_date`); `build_collections_view` orders buckets by `BUCKET_ORDER`, includes empty buckets with `count 0`, computes totals, and only includes `unclassified` when passed.

- [ ] **Step 2: Run → fail (ImportError). Step 3: implement. Step 4: run → pass.**

Run: `cd backend && .venv/bin/pytest v2/tests/unit/test_collections_buckets.py -q`

- [ ] **Step 5: Commit** `feat(billing): pure bucket classifier for the admin collections view`

---

### Task 3: `MongoCollectionsReadModel` + mongomock contract tests

**Files:**
- Create: `backend/v2/contexts/billing/infrastructure/collections_read_model.py`
- Test: `backend/v2/tests/contract/test_collections_read_model.py`

**Interfaces:**
- Consumes: Task 1 & 2; `MongoConnectedAccountRepository.get_for_academy()` (→ `ConnectedAccount.is_ready_for_charges()`), `MongoBillingSettingsRepository.get()` (→ `.allow_platform_charge_fallback`), `MongoParentBillingCustomerRepository.list_academy_customers()` + `display_payment_method(doc)`, `exclude_non_charge_attempts`, `academy_timezone_lookup`, `current_academy_id`.
- Produces:
  ```python
  class MongoCollectionsReadModel:
      def __init__(self, db, *, academy_timezone: Callable[[str], Awaitable[str | None]], connected_accounts, billing_settings, customers, clock=lambda: datetime.now(UTC)) -> None
      async def build(self, period: str | None = None, *, debug: bool = False) -> dict[str, Any]
  ```
  `period=None` → current month in the academy timezone (UTC when unset). `today` = local date. Result is the dict from `build_collections_view`.

Queries (all scoped by `academy_id = current_academy_id()`), in this order and no per-family loops:
1. `invoices` `{period: P, status: {$ne: "void"}, is_deleted: {$ne: True}}` projecting the fields in `InvoiceFacts` plus `parent_id`, `parent_user_id`.
2. `invoices` `{period: {$lt: P}, status: {$in: ["open","partially_paid"]}, balance_due_cents: {$gt: 0}}` → leftover per parent.
3. `dunning_states` `{invoice_id: {$in: ids}}`.
4. `payment_attempts` aggregate: `exclude_non_charge_attempts({academy_id, invoice_id: {$in: ids}})` → `$sort {created_at: -1, attempt_id: -1}` → `$group {_id: "$invoice_id", status: {$first: "$status"}, reason: {$first: {$ifNull: ["$failure_message", "$failure_code"]}}}`.
5. `student_billing_enrollments` `{enrollment_id: {$in: enrollment_ids}}` → autopay status.
6. `enrollments` `{status: "paused"}` (whole tenant, projection `enrollment_id, student_id, session_id`) → paused per student; `enrollment_billing_deferrals` `{enrollment_id: {$in: paused_ids}}` sorted `created_at desc` → resume_on / review_on (first per enrollment).
7. `students` by `parent_id in parents ∪ paused parents` (projection `student_id, parent_id, full_name`); `enrollments` `{student_id: {$in: ...}, status: {$in: ["active","paused"]}}` → session per student; `sessions` `{session_id: {$in}}` projection `title, name`.
8. `users` `{user_id: {$in: parent_ids}}` projection `display_name, name, email` (fall back to `_id` string match only if `user_id` misses nothing — check `mongo_user_repo.py` for the id field and use the same).
9. `payment_allocations` `{invoice_id: {$in: ids}}` then `ledger_payments` `{payment_id: {$in}}` → per invoice `paid_cents` (Σ allocations), `paid_method`/`paid_at` from the latest payment (`paid_at` desc).
10. `customers.list_academy_customers()` → `has_payment_method`, `card_last4` via `display_payment_method`. `connected_accounts.get_for_academy()` + `billing_settings.get()` once → `connected_account_ready = account is not None and account.is_ready_for_charges() or settings.allow_platform_charge_fallback`. Wrap steps 10 in `try/except Exception` → `None` (unknown) with a `log.warning`.

Families = parents from step 1 ∪ parents of paused students. A row that raises inside `classify_family` (bad data) is caught, logged, and appended to `unclassified` as `{"parent_id", "error"}`.

- [ ] **Step 1: Write failing contract tests** (`db`, `acad`, `other_acad` fixtures from `tests/contract/conftest.py`; seed helpers modelled on `test_dunning_state_repo.py::_seed_invoice`). Fix `clock` to `datetime(2026, 9, 10, 15, 0, tzinfo=UTC)`, seed `academies` with `{"academy_id": acad, "timezone": "America/Chicago"}`. Cases: (a) one family per bucket → each bucket count 1 and correct key; (b) two students, one autopay-eligible and one past due → single row in past_due with two students; (c) paused family with a prior-month open invoice → paused bucket, `leftover_balance_cents` set; (d) voided invoice excluded entirely; (e) autopay active, no customer card → awaiting with `autopay.status == "no_card_on_file"`; (f) prior-month open invoice → counted as leftover, not in period buckets; (g) tenant isolation: rows for `other_acad` never appear; (h) `period=None` resolves to `"2026-09"`; (i) a family whose invoice has no parent lands in `unclassified` only when `debug=True` and the build still returns.

- [ ] **Step 2: Run → fail. Step 3: implement. Step 4: run → pass.**

Run: `cd backend && .venv/bin/pytest v2/tests/contract/test_collections_read_model.py -q`

- [ ] **Step 5: Commit** `feat(billing): Mongo collections read model for the Payments buckets`

---

### Task 4: Composition, route, interface tests, and the worker/read-model invariant test

**Files:**
- Create: `backend/v2/composition/collections.py`, `backend/v2/interfaces/admin/collections_views.py`, `backend/v2/interfaces/admin/collections_routes.py`
- Modify: `backend/v2/interfaces/admin/router.py` (include `collections_router` before `billing_router`), `backend/v2/main.py` (after `app.state.admin = compose_admin(...)` add `app.state.admin_collections = compose_admin_collections(db)` + import)
- Test: `backend/v2/tests/interface/test_admin_collections_routes.py`, add `test_worker_and_read_model_classify_seeded_invoices_identically` to `backend/v2/tests/contract/test_collections_read_model.py`

**Interfaces:**
```python
# composition/collections.py
def compose_admin_collections(db: Any) -> MongoCollectionsReadModel   # timezone via academy_timezone_lookup(db); repos: MongoConnectedAccountRepository(db), MongoBillingSettingsRepository(db), MongoParentBillingCustomerRepository(db)

# interfaces/admin/collections_routes.py
class AdminCollectionsReader(Protocol):
    async def build(self, period: str | None = None, *, debug: bool = False) -> dict[str, Any]: ...
def get_admin_collections(request: Request) -> AdminCollectionsReader: return request.app.state.admin_collections
router = APIRouter(tags=["admin.collections"])
@router.get("/payments/collections", response_model=AdminCollectionsView)
async def payments_collections(period: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), debug: bool = Query(default=False), _claims = Depends(require_persona("admin")), reader = Depends(get_admin_collections)) -> AdminCollectionsView
```
Views (`collections_views.py`, Pydantic, `extra="ignore"`): `AdminCollectionsTotals`, `AdminCollectionsStudent`, `AdminCollectionsInvoice`, `AdminCollectionsAutopay`, `AdminCollectionsFailure`, `AdminCollectionsPause`, `AdminCollectionsPaid`, `AdminCollectionsFamily`, `AdminCollectionsBucket`, `AdminCollectionsView` (`period, generated_at, timezone, totals, buckets, unclassified: list[dict] | None = None`). Field names exactly as the spec §3 JSON.

- [ ] **Step 1: Interface tests (failing first).** Build the app the way `tests/interface/conftest.py::_make_admin_app` does but override `get_admin_collections` with a fake whose `build` records its args and returns a minimal valid dict. Tests: admin → 200 and `body["buckets"][0]["key"] == "failed_autopay"`; coach → 404; `period=2026-13` → 422; no period → fake called with `period=None`; `debug=1` → `debug=True`.
- [ ] **Step 2: Implement views, route, composition, router include, `main.py` attach.** Run the interface tests → pass. Run `cd backend && .venv/bin/pytest v2/tests/structural v2/tests/test_no_raw_tenant_mongo_access.py -q` (the read model reads several collections with an explicit `academy_id` filter; if the raw-access test flags it, follow the allow-list mechanism that test documents).
- [ ] **Step 3: Invariant test.** In the contract file: seed 6 invoices all due `2026-09-10` for distinct parents/enrollments, each with a customer card and a ready connected account (`academy_connected_accounts` doc with `status: "active", charges_enabled: True`): 3 with `autopay_enrollment_status: "active"`, 1 `paused`, 1 with no `enrollment_id`, 1 `partially_paid` with `balance_due_cents: 0`. Run `MongoDunningStateRepository(db, academy_timezone=lookup).prepare_due_states(now=clock(), limit=100)` → set A = invoice_ids in `dunning_states`. Run `build("2026-09")` → set B = invoice_ids in the `autopay_scheduled` bucket. Assert `A == B == {the 3 active}`.
- [ ] **Step 4: Full backend suite, import-linter, mypy**

```bash
cd backend && .venv/bin/pytest -q -x
cd backend && PYTHONPATH=.. .venv/bin/lint-imports --config pyproject.toml
cd <repo root> && backend/.venv/bin/mypy --config-file backend/pyproject.toml -p backend.v2 | backend/.venv/bin/mypy-baseline filter --baseline-path backend/mypy-baseline.txt --allow-unsynced
```
- [ ] **Step 5: Commit** `feat(admin): GET /admin/payments/collections wired through composition/collections.py`

---
### Task 5: Frontend foundations — money, status vocabulary, API client

**Files:**
- Create: `frontend/lib/money.ts`, `frontend/lib/money.test.ts`, `frontend/lib/billing-status.ts`, `frontend/lib/billing-status.test.ts`
- Modify: `frontend/lib/api/admin.ts`, `frontend/lib/query/keys.ts`, `frontend/app/(admin)/admin/payments/format.ts`

**Interfaces (produces):**
```ts
// lib/money.ts
export function formatCents(cents: number, opts?: { whole?: boolean }): string   // "$1,110.00"; whole → "$1,110"
export function formatDateOnly(value: string | null | undefined): string          // "Sep 8, 2026" from "2026-09-08", "—" when empty
// lib/billing-status.ts
export type InvoiceStatus = "draft" | "open" | "partially_paid" | "paid" | "void";
export function normalizeInvoiceStatus(raw: string | null | undefined): InvoiceStatus   // mapping in Global Constraints; unknown → "open"
export function invoiceStatusChip(raw: string | null | undefined): { variant: ChipVariant; label: string }
   // draft→{draft,"DRAFT"} open→{pending,"OPEN"} partially_paid→{partial,"PARTIALLY PAID"} paid→{paid,"PAID"} void→{waived,"VOID"}
// lib/api/admin.ts
export type CollectionsBucketKey = "failed_autopay"|"past_due"|"awaiting"|"autopay_scheduled"|"paused"|"paid";
export type CollectionsAction = "send_reminder"|"record_payment"|"message"|"skip_month"|"resume";
export interface AdminCollectionsFamily { parent_id: string; parent_name: string|null; parent_email: string|null; students: {student_id:string; name:string; session_title:string|null}[]; invoices: {invoice_id:string; invoice_number:string|null; period:string; status:string; total_cents:number; balance_due_cents:number; due_date:string; delivery_status:string}[]; balance_cents:number; leftover_balance_cents:number; autopay: {status:string; card_last4:string|null; charge_on:string|null; notice_sent_at:string|null}|null; failure: {reason:string|null; attempt_count:number; max_attempts:number; next_retry_on:string|null; disabled:boolean}|null; pause: {enrollment_id:string; resume_on:string|null; review_on:string|null; session_title:string|null; student_name:string}|null; paid: {amount_cents:number; method:string|null; paid_at:string|null}|null; last_reminder_at:string|null; actions: CollectionsAction[] }
export interface AdminCollectionsBucket { key: CollectionsBucketKey; count: number; total_cents: number; families: AdminCollectionsFamily[] }
export interface AdminCollectionsView { period: string; generated_at: string; timezone: string; totals: { owed_cents:number; autopay_scheduled_cents:number; autopay_scheduled_count:number; needs_action_count:number; collected_cents:number }; buckets: AdminCollectionsBucket[] }
export function getAdminCollections(period?: string): Promise<AdminCollectionsView>   // GET /admin/payments/collections?period=
// lib/query/keys.ts: collections: (period: string) => ["admin", "payments", "collections", period] as const
```
`payments/format.ts`: re-export `formatCents` from `@/lib/money`; make `statusChip(status)` return `invoiceStatusChip(status)`; delete the local `STATUS_CHIP` map; remove `{ value: "succeeded" }` from `STATUS_FILTER_OPTIONS`.

- [ ] Step 1: write `money.test.ts` and `billing-status.test.ts` (vitest, every mapping row) → `pnpm vitest run lib` fails. Step 2: implement. Step 3: pass. Step 4: `pnpm tsc --noEmit` (via `pnpm typecheck`) passes. Step 5: commit `feat(frontend): one money formatter and one invoice status vocabulary`.

---

### Task 6: Payments page — bucket list + All invoices tab

**Files:**
- Create: `frontend/app/(admin)/admin/payments/buckets/bucket-view.ts`, `bucket-view.test.ts`, `CollectionsTab.tsx`, `RecordPaymentDialog.tsx`; `frontend/app/(admin)/admin/payments/AllInvoicesTab.tsx`
- Modify: `frontend/app/(admin)/admin/payments/page.tsx`, `frontend/components/admin/screen-meta.ts` (subtitle → "Who owes, who is charged, who paid")

**Interfaces (produces, `bucket-view.ts`, pure):**
```ts
export const BUCKET_ORDER: CollectionsBucketKey[]
export const BUCKET_META: Record<CollectionsBucketKey, { title: string; hint: string; stripe: string /* tailwind bg class */; emptyLine: string }>
   // titles: "Failed autopay","Past due","Awaiting payment","Autopay scheduled","Paused","Paid"; stripes red/amber/teal/green/grey/light grey; emptyLine "No failed autopay" etc.
export const ACTION_LABEL: Record<CollectionsAction, string>   // "Send reminder","Record payment","Message","Skip this month","Resume"
export function normalizeCollections(data: unknown): AdminCollectionsView   // tolerant: missing/undefined → zero totals + six empty buckets in BUCKET_ORDER, sorted by BUCKET_ORDER
export function familyChip(bucket: CollectionsBucketKey, family: AdminCollectionsFamily): { variant: ChipVariant; label: string }
   // failed→failed "FAILED" (or "DISABLED" when failure.disabled); past_due→overdue "N DAYS LATE"; awaiting→pending "DUE IN N DAYS" (autopay.status "no_card_on_file"→"NO CARD ON FILE", "card_state_unknown"/"connected_account_unknown"→"AUTOPAY STATUS UNAVAILABLE"); autopay_scheduled→autopayOn "AUTOPAY"; paused→paused; paid→paid
export function secondaryLine(bucket, family, today: string): string
   // failed: "attempt N of 4 · retries <date>" | "no more retries"; past_due: "due <date> · N days late · reminded <date>|never reminded" (+ "· M months owed" when invoices.length>1 or leftover>0); awaiting: "due <date> · invoice emailed <date>|not sent"; autopay: "card ••1234 · charges <date> 9:00 AM · notice emailed <date>"; paused: "<session> · resumes <date>|review <date> · leftover $X|no balance"; paid: "<method> · <date>"
export function daysBetween(fromISO: string, toISO: string): number
export function studentLine(family): string   // "Hannah · Wed 6:15 Intermediate" joined with ", "
```

`CollectionsTab.tsx`: `useQuery({ queryKey: queryKeys.admin.collections(period), queryFn: () => getAdminCollections(period) })`; period picker `<select>` with the current month and 11 previous months (`YYYY-MM`, label "September 2026"); family search input filters rows client-side by parent/student name; four tiles (`Owed this month`, `Autopay scheduled`, `Needs action`, `Collected`) using `formatCents` with `data-testid="collections-tile-<key>"`; six buckets rendered in `BUCKET_ORDER` as `<section id="bucket-<key>" data-testid="bucket-<key>">` with header count `data-testid="bucket-<key>-count"`, hint, and rows `data-testid="family-row-<parent_id>"`; Paid uses a `<details>` collapsed by default (`data-testid="bucket-paid-toggle"`); empty bucket renders `<p data-testid="bucket-<key>-empty">{emptyLine}</p>`. Family name links to `/admin/students/<first student_id>` when there is a student. Row actions from `family.actions`:
- `send_reminder` → `useMutation(sendDuesReminders({ parent_ids: [parent_id] }))`; inline result text `Reminder sent` / `Blocked: <reason>` / error message under the row (`data-testid="row-status-<parent_id>"`), then `invalidateQueries(queryKeys.admin.collections(period))`.
- `record_payment` → opens `RecordPaymentDialog` for the family's first owing invoice (select if several).
- `message` → `<Link href={`/admin/messages?dm=${parent_id}`}>`.
- `skip_month` → `window.confirm("Void <invoice_number ?? invoice_id> for <name>? The family will not be charged this month.")` then `voidAdminInvoice(invoice_id, { reason: "skipped_by_admin" })`.
- `resume` → `resumeEnrollment(pause.enrollment_id)`.
Loading → `TableSkeleton` per bucket; error → one `role="alert"` panel with Retry (`data-testid="collections-error"`). Header "Record payment" primary button (`data-testid="collections-record-payment"`) opens `RecordPaymentDialog` with an invoice `<select>` over every owing invoice in buckets 1–3.

`RecordPaymentDialog.tsx`: props `{ open, invoices: {invoice_id, label, balance_due_cents}[], initialInvoiceId?, onClose, onSaved }`; `RallyModal` + `Field`/`DialogActions` from `@/components/ds/dialog-chrome`; fields amount (prefilled with balance), method select (cash/check/zelle/venmo/bank_transfer/other), reference, notes; one idempotency key per open (`mintPaymentIdempotencyKey`, rotated when fields change, exactly like the students page dialog); submit → `recordAdminInvoicePayment(invoiceId, payload, { idempotencyKey })`; `data-testid="record-payment-dialog"`, submit button text "Record payment".

`AllInvoicesTab.tsx`: move the current `page.tsx` body (webhook card, `ReconciliationReportPanel`, filters, table, dialogs, pagination). Remove the KPI strip (`Metric` cards) and the `Month` filter; keep `Sync Stripe` and `Generate monthly` buttons at the top of this tab. Keep `data-testid="admin-payments-table"` and row test ids.

`page.tsx`: `"use client"`; `useSearchParams().get("tab") === "invoices" ? "invoices" : "buckets"`; `role="tablist"` like `registrations/page.tsx` with tabs `Collections` (`data-testid="payments-tab-buckets"`) and `All invoices` (`data-testid="payments-tab-invoices"`); root `<section data-testid="admin-payments">`; wrap in `<Suspense>` because of `useSearchParams`.

- [ ] Step 1: `bucket-view.test.ts` (normalizeCollections on `{payments: []}` and `undefined`; familyChip per bucket; secondaryLine for each bucket incl. "no more retries", "never reminded", "no balance"; ACTION_LABEL covers all five) → fail. Step 2: implement `bucket-view.ts` → pass. Step 3: build components and page. Step 4: `pnpm typecheck && pnpm lint`. Step 5: commit `feat(admin): Payments page as a bucket list with an All invoices tab`.

---

### Task 7: Dashboard tiles + message composer prefill

**Files:**
- Modify: `frontend/app/(admin)/admin/page.tsx`, `frontend/app/(admin)/admin/messages/page.tsx`

- [ ] Dashboard: delete the local `formatCents` and import `{ formatCents } from "@/lib/money"` (use `{ whole: true }` where it used `maximumFractionDigits: 0`); delete `paymentsQuery`/`listAdminPayments` import and the "Payments tracked" `KpiCard`; add `collectionsQuery = useQuery({ queryKey: queryKeys.admin.collections("current"), queryFn: () => getAdminCollections() })` and three `KpiCard`s wrapped in `<Link>`: `Owed this month` → `/admin/payments#bucket-past_due`, `Autopay scheduled` (value money, hint "N families") → `/admin/payments#bucket-autopay_scheduled`, `Needs action` (count, hint "failed autopay · past due") → `/admin/payments#bucket-failed_autopay`. Use `normalizeCollections(collectionsQuery.data)` so stubs returning `{payments: []}` render zeros. Grid becomes `lg:grid-cols-5`. Recent payments untouched (PR #645 invariant comment stays).
- [ ] Messages: `const dmParam = useSearchParams().get("dm"); const [dmRecipientId, setDmRecipientId] = useState<string | null>(dmParam);` and wrap the default export body in `<Suspense>`. When `dmRecipientId` has no existing thread, still render the DM composer for that recipient (check the existing render branch around L150 and make the composer render whenever `dmRecipientId` is set).
- [ ] `pnpm typecheck && pnpm lint`; commit `feat(admin): dashboard money tiles from the collections totals; message composer prefill`.

---

### Task 8: Playwright — new bucket spec, update existing specs

**Files:**
- Create: `frontend/e2e/specs/admin-payments-buckets.spec.ts`
- Modify: `frontend/e2e/specs/admin-shell.spec.ts` ("payments renders legacy paid and waived statuses" → goto `/admin/payments?tab=invoices`, expect `VOID` instead of `WAIVED`), `frontend/e2e/specs/billing-trust-recovery.spec.ts` (goto `/admin/payments?tab=invoices`; replace the `Failed payments` KPI assertions with the row/webhook assertions that remain), `frontend/e2e/specs/saas-attendance-billing.spec.ts` (only if it asserts something that moved; the `admin-payments` testid stays on the root so likely untouched).

New spec (copy the auth/stub pattern from `billing-trust-recovery.spec.ts`: `installTenantGuard`, `collectConsoleErrors`, `stubMe`, `stubMemberships`, `stubAcademy`, `fulfillJson`): stub `**/api/v2/admin/payments/collections*` with a fixture containing all six buckets (one family each, values shaped like the wireframe), `**/api/v2/admin/payments*` → `{payments: []}` registered BEFORE the collections stub, `**/api/v2/admin/billing/webhooks*` → `{events: []}`, `**/api/v2/admin/dues-reminders` POST → capture body, return `{sent: 1, blocked: false, reason: null, selected_parent_ids: [...], generated_invoice_artifacts: 0}`. Tests:
1. buckets render in order (`bucket-*` testids appear top to bottom), counts match, tile values `$1,110.00`, `$1,380.00`, `2`, `$2,010.00` (match the fixture totals), zero console errors.
2. Paid bucket collapsed by default (`bucket-paid-toggle` `<details>` not open) and expands on click.
3. clicking `Record payment` on the past-due row opens `record-payment-dialog` prefilled with the balance.
4. clicking `Send reminder` posts `parent_ids: ["parent-past-due"]` and the row shows `Reminder sent`.
5. empty response `{payments: []}` → every `bucket-*-empty` line visible, tiles show `$0.00`, no console errors.
6. `?tab=invoices` shows `admin-payments-table` area (empty state `payments-empty`).

- [ ] Run: `cd frontend && pnpm playwright test e2e/specs/admin-payments-buckets.spec.ts e2e/specs/admin-shell.spec.ts e2e/specs/billing-trust-recovery.spec.ts e2e/specs/saas-attendance-billing.spec.ts e2e/specs/admin-session-creation-ui.spec.ts e2e/specs/saas-launch-route-matrix.spec.ts --project=chromium-mobile` (the config starts the dev server; if port 3001 is busy another worktree is using it — wait). Retry a single WebKit failure once when idle.
- [ ] Commit `test(e2e): Payments buckets spec; existing payments specs moved to the All invoices tab`.

---

### Task 9: Release note, gates, PR

- [ ] Write `docs/release-notes/2026-09-05-feat-payments-buckets.md` with `PR: #TBD` placeholder ONLY until the PR exists, then replace. What changed: Payments page = six buckets + All invoices tab; removed filters (`Succeeded` status option, `Month`); dashboard "Payments tracked" tile replaced by three money tiles; new read-only endpoint. Deploy notes: none (no migration, no env). Risk/rollback: read-only read model; actions reuse existing endpoints; rollback = revert the PR.
- [ ] Run the full gates from Global Constraints (backend suite from `backend/`, import-linter, mypy baseline, `pnpm typecheck`, `pnpm lint`, `pnpm test:unit`, touched e2e specs). Run `/code-review` on the diff and address findings.
- [ ] Push `git push -u origin feat/payments-buckets`, open the PR against `main` with `gh pr create` (body links the spec, inventory and wireframe artifacts, ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`), then stamp the real PR number in the release note and push. Do not merge.
