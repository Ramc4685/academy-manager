# Family Billing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the parent-level Family billing page (`/admin/families/[parentId]`) from spec `docs/superpowers/specs/2026-09-05-family-billing-design.md`: one read model, one new autopay-pause endpoint, the page, the Families list, and removal of Billing Setup and the student Billing tab.

**Architecture:** Same shape as spec 1 (PR #662): pure shaping rules in `contexts/billing/application/family_billing.py`, batched Mongo facts in `contexts/billing/infrastructure/family_billing_read_model.py`, a thin BFF route in `interfaces/admin/families_routes.py`, wiring in a new `composition/families.py` attached to `app.state.admin_families` (never `composition/admin.py`, which is at its 4800-line cap). Frontend reads one endpoint and renders `actions` verbatim; every write reuses an existing endpoint except `POST /admin/families/{parent_id}/autopay/pause`.

**Tech Stack:** FastAPI + Motor (mongomock in tests), pydantic v2, pytest; Next.js 15 App Router, React Query, vitest, Playwright.

## Global Constraints

- Work in worktree `.worktrees/family-billing` (branch `feat/family-billing`, off `origin/main`). `backend/.venv` is a symlink; run backend commands from `backend/` with `.venv/bin/python -m pytest`.
- `backend/v2/composition/admin.py` must not grow: all wiring in `composition/families.py`.
- No new write endpoints other than `POST /admin/families/{parent_id}/autopay/pause` (spec §5).
- Reuse `autopay_eligibility` (spec 1) for chargeability; reuse `frontend/lib/money.ts` (`formatCents`) and `frontend/lib/billing-status.ts` for status chips. No new money formatter, no new status vocabulary.
- Owner-only actions: `void`, `refund`, `discount_once`, and recurring discount. Backend enforces via existing `require_owner` routes; the family view drops them for non-owners; the page hides them via `useIsOwner()`.
- Every correction dialog requires a non-empty reason.
- Playwright stubs must name `**/api/v2/admin/families/**` explicitly (a `*` glob stops at `/`).
- Commit after every task with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Run `ruff check v2 && ruff format v2` from `backend/` before each backend commit; `pnpm exec tsc --noEmit && pnpm exec eslint <files>` from `frontend/` before each frontend commit.

## File structure

Backend (create):
- `backend/v2/contexts/billing/application/family_billing.py` — fact dataclasses, autopay state, action rules, timeline merge, view builder, owner stripping.
- `backend/v2/contexts/billing/application/use_cases/pause_family_autopay.py` — the pause use case.
- `backend/v2/contexts/billing/infrastructure/family_billing_read_model.py` — batched Mongo reads → `FamilyFacts` → view dict.
- `backend/v2/interfaces/admin/families_views.py` — pydantic response/request models.
- `backend/v2/interfaces/admin/families_routes.py` — `GET /families/{parent_id}/billing`, `POST /families/{parent_id}/autopay/pause`.
- `backend/v2/composition/families.py` — `compose_admin_families(db)`.
- Tests: `tests/unit/test_family_billing.py`, `tests/unit/test_pause_family_autopay.py`, `tests/contract/test_family_billing_read_model.py`, `tests/interface/test_admin_families_routes.py`.

Backend (modify):
- `backend/v2/contexts/billing/domain/billing_audit.py` — add `"autopay_paused"` action and optional `parent_id`.
- `backend/v2/contexts/billing/infrastructure/mongo_billing_audit_log.py` — `parent_id` round-trip, `list_for_family`.
- `backend/v2/interfaces/admin/router.py`, `backend/v2/main.py` — include router, attach state.
- `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` — two new routes.

Frontend (create):
- `frontend/lib/api/admin-families.ts` — types + `fetchAdminFamilyBilling`, `pauseFamilyAutopay`.
- `frontend/app/(admin)/admin/families/page.tsx` — Families list (moved Billing Setup table, actions removed).
- `frontend/app/(admin)/admin/families/[parentId]/page.tsx` — the page.
- `frontend/app/(admin)/admin/families/[parentId]/family-view.ts` + `family-view.test.ts` — pure view helpers.
- `frontend/app/(admin)/admin/families/[parentId]/FamilyHeader.tsx`, `StudentsPanel.tsx`, `InvoicesPanel.tsx`, `TimelinePanel.tsx`, `FixSomethingPanel.tsx`, `family-dialogs.tsx`.
- `frontend/e2e/specs/admin-family-billing.spec.ts`.

Frontend (modify):
- `frontend/app/(admin)/admin/billing-setup/page.tsx` — becomes a redirect.
- `frontend/app/(admin)/admin/students/[studentId]/page.tsx` — Billing tab → link panel (`FamilyBillingLink.tsx`); delete `BillingWorkflowPanel.tsx`, `billing-dialogs.tsx` if nothing else imports them (keep `BillingEnrollmentsPanel.tsx` on the Sessions tab? No — delete with the tab; `format.ts` stays for other panels).
- `frontend/app/(admin)/admin/payments/buckets/CollectionsTab.tsx` — family name links to `/admin/families/{parent_id}`.
- `frontend/components/admin/screen-meta.ts` (+ test) — nav item and titles.
- `frontend/lib/query/keys.ts` — `families`, `familyBilling(parentId)`.
- `frontend/e2e/specs/admin-students.spec.ts` — Billing tab assertions.
- `docs/release-notes/2026-09-06-feat-family-billing.md`.

---

### Task 1: Audit log — `autopay_paused` action, `parent_id`, family batch reader

**Files:**
- Modify: `backend/v2/contexts/billing/domain/billing_audit.py`
- Modify: `backend/v2/contexts/billing/infrastructure/mongo_billing_audit_log.py`
- Test: `backend/v2/tests/contract/test_billing_audit_log_family.py`

**Interfaces:**
- Produces: `BillingAuditEntry.parent_id: str | None` (default None); `BillingAuditAction` gains `"autopay_paused"`; `MongoBillingAuditLogRepository.list_for_family(*, parent_id: str, invoice_ids: list[str], payment_ids: list[str], enrollment_ids: list[str]) -> list[BillingAuditEntry]` (newest first, limit 500).

- [ ] **Step 1: Write the failing contract test**

```python
# backend/v2/tests/contract/test_billing_audit_log_family.py
"""mongomock contract for ``MongoBillingAuditLogRepository.list_for_family``."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)

AT = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _entry(**overrides) -> BillingAuditEntry:
    base = dict(
        audit_id="a-1",
        academy_id="acad",
        action="manual_payment_recorded",
        actor_id="admin-1",
        at=AT,
    )
    base.update(overrides)
    return BillingAuditEntry(**base)


@pytest.mark.asyncio
async def test_list_for_family_matches_invoice_payment_parent_and_enrollment(db, acad) -> None:
    repo = MongoBillingAuditLogRepository(db)
    await repo.append(_entry(audit_id="by-invoice", invoice_id="inv-1"))
    await repo.append(_entry(audit_id="by-payment", action="refund_issued", payment_id="pay-1"))
    await repo.append(
        _entry(audit_id="by-parent", action="autopay_paused", parent_id="p-1", reason="moving")
    )
    await repo.append(
        _entry(
            audit_id="by-enrollment",
            action="autopay_resumed",
            before={"enrollment_id": "e-1", "status": "paused"},
            after={"enrollment_id": "e-1", "status": "active"},
        )
    )
    await repo.append(_entry(audit_id="other", invoice_id="inv-other"))

    entries = await repo.list_for_family(
        parent_id="p-1", invoice_ids=["inv-1"], payment_ids=["pay-1"], enrollment_ids=["e-1"]
    )

    assert sorted(e.audit_id for e in entries) == [
        "by-enrollment",
        "by-invoice",
        "by-parent",
        "by-payment",
    ]
    paused = next(e for e in entries if e.audit_id == "by-parent")
    assert paused.parent_id == "p-1"
    assert paused.reason == "moving"


@pytest.mark.asyncio
async def test_list_for_family_is_tenant_scoped(db, acad) -> None:
    await db["billing_audit_log"].insert_one(
        {
            "audit_id": "foreign",
            "academy_id": "other-acad",
            "action": "autopay_paused",
            "actor_id": "x",
            "at": AT,
            "parent_id": "p-1",
        }
    )
    repo = MongoBillingAuditLogRepository(db)

    entries = await repo.list_for_family(
        parent_id="p-1", invoice_ids=[], payment_ids=[], enrollment_ids=[]
    )

    assert entries == []
```

Check how `db`/`acad` fixtures set the tenant context: `grep -n "def db\b\|def acad\b" backend/v2/tests/conftest.py` — they are the same fixtures the collections contract test uses.

- [ ] **Step 2: Run to verify it fails**

Run from `backend/`: `.venv/bin/python -m pytest v2/tests/contract/test_billing_audit_log_family.py -q`
Expected: FAIL (`parent_id` unexpected kwarg / no attribute `list_for_family`).

- [ ] **Step 3: Implement**

In `billing_audit.py`, add to the `BillingAuditAction` literal after `"autopay_resumed",`:

```python
    # Family billing page: the owner/admin switched autopay OFF for every
    # active enrollment of one parent (spec 2026-09-05-family-billing §5).
    "autopay_paused",
```

and to `BillingAuditEntry` after `payment_id`:

```python
    # Family-level actions (autopay_paused) have no invoice; the family
    # timeline finds them by parent instead.
    parent_id: str | None = None
```

In `mongo_billing_audit_log.py`, add `parent_id=_opt_str(doc.get("parent_id")),` to `_to_domain` after `payment_id`, and add the reader after `list_for_invoice`:

```python
    async def list_for_family(
        self,
        *,
        parent_id: str,
        invoice_ids: list[str],
        payment_ids: list[str],
        enrollment_ids: list[str],
    ) -> list[BillingAuditEntry]:
        """Every entry that touches one family: by invoice, by payment, by parent
        (family-level actions), or by the enrollment named in ``before``
        (``autopay_resumed`` rows written by the Billing Setup enable path carry
        no parent_id)."""
        clauses: list[dict[str, Any]] = [{"parent_id": parent_id}]
        if invoice_ids:
            clauses.append({"invoice_id": {"$in": invoice_ids}})
        if payment_ids:
            clauses.append({"payment_id": {"$in": payment_ids}})
        if enrollment_ids:
            clauses.append({"before.enrollment_id": {"$in": enrollment_ids}})
        cursor = self._find_many({"$or": clauses}, sort=[("at", -1)], limit=500)
        return [self._to_domain(doc) async for doc in cursor]
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest v2/tests/contract/test_billing_audit_log_family.py v2/tests -q -k "audit" -x`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/v2/contexts/billing/domain/billing_audit.py backend/v2/contexts/billing/infrastructure/mongo_billing_audit_log.py backend/v2/tests/contract/test_billing_audit_log_family.py
git commit -m "feat(billing): autopay_paused audit action and family batch reader"
```

---

### Task 2: Pure family billing rules (`family_billing.py`)

**Files:**
- Create: `backend/v2/contexts/billing/application/family_billing.py`
- Test: `backend/v2/tests/unit/test_family_billing.py`

**Interfaces:**
- Consumes: `autopay_eligibility(...)`, `invoice_is_chargeable` from `autopay_eligibility.py`; `MAX_DUNNING_ATTEMPTS` from `domain/dunning.py`.
- Produces (all frozen dataclasses unless noted): `ParentFacts`, `EnrollmentFacts`, `StudentFacts`, `AllocationFacts`, `CreditFacts`, `InvoiceFacts`, `AttemptFacts`, `DunningFacts`, `AuditFacts`, `EventFacts`, `CustomerFacts`, `FamilyFacts`; functions `autopay_state(enrollments) -> str`, `invoice_actions(inv, *, eligibility) -> list[str]`, `family_actions(*, state, has_card, invoices) -> list[str]`, `build_timeline(facts, *, zone) -> list[dict]`, `build_family_billing_view(facts, *, timezone, generated_at, today) -> dict`, `strip_owner_actions(view) -> dict`; constants `OWNER_ONLY_ACTIONS`, `TIMELINE_CAP = 200`, `FAILURE_ATTEMPT_STATUSES`.

- [ ] **Step 1: Write the failing unit tests**

```python
# backend/v2/tests/unit/test_family_billing.py
"""Pure rules for the Family billing view (spec 2026-09-05-family-billing §3.3, §3.4, §4)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from backend.v2.contexts.billing.application.family_billing import (
    AllocationFacts,
    AttemptFacts,
    AuditFacts,
    CustomerFacts,
    DunningFacts,
    EnrollmentFacts,
    EventFacts,
    FamilyFacts,
    InvoiceFacts,
    ParentFacts,
    StudentFacts,
    autopay_state,
    build_family_billing_view,
    build_timeline,
    family_actions,
    invoice_actions,
    strip_owner_actions,
)
from backend.v2.contexts.billing.application.autopay_eligibility import (
    ELIGIBLE,
    Eligibility,
)

ZONE = ZoneInfo("America/Chicago")
NOW = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)
TODAY = date(2026, 9, 10)


def _enrollment(eid="e-1", autopay="active", status="active", **kw) -> EnrollmentFacts:
    base = dict(
        enrollment_id=eid,
        student_id="s-1",
        session_id="sess-1",
        session_title="Wed 6:15 Intermediate",
        schedule="Wed 18:15",
        status=status,
        monthly_price_cents=7000,
        override_price_cents=None,
        autopay_status=autopay,
        recurring_discount=None,
        resume_on=None,
    )
    base.update(kw)
    return EnrollmentFacts(**base)


def _invoice(iid="inv-1", status="open", balance=6000, allocations=(), **kw) -> InvoiceFacts:
    base = dict(
        invoice_id=iid,
        invoice_number=f"INV-{iid}",
        period="2026-09",
        student_id="s-1",
        student_name="Arjun",
        enrollment_id="e-1",
        status=status,
        total_cents=6000,
        balance_due_cents=balance,
        due_date=date(2026, 9, 8),
        created_at=datetime(2026, 9, 1, 6, 0, tzinfo=UTC),
        paid_at=None,
        voided_at=None,
        void_reason=None,
        delivery_status="sent",
        last_sent_at=datetime(2026, 9, 1, 6, 5, tzinfo=UTC),
        autopay_status="active",
        allocations=tuple(allocations),
        credits=(),
    )
    base.update(kw)
    return InvoiceFacts(**base)


def _alloc(payment_id="pay-1", stripe=True, method="card", amount=6000) -> AllocationFacts:
    return AllocationFacts(
        payment_id=payment_id,
        amount_cents=amount,
        method=method,
        paid_at=datetime(2026, 8, 4, 14, 0, tzinfo=UTC),
        stripe_payment_intent_id="pi_1" if stripe else None,
    )


def _facts(**kw) -> FamilyFacts:
    base = dict(
        parent=ParentFacts(parent_id="p-1", name="Sahaya Vinodh", email="s@example.com", phone=None),
        students=(StudentFacts(student_id="s-1", name="Arjun", status="active", enrollments=(_enrollment(),)),),
        invoices=(_invoice(),),
        attempts=(),
        dunning=(),
        audit=(),
        events=(),
        customer=CustomerFacts(has_card=True, card_last4="4242", card_label="Visa", last_invited_at=None, has_login_account=True),
        available_credit_cents=0,
        connected_account_ready=True,
        warnings=(),
    )
    base.update(kw)
    return FamilyFacts(**base)


# ------------------------------------------------------------ autopay state


def test_autopay_state_on_partial_off_needs_consent() -> None:
    assert autopay_state([_enrollment(autopay="active")]) == "on"
    assert autopay_state([_enrollment(autopay="active"), _enrollment("e-2", autopay="paused")]) == "partial"
    assert autopay_state([_enrollment(autopay="paused")]) == "off"
    assert autopay_state([_enrollment(autopay="offered"), _enrollment("e-2", autopay="disabled")]) == "needs_consent"
    assert autopay_state([]) == "needs_consent"


def test_autopay_state_ignores_cancelled_enrollments() -> None:
    assert autopay_state([_enrollment(autopay="active"), _enrollment("e-2", autopay="paused", status="cancelled")]) == "on"


# ------------------------------------------------------------ actions


def test_open_invoice_actions_with_eligible_card() -> None:
    assert invoice_actions(_invoice(), eligibility=ELIGIBLE) == [
        "send",
        "record_payment",
        "charge_card",
        "void",
        "discount_once",
    ]


def test_open_invoice_without_eligibility_has_no_charge_card() -> None:
    acts = invoice_actions(_invoice(), eligibility=Eligibility("ineligible", "no_card_on_file"))
    assert "charge_card" not in acts
    assert "void" in acts


def test_partially_paid_invoice_with_stripe_allocation_refunds_not_void() -> None:
    inv = _invoice(status="partially_paid", balance=1000, allocations=[_alloc(amount=5000)])
    acts = invoice_actions(inv, eligibility=ELIGIBLE)
    assert "refund" in acts
    assert "void" not in acts
    assert "record_payment" in acts


def test_paid_invoice_with_manual_allocation_has_no_refund() -> None:
    inv = _invoice(status="paid", balance=0, allocations=[_alloc(stripe=False, method="zelle")])
    assert invoice_actions(inv, eligibility=Eligibility("ineligible", "invoice_not_chargeable")) == []


def test_void_and_draft_invoices_have_no_actions() -> None:
    assert invoice_actions(_invoice(status="void", balance=0), eligibility=ELIGIBLE) == []
    assert invoice_actions(_invoice(status="draft"), eligibility=ELIGIBLE) == []


def test_family_actions() -> None:
    assert family_actions(state="on", has_card=True, invoices=[_invoice()]) == [
        "autopay_off",
        "send_invoice",
        "record_payment",
    ]
    assert family_actions(state="off", has_card=True, invoices=[]) == ["autopay_on"]
    assert family_actions(state="needs_consent", has_card=False, invoices=[]) == ["send_invite"]
    assert family_actions(state="partial", has_card=True, invoices=[_invoice()]) == [
        "autopay_on",
        "autopay_off",
        "send_invoice",
        "record_payment",
    ]


def test_strip_owner_actions_removes_void_refund_discount_everywhere() -> None:
    view = build_family_billing_view(_facts(), timezone="America/Chicago", generated_at=NOW, today=TODAY)
    assert "void" in view["invoices"][0]["actions"]
    stripped = strip_owner_actions(view)
    assert stripped["invoices"][0]["actions"] == ["send", "record_payment", "charge_card"]
    assert stripped["students"][0]["enrollments"][0]["actions"] == []
    assert view["students"][0]["enrollments"][0]["actions"] == ["recurring_discount"]


# ------------------------------------------------------------ timeline


def test_timeline_merges_sources_newest_first_and_mutes_comms() -> None:
    paid = _invoice(
        "inv-aug",
        status="paid",
        balance=0,
        period="2026-08",
        created_at=datetime(2026, 8, 1, 6, 0, tzinfo=UTC),
        paid_at=datetime(2026, 8, 4, 14, 0, tzinfo=UTC),
        allocations=[_alloc()],
        last_sent_at=datetime(2026, 8, 1, 6, 5, tzinfo=UTC),
    )
    void = _invoice(
        "inv-void",
        status="void",
        balance=0,
        student_name="Hannah",
        voided_at=datetime(2026, 9, 4, 20, 0, tzinfo=UTC),
        void_reason="enrollment paused",
        last_sent_at=None,
    )
    facts = _facts(
        invoices=(_invoice(), paid, void),
        attempts=(
            AttemptFacts(
                attempt_id="at-1",
                invoice_id="inv-1",
                status="declined",
                failure_message="Your card was declined.",
                amount_cents=6000,
                created_at=datetime(2026, 9, 8, 14, 0, tzinfo=UTC),
            ),
        ),
        dunning=(
            DunningFacts(
                invoice_id="inv-1",
                status="dunned",
                attempt_count=4,
                autopay_disabled_at=datetime(2026, 9, 9, 14, 0, tzinfo=UTC),
                last_notification_at=datetime(2026, 9, 8, 14, 1, tzinfo=UTC),
            ),
        ),
        audit=(
            AuditFacts(
                audit_id="a-1",
                action="autopay_paused",
                actor_id="admin-1",
                at=datetime(2026, 9, 4, 20, 1, tzinfo=UTC),
                invoice_id=None,
                payment_id=None,
                reason="parent asked",
                before=None,
                after=None,
            ),
        ),
        events=(
            EventFacts(
                event_id="ev-1",
                event_type="paused",
                enrollment_id="e-1",
                student_name="Hannah",
                occurred_at=datetime(2026, 9, 4, 19, 59, tzinfo=UTC),
                actor_id="admin-1",
                reason="travel",
                effective_at=datetime(2026, 10, 1, 5, 0, tzinfo=UTC),
            ),
        ),
    )

    timeline = build_timeline(facts, zone=ZONE)

    codes = [e["code"] for e in timeline]
    assert codes == [
        "autopay_disabled_by_ladder",
        "failure_notice_emailed",
        "charge_failed",
        "audit:autopay_paused",
        "invoice_voided",
        "enrollment:paused",
        "autopay_notice_emailed",
        "invoice_generated",
        "payment_received",
        "invoice_emailed",  # inv-aug sent Aug 1 06:05 (autopay_status active → notice? no: see below)
        "invoice_generated",
    ]
    by_code = {e["code"]: e for e in timeline}
    assert by_code["charge_failed"]["summary"] == "Card declined · $60 · attempt 1 · Your card was declined."
    assert by_code["payment_received"]["summary"] == "$60 received · card"
    assert by_code["payment_received"]["kind"] == "money"
    assert by_code["autopay_notice_emailed"]["muted"] is True
    assert by_code["audit:autopay_paused"]["reason"] == "parent asked"
    assert by_code["audit:autopay_paused"]["kind"] == "admin"
    assert by_code["invoice_voided"]["summary"] == "Sep 2026 invoice voided · Hannah · enrollment paused"
    assert by_code["enrollment:paused"]["summary"] == "Hannah paused · resumes Oct 1"


def test_timeline_one_entry_per_payment_even_when_it_settles_two_invoices() -> None:
    a = _invoice("inv-a", status="paid", balance=0, allocations=[_alloc(amount=3000)])
    b = _invoice("inv-b", status="paid", balance=0, allocations=[_alloc(amount=3000)])
    timeline = build_timeline(_facts(invoices=(a, b)), zone=ZONE)
    received = [e for e in timeline if e["code"] == "payment_received"]
    assert len(received) == 1
    assert received[0]["amount_cents"] == 6000
    assert sorted(received[0]["invoice_ids"]) == ["inv-a", "inv-b"]


def test_timeline_is_capped() -> None:
    invoices = tuple(_invoice(f"inv-{i}", last_sent_at=None) for i in range(250))
    assert len(build_timeline(_facts(invoices=invoices), zone=ZONE)) == 200


# ------------------------------------------------------------ view


def test_view_header_next_charge_and_paid_cents() -> None:
    aug = _invoice("inv-aug", status="paid", balance=0, period="2026-08", allocations=[_alloc()])
    view = build_family_billing_view(
        _facts(invoices=(_invoice(), aug)), timezone="America/Chicago", generated_at=NOW, today=TODAY
    )
    header = view["header"]
    assert header["balance_cents"] == 6000
    assert header["open_invoice_count"] == 1
    assert header["autopay"] == {
        "state": "on",
        "active_count": 1,
        "total_count": 1,
        "card_last4": "4242",
        "card_label": "Visa",
        "next_charge_on": "2026-09-08",
        "next_charge_invoice_id": "inv-1",
        "last_failure": None,
    }
    assert header["last_payment"] == {
        "amount_cents": 6000,
        "method": "card",
        "paid_at": "2026-08-04T14:00:00+00:00",
        "invoice_ids": ["inv-aug"],
    }
    assert header["registration"] == {"state": "registered", "card_on_file": True, "last_invited_at": None}
    paid_row = next(i for i in view["invoices"] if i["invoice_id"] == "inv-aug")
    assert paid_row["paid_cents"] == 6000
    assert paid_row["settlement_unlinked"] is False
    assert view["actions"] == ["autopay_off", "send_invoice", "record_payment"]
    assert view["warnings"] == []


def test_view_unlinked_paid_invoice_reports_total_minus_balance() -> None:
    legacy = _invoice("inv-legacy", status="paid", balance=0, allocations=[])
    view = build_family_billing_view(_facts(invoices=(legacy,)), timezone="UTC", generated_at=NOW, today=TODAY)
    row = view["invoices"][0]
    assert row["paid_cents"] == 6000
    assert row["settlement_unlinked"] is True


def test_view_no_card_means_no_next_charge_and_invite_offered() -> None:
    facts = _facts(customer=CustomerFacts(has_card=False, card_last4=None, card_label=None, last_invited_at=None, has_login_account=False))
    view = build_family_billing_view(facts, timezone="UTC", generated_at=NOW, today=TODAY)
    assert view["header"]["autopay"]["next_charge_on"] is None
    assert view["header"]["registration"]["state"] == "not_invited"
    assert "send_invite" in view["actions"]
    assert "charge_card" not in view["invoices"][0]["actions"]
```

Note on the expected code order in `test_timeline_merges_sources_newest_first_and_mutes_comms`: `inv-aug` has `autopay_status="active"` (the default in `_invoice`), so its send is `autopay_notice_emailed` too. Fix the expected list to: `[..., "invoice_generated", "payment_received", "autopay_notice_emailed", "invoice_generated"]` — i.e. replace the `"invoice_emailed"` line with `"autopay_notice_emailed"` and drop the trailing comment. Sort key is `(at desc, code asc)`; the Sep-1 06:05 notice for `inv-1` precedes the Sep-1 06:00 generation, and Aug 4 payment precedes Aug 1 events.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest v2/tests/unit/test_family_billing.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `family_billing.py`**

```python
# backend/v2/contexts/billing/application/family_billing.py
"""Pure rules for the admin Family billing view.

Spec: ``docs/superpowers/specs/2026-09-05-family-billing-design.md`` §3.3 (autopay
state), §3.4 (actions), §4 (timeline). No Mongo, no clock: the infrastructure read
model gathers :class:`FamilyFacts` in a fixed number of batched queries and calls
:func:`build_family_billing_view`; the interface layer strips owner-only actions
for non-owners with :func:`strip_owner_actions` and serialises the dict.

Chargeability is never re-derived here — it comes from :mod:`autopay_eligibility`,
the predicates the dunning worker runs.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from typing import Any

from backend.v2.contexts.billing.application.autopay_eligibility import (
    AUTOPAY_ACTIVE_STATUS,
    CHARGEABLE_INVOICE_STATUSES,
    Eligibility,
    autopay_eligibility,
)

TIMELINE_CAP = 200

OWNER_ONLY_ACTIONS: frozenset[str] = frozenset({"void", "refund", "discount_once", "recurring_discount"})

# Charge-outcome attempt statuses that mean "the charge did not take money".
FAILURE_ATTEMPT_STATUSES: frozenset[str] = frozenset(
    {"failed", "declined", "requires_action", "error", "canceled", "cancelled"}
)

_PAUSED = "paused"
_CANCELLED_ENROLLMENT_STATUSES: frozenset[str] = frozenset({"cancelled", "withdrawn"})
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# --------------------------------------------------------------------------- facts


@dataclass(frozen=True)
class ParentFacts:
    parent_id: str
    name: str | None
    email: str | None
    phone: str | None


@dataclass(frozen=True)
class EnrollmentFacts:
    enrollment_id: str
    student_id: str
    session_id: str | None
    session_title: str | None
    schedule: str | None
    status: str
    monthly_price_cents: int | None
    override_price_cents: int | None
    autopay_status: str | None
    recurring_discount: dict[str, Any] | None
    resume_on: date | None


@dataclass(frozen=True)
class StudentFacts:
    student_id: str
    name: str
    status: str | None
    enrollments: tuple[EnrollmentFacts, ...]


@dataclass(frozen=True)
class AllocationFacts:
    payment_id: str
    amount_cents: int
    method: str | None
    paid_at: datetime | None
    stripe_payment_intent_id: str | None


@dataclass(frozen=True)
class CreditFacts:
    credit_id: str
    amount_cents: int


@dataclass(frozen=True)
class InvoiceFacts:
    invoice_id: str
    invoice_number: str | None
    period: str
    student_id: str | None
    student_name: str | None
    enrollment_id: str | None
    status: str
    total_cents: int
    balance_due_cents: int
    due_date: date | None
    created_at: datetime | None
    paid_at: datetime | None
    voided_at: datetime | None
    void_reason: str | None
    delivery_status: str
    last_sent_at: datetime | None
    autopay_status: str | None  # the enrollment's autopay status (labels the send)
    allocations: tuple[AllocationFacts, ...]
    credits: tuple[CreditFacts, ...]


@dataclass(frozen=True)
class AttemptFacts:
    attempt_id: str
    invoice_id: str
    status: str
    failure_message: str | None
    amount_cents: int
    created_at: datetime | None


@dataclass(frozen=True)
class DunningFacts:
    invoice_id: str
    status: str | None
    attempt_count: int
    autopay_disabled_at: datetime | None
    last_notification_at: datetime | None


@dataclass(frozen=True)
class AuditFacts:
    audit_id: str
    action: str
    actor_id: str
    at: datetime
    invoice_id: str | None
    payment_id: str | None
    reason: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None


@dataclass(frozen=True)
class EventFacts:
    event_id: str
    event_type: str
    enrollment_id: str
    student_name: str | None
    occurred_at: datetime
    actor_id: str | None
    reason: str | None
    effective_at: datetime | None


@dataclass(frozen=True)
class CustomerFacts:
    has_card: bool | None  # None = lookup failed (unknown)
    card_last4: str | None
    card_label: str | None
    last_invited_at: datetime | None
    has_login_account: bool


@dataclass(frozen=True)
class FamilyFacts:
    parent: ParentFacts
    students: tuple[StudentFacts, ...]
    invoices: tuple[InvoiceFacts, ...]  # newest first
    attempts: tuple[AttemptFacts, ...]
    dunning: tuple[DunningFacts, ...]
    audit: tuple[AuditFacts, ...]
    events: tuple[EventFacts, ...]
    customer: CustomerFacts
    available_credit_cents: int
    connected_account_ready: bool | None
    warnings: tuple[str, ...]


# --------------------------------------------------------------------------- helpers


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _local_date(value: datetime | None, zone: tzinfo) -> date | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(zone).date()


def _money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    if cents % 100 == 0:
        return f"{sign}${cents // 100:,}"
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def _period_label(period: str) -> str:
    try:
        year, month = period.split("-")
        return f"{_MONTHS[int(month) - 1]} {year}"
    except (ValueError, IndexError):
        return period


def _day_label(value: date | datetime | None, zone: tzinfo) -> str | None:
    day = _local_date(value, zone) if isinstance(value, datetime) else value
    if day is None:
        return None
    return f"{_MONTHS[day.month - 1]} {day.day}"


def _method_label(method: str | None, card_last4: str | None = None) -> str:
    if method in (None, "", "card", "stripe") and card_last4:
        return f"card ••{card_last4}"
    return (method or "payment").replace("_", " ")


def _live(enrollments: Iterable[EnrollmentFacts]) -> list[EnrollmentFacts]:
    return [e for e in enrollments if e.status not in _CANCELLED_ENROLLMENT_STATUSES]


def _all_enrollments(facts: FamilyFacts) -> list[EnrollmentFacts]:
    return [e for s in facts.students for e in s.enrollments]


def _stripe_paid_cents(inv: InvoiceFacts) -> int:
    return sum(a.amount_cents for a in inv.allocations if a.stripe_payment_intent_id)


# --------------------------------------------------------------------------- rules


def autopay_state(enrollments: Iterable[EnrollmentFacts]) -> str:
    """Spec §3.3 over the parent's non-cancelled enrollments."""
    statuses = [e.autopay_status for e in _live(enrollments)]
    active = sum(1 for s in statuses if s == AUTOPAY_ACTIVE_STATUS)
    if statuses and active == len(statuses):
        return "on"
    if active:
        return "partial"
    if any(s == _PAUSED for s in statuses):
        return "off"
    return "needs_consent"


def invoice_actions(inv: InvoiceFacts, *, eligibility: Eligibility) -> list[str]:
    """Spec §3.4 per-invoice table. Order is the button order on the page."""
    actions: list[str] = []
    if inv.status in CHARGEABLE_INVOICE_STATUSES:
        actions.append("send")
        if inv.balance_due_cents > 0:
            actions.append("record_payment")
            if eligibility.eligible:
                actions.append("charge_card")
        if not inv.allocations:
            actions.append("void")
    if inv.status in {"paid", "partially_paid"} and _stripe_paid_cents(inv) > 0:
        actions.append("refund")
    if inv.status == "open" and inv.balance_due_cents > 0:
        actions.append("discount_once")
    return actions


def family_actions(*, state: str, has_card: bool | None, invoices: Sequence[InvoiceFacts]) -> list[str]:
    actions: list[str] = []
    if not has_card:
        actions.append("send_invite")
    if state in {"off", "partial"}:
        actions.append("autopay_on")
    if state in {"on", "partial"}:
        actions.append("autopay_off")
    open_invoices = [i for i in invoices if i.status in CHARGEABLE_INVOICE_STATUSES]
    if open_invoices:
        actions.append("send_invoice")
    if any(i.balance_due_cents > 0 for i in open_invoices):
        actions.append("record_payment")
    return actions


def strip_owner_actions(view: dict[str, Any]) -> dict[str, Any]:
    """Remove owner-only actions for a non-owner caller (interface layer)."""
    out = dict(view)
    out["invoices"] = [
        {**inv, "actions": [a for a in inv["actions"] if a not in OWNER_ONLY_ACTIONS]}
        for inv in view["invoices"]
    ]
    out["students"] = [
        {
            **student,
            "enrollments": [
                {**e, "actions": [a for a in e["actions"] if a not in OWNER_ONLY_ACTIONS]}
                for e in student["enrollments"]
            ],
        }
        for student in view["students"]
    ]
    out["actions"] = [a for a in view["actions"] if a not in OWNER_ONLY_ACTIONS]
    return out


# --------------------------------------------------------------------------- timeline


def _entry(
    *,
    at: datetime,
    kind: str,
    code: str,
    summary: str,
    invoice_id: str | None = None,
    enrollment_id: str | None = None,
    student_name: str | None = None,
    actor_id: str | None = None,
    reason: str | None = None,
    amount_cents: int | None = None,
    invoice_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "at": at,
        "kind": kind,
        "code": code,
        "summary": summary,
        "invoice_id": invoice_id,
        "invoice_ids": invoice_ids or ([invoice_id] if invoice_id else []),
        "enrollment_id": enrollment_id,
        "student_name": student_name,
        "actor_id": actor_id,
        "reason": reason,
        "amount_cents": amount_cents,
        "muted": kind == "comms",
    }


_AUDIT_SUMMARIES: dict[str, str] = {
    "manual_payment_recorded": "Payment recorded by admin",
    "refund_issued": "Refund issued",
    "admin_charge_initiated": "Card charged by admin",
    "autopay_resumed": "Autopay turned on",
    "autopay_paused": "Autopay turned off",
    "invoice_voided": "Invoice voided by admin",
    "invoice_line_added": "Charge added to invoice",
    "invoice_line_removed": "Charge removed from invoice",
    "discount_set": "Discount set",
    "discount_removed": "Discount removed",
    "platform_fallback_toggled": "Charge routing changed",
    "invoice_schedule_changed": "Invoice schedule changed",
}

_EVENT_SUMMARIES: dict[str, str] = {
    "created": "enrolled",
    "paused": "paused",
    "resumed": "resumed",
    "cancelled": "cancelled",
    "withdrawn": "withdrawn",
    "moved": "moved to another class",
    "promoted": "promoted from waitlist",
    "waitlisted": "waitlisted",
}


def build_timeline(facts: FamilyFacts, *, zone: tzinfo) -> list[dict[str, Any]]:
    """Spec §4: one merged list, newest first, capped, comms muted."""
    entries: list[dict[str, Any]] = []
    invoice_by_id = {inv.invoice_id: inv for inv in facts.invoices}

    for inv in facts.invoices:
        label = _period_label(inv.period)
        who = f" · {inv.student_name}" if inv.student_name else ""
        if inv.created_at is not None:
            entries.append(
                _entry(
                    at=inv.created_at,
                    kind="money",
                    code="invoice_generated",
                    summary=f"{label} invoice generated{who} · {_money(inv.total_cents)}",
                    invoice_id=inv.invoice_id,
                    student_name=inv.student_name,
                    amount_cents=inv.total_cents,
                )
            )
        if inv.voided_at is not None:
            why = f" · {inv.void_reason}" if inv.void_reason else ""
            entries.append(
                _entry(
                    at=inv.voided_at,
                    kind="money",
                    code="invoice_voided",
                    summary=f"{label} invoice voided{who}{why}",
                    invoice_id=inv.invoice_id,
                    student_name=inv.student_name,
                    reason=inv.void_reason,
                )
            )
        if inv.last_sent_at is not None:
            notice = inv.autopay_status == AUTOPAY_ACTIVE_STATUS
            entries.append(
                _entry(
                    at=inv.last_sent_at,
                    kind="comms",
                    code="autopay_notice_emailed" if notice else "invoice_emailed",
                    summary=(
                        f"Autopay notice emailed · {label}{who}"
                        if notice
                        else f"{label} invoice emailed{who}"
                    ),
                    invoice_id=inv.invoice_id,
                    student_name=inv.student_name,
                )
            )

    # One entry per payment, listing every invoice it settled (PR #645 invariant).
    payments: dict[str, dict[str, Any]] = {}
    for inv in facts.invoices:
        for alloc in inv.allocations:
            slot = payments.setdefault(
                alloc.payment_id,
                {"amount_cents": 0, "invoice_ids": [], "method": alloc.method, "paid_at": alloc.paid_at},
            )
            slot["amount_cents"] += alloc.amount_cents
            slot["invoice_ids"].append(inv.invoice_id)
            if slot["paid_at"] is None:
                slot["paid_at"] = alloc.paid_at
    for payment_id, slot in payments.items():
        if slot["paid_at"] is None:
            continue
        entries.append(
            _entry(
                at=slot["paid_at"],
                kind="money",
                code="payment_received",
                summary=f"{_money(slot['amount_cents'])} received · {_method_label(slot['method'], facts.customer.card_last4)}",
                invoice_ids=sorted(slot["invoice_ids"]),
                amount_cents=slot["amount_cents"],
                reason=payment_id,
            )
        )

    failed_by_invoice: dict[str, int] = {}
    for attempt in sorted(facts.attempts, key=lambda a: (a.created_at or datetime.min, a.attempt_id)):
        if attempt.status not in FAILURE_ATTEMPT_STATUSES or attempt.created_at is None:
            continue
        n = failed_by_invoice.get(attempt.invoice_id, 0) + 1
        failed_by_invoice[attempt.invoice_id] = n
        inv = invoice_by_id.get(attempt.invoice_id)
        detail = f" · {attempt.failure_message}" if attempt.failure_message else ""
        entries.append(
            _entry(
                at=attempt.created_at,
                kind="money",
                code="charge_failed",
                summary=f"Card declined · {_money(attempt.amount_cents)} · attempt {n}{detail}",
                invoice_id=attempt.invoice_id,
                student_name=inv.student_name if inv else None,
                amount_cents=attempt.amount_cents,
            )
        )

    for d in facts.dunning:
        if d.autopay_disabled_at is not None:
            entries.append(
                _entry(
                    at=d.autopay_disabled_at,
                    kind="money",
                    code="autopay_disabled_by_ladder",
                    summary=f"Autopay disabled after {d.attempt_count} failed attempts",
                    invoice_id=d.invoice_id,
                )
            )
        if d.last_notification_at is not None:
            entries.append(
                _entry(
                    at=d.last_notification_at,
                    kind="comms",
                    code="failure_notice_emailed",
                    summary="Payment failure notice emailed",
                    invoice_id=d.invoice_id,
                )
            )

    for a in facts.audit:
        base = _AUDIT_SUMMARIES.get(a.action, a.action.replace("_", " ").capitalize())
        why = f" · {a.reason}" if a.reason else ""
        entries.append(
            _entry(
                at=a.at,
                kind="admin",
                code=f"audit:{a.action}",
                summary=f"{base}{why}",
                invoice_id=a.invoice_id,
                actor_id=a.actor_id,
                reason=a.reason,
            )
        )

    for ev in facts.events:
        verb = _EVENT_SUMMARIES.get(ev.event_type, ev.event_type)
        who = ev.student_name or "Student"
        tail = ""
        if ev.event_type == "paused" and ev.effective_at is not None:
            tail = f" · resumes {_day_label(ev.effective_at, zone)}"
        elif ev.reason:
            tail = f" · {ev.reason}"
        entries.append(
            _entry(
                at=ev.occurred_at,
                kind="lifecycle",
                code=f"enrollment:{ev.event_type}",
                summary=f"{who} {verb}{tail}",
                enrollment_id=ev.enrollment_id,
                student_name=ev.student_name,
                actor_id=ev.actor_id,
                reason=ev.reason,
            )
        )

    entries.sort(key=lambda e: (e["at"], e["code"]), reverse=True)
    # ``reverse`` flips the code tiebreak too; restore ascending code order within a timestamp.
    entries.sort(key=lambda e: e["code"])
    entries.sort(key=lambda e: e["at"], reverse=True)
    for e in entries:
        e["at"] = _iso(e["at"])
    return entries[:TIMELINE_CAP]


# --------------------------------------------------------------------------- view


def _enrollment_payload(e: EnrollmentFacts, *, owner_actions: bool = True) -> dict[str, Any]:
    return {
        "enrollment_id": e.enrollment_id,
        "session_id": e.session_id,
        "session_title": e.session_title,
        "schedule": e.schedule,
        "status": e.status,
        "monthly_price_cents": e.monthly_price_cents,
        "override_price_cents": e.override_price_cents,
        "autopay_status": e.autopay_status,
        "recurring_discount": e.recurring_discount,
        "resume_on": _iso(e.resume_on),
        "actions": ["recurring_discount"] if e.status not in _CANCELLED_ENROLLMENT_STATUSES else [],
    }


def _invoice_payload(inv: InvoiceFacts, *, eligibility: Eligibility) -> dict[str, Any]:
    allocated = sum(a.amount_cents for a in inv.allocations)
    unlinked = inv.status == "paid" and not inv.allocations
    paid_cents = inv.total_cents - inv.balance_due_cents if unlinked else allocated
    notice = inv.autopay_status == AUTOPAY_ACTIVE_STATUS
    return {
        "invoice_id": inv.invoice_id,
        "invoice_number": inv.invoice_number,
        "period": inv.period,
        "student_id": inv.student_id,
        "student_name": inv.student_name,
        "enrollment_id": inv.enrollment_id,
        "status": inv.status,
        "total_cents": inv.total_cents,
        "paid_cents": paid_cents,
        "balance_due_cents": inv.balance_due_cents,
        "due_date": _iso(inv.due_date),
        "created_at": _iso(inv.created_at),
        "paid_at": _iso(inv.paid_at),
        "voided_at": _iso(inv.voided_at),
        "void_reason": inv.void_reason,
        "settlement_unlinked": unlinked,
        "delivery": {
            "status": inv.delivery_status,
            "last_sent_at": _iso(inv.last_sent_at),
            "kind": "autopay_notice" if notice else "invoice",
        },
        "allocations": [
            {
                "payment_id": a.payment_id,
                "amount_cents": a.amount_cents,
                "method": a.method,
                "paid_at": _iso(a.paid_at),
                "stripe_payment_intent_id": a.stripe_payment_intent_id,
            }
            for a in inv.allocations
        ],
        "credits": [{"credit_id": c.credit_id, "amount_cents": c.amount_cents} for c in inv.credits],
        "chargeable": eligibility.eligible,
        "actions": invoice_actions(inv, eligibility=eligibility),
    }


def build_family_billing_view(
    facts: FamilyFacts,
    *,
    timezone: str,
    generated_at: datetime,
    today: date,
) -> dict[str, Any]:
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(timezone)
    enrollments = _all_enrollments(facts)
    live = _live(enrollments)
    state = autopay_state(enrollments)
    autopay_by_enrollment = {e.enrollment_id: e.autopay_status for e in enrollments}

    invoice_rows: list[dict[str, Any]] = []
    next_charge: tuple[date, str] | None = None
    for inv in facts.invoices:
        elig = autopay_eligibility(
            invoice_status=inv.status,
            balance_due_cents=inv.balance_due_cents,
            enrollment_id=inv.enrollment_id,
            autopay_enrollment_status=autopay_by_enrollment.get(inv.enrollment_id or "", inv.autopay_status),
            has_payment_method=facts.customer.has_card,
            connected_account_ready=facts.connected_account_ready,
        )
        invoice_rows.append(_invoice_payload(inv, eligibility=elig))
        if elig.eligible and inv.due_date is not None:
            candidate = (inv.due_date, inv.invoice_id)
            if next_charge is None or candidate < next_charge:
                next_charge = candidate

    open_rows = [inv for inv in facts.invoices if inv.status in CHARGEABLE_INVOICE_STATUSES]
    balance = sum(inv.balance_due_cents for inv in open_rows)

    # Last payment: newest allocation paid_at across invoices, grouped by payment.
    last_payment: dict[str, Any] | None = None
    for inv in facts.invoices:
        for a in inv.allocations:
            if a.paid_at is None:
                continue
            if last_payment is None or a.paid_at > last_payment["_at"]:
                last_payment = {"_at": a.paid_at, "payment_id": a.payment_id}
    if last_payment is not None:
        pid = last_payment["payment_id"]
        settled = [inv for inv in facts.invoices if any(a.payment_id == pid for a in inv.allocations)]
        amount = sum(a.amount_cents for inv in settled for a in inv.allocations if a.payment_id == pid)
        method = next(a.method for inv in settled for a in inv.allocations if a.payment_id == pid)
        last_payment = {
            "amount_cents": amount,
            "method": method,
            "paid_at": _iso(last_payment["_at"]),
            "invoice_ids": [inv.invoice_id for inv in settled],
        }

    last_failure: dict[str, Any] | None = None
    for attempt in facts.attempts:
        if attempt.status in FAILURE_ATTEMPT_STATUSES and attempt.created_at is not None:
            if last_failure is None or attempt.created_at > last_failure["_at"]:
                last_failure = {"_at": attempt.created_at, "code": attempt.failure_message or attempt.status}
    if last_failure is not None:
        last_failure = {"code": last_failure["code"], "at": _iso(last_failure["_at"])}

    if facts.customer.has_card:
        registration = "registered"
    elif facts.customer.last_invited_at is not None:
        registration = "invited"
    else:
        registration = "not_invited"

    students = [
        {
            "student_id": s.student_id,
            "name": s.name,
            "status": s.status,
            "enrollments": [_enrollment_payload(e) for e in s.enrollments],
        }
        for s in facts.students
    ]

    return {
        "generated_at": _iso(generated_at),
        "timezone": timezone,
        "today": today.isoformat(),
        "parent": {
            "parent_id": facts.parent.parent_id,
            "name": facts.parent.name,
            "email": facts.parent.email,
            "phone": facts.parent.phone,
        },
        "header": {
            "balance_cents": balance,
            "open_invoice_count": len(open_rows),
            "available_credit_cents": facts.available_credit_cents,
            "last_payment": last_payment,
            "autopay": {
                "state": state,
                "active_count": sum(1 for e in live if e.autopay_status == AUTOPAY_ACTIVE_STATUS),
                "total_count": len(live),
                "card_last4": facts.customer.card_last4,
                "card_label": facts.customer.card_label,
                "next_charge_on": _iso(next_charge[0]) if next_charge else None,
                "next_charge_invoice_id": next_charge[1] if next_charge else None,
                "last_failure": last_failure,
            },
            "registration": {
                "state": registration,
                "card_on_file": bool(facts.customer.has_card),
                "last_invited_at": _iso(facts.customer.last_invited_at),
            },
            "enrollment_counts": {
                "active": sum(1 for e in enrollments if e.status == "active"),
                "paused": sum(1 for e in enrollments if e.status == _PAUSED),
                "cancelled": sum(1 for e in enrollments if e.status in _CANCELLED_ENROLLMENT_STATUSES),
            },
        },
        "students": students,
        "invoices": invoice_rows,
        "timeline": build_timeline(facts, zone=zone),
        "actions": family_actions(state=state, has_card=facts.customer.has_card, invoices=facts.invoices),
        "warnings": list(facts.warnings),
    }
```

Note: the three-sort dance in `build_timeline` exists because Python's sort is stable; the final two sorts (by code ascending, then by `at` descending) give "newest first, ties by code ascending". Delete the first `entries.sort(... reverse=True)` line — it is redundant. Keep the two stable sorts.

- [ ] **Step 4: Run tests until green**

Run: `.venv/bin/python -m pytest v2/tests/unit/test_family_billing.py -q`
Expected: PASS. If the timeline order test disagrees on ties, print `[(e["at"], e["code"]) for e in timeline]` and correct the expected list in the test only if the rule "newest first, ties by code ascending" is what the code does.

- [ ] **Step 5: Lint and commit**

```bash
cd backend && .venv/bin/ruff check v2/contexts/billing/application/family_billing.py v2/tests/unit/test_family_billing.py && .venv/bin/ruff format v2/contexts/billing/application/family_billing.py v2/tests/unit/test_family_billing.py
git add backend/v2/contexts/billing/application/family_billing.py backend/v2/tests/unit/test_family_billing.py
git commit -m "feat(billing): pure family billing rules — autopay state, actions, timeline"
```

---

### Task 3: Mongo read model (`family_billing_read_model.py`)

**Files:**
- Create: `backend/v2/contexts/billing/infrastructure/family_billing_read_model.py`
- Test: `backend/v2/tests/contract/test_family_billing_read_model.py`

**Interfaces:**
- Consumes: Task 2 facts and `build_family_billing_view`; Task 1 `MongoBillingAuditLogRepository.list_for_family`; `MongoParentBillingCustomerRepository.display_payment_method`, `get_for_parent` (check the exact reader name with `grep -n "async def" mongo_parent_billing_customer_repo.py`; use the one that returns the raw customer doc for a parent, or fall back to `self._db["parent_billing_customers"].find_one({"academy_id":..., "parent_id":...})`); `MongoCreditLedgerRepository.balance_for_parent(parent_id)`; `MongoUserRepository.list_existing_user_ids(ids, academy_id=)`; `academy_timezone_lookup(db)`; `MongoConnectedAccountRepository.get_for_academy()`, `MongoBillingSettingsRepository.get()`.
- Produces: `class MongoFamilyBillingReadModel(db, *, academy_timezone, connected_accounts, billing_settings, customers, credits, users, audit, clock=...)` with `async build(parent_id: str) -> dict[str, Any] | None` (None = parent not found in this tenant → route 404). Raises `FamilyBillingUnavailable` if a primary source (users/students/invoices) fails.

- [ ] **Step 1: Write the failing contract tests**

```python
# backend/v2/tests/contract/test_family_billing_read_model.py
"""mongomock contract tests for ``MongoFamilyBillingReadModel`` (spec §3, §8)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.infrastructure.family_billing_read_model import (
    MongoFamilyBillingReadModel,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.interfaces.admin.families_views import AdminFamilyBillingView
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup

NOW = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)


def _dt(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC)


def _read_model(db) -> MongoFamilyBillingReadModel:
    return MongoFamilyBillingReadModel(
        db,
        academy_timezone=academy_timezone_lookup(db),
        connected_accounts=MongoConnectedAccountRepository(db),
        billing_settings=MongoBillingSettingsRepository(db),
        customers=MongoParentBillingCustomerRepository(db),
        credits=MongoCreditLedgerRepository(db),
        users=MongoUserRepository(db),
        audit=MongoBillingAuditLogRepository(db),
        clock=lambda: NOW,
    )


async def _seed_family(db, acad: str, *, parent_id: str = "p-1") -> None:
    await db["academies"].insert_one({"academy_id": acad, "timezone": "America/Chicago"})
    await db["users"].insert_one(
        {
            "user_id": parent_id,
            "academy_id": acad,
            "display_name": "Sahaya Vinodh",
            "email": "s@example.com",
            "phone": "555-0100",
            "roles": ["parent"],
        }
    )
    await db["students"].insert_many(
        [
            {"academy_id": acad, "student_id": "s-arjun", "parent_id": parent_id, "full_name": "Arjun", "status": "active"},
            {"academy_id": acad, "student_id": "s-hannah", "parent_id": parent_id, "full_name": "Hannah", "status": "active"},
        ]
    )
    await db["sessions"].insert_many(
        [
            {"academy_id": acad, "session_id": "sess-sat", "title": "Sat 9:00 Beginners", "days_of_week": ["saturday"], "start_time": "09:00", "monthly_price_cents": 6000},
            {"academy_id": acad, "session_id": "sess-wed", "title": "Wed 6:15 Intermediate", "days_of_week": ["wednesday"], "start_time": "18:15", "monthly_price_cents": 7000},
        ]
    )
    await db["enrollments"].insert_many(
        [
            {"academy_id": acad, "enrollment_id": "e-arjun", "student_id": "s-arjun", "session_id": "sess-sat", "status": "active"},
            {"academy_id": acad, "enrollment_id": "e-hannah", "student_id": "s-hannah", "session_id": "sess-wed", "status": "paused"},
        ]
    )
    await db["student_billing_enrollments"].insert_many(
        [
            {"academy_id": acad, "enrollment_id": "e-arjun", "student_id": "s-arjun", "parent_id": parent_id, "status": "active", "autopay_enrollment_status": "active"},
            {"academy_id": acad, "enrollment_id": "e-hannah", "student_id": "s-hannah", "parent_id": parent_id, "status": "active", "autopay_enrollment_status": "paused", "override_price_cents": 6500},
        ]
    )
    await db["enrollment_billing_deferrals"].insert_one(
        {"academy_id": acad, "enrollment_id": "e-hannah", "resume_on": _dt(date(2026, 10, 1)), "created_at": NOW}
    )
    await db["parent_billing_customers"].insert_one(
        {"academy_id": acad, "parent_id": parent_id, "stripe_customer_id": "cus_1", "payment_method_label": "Visa", "payment_method_last4": "4242"}
    )
    await db["academy_connected_accounts"].insert_one(
        {"academy_id": acad, "stripe_account_id": "acct_1", "status": "active", "charges_enabled": True, "payouts_enabled": True, "details_submitted": True, "capabilities": {}, "created_at": NOW, "updated_at": NOW}
    )


async def _seed_invoices(db, acad: str, parent_id: str = "p-1") -> None:
    await db["invoices"].insert_many(
        [
            {
                "academy_id": acad, "invoice_id": "inv-sep-arjun", "invoice_number": "INV-3", "parent_id": parent_id,
                "student_id": "s-arjun", "enrollment_id": "e-arjun", "period": "2026-09", "status": "open",
                "total_cents": 6000, "balance_due_cents": 6000, "due_date": _dt(date(2026, 9, 8)),
                "delivery_status": "sent", "last_sent_at": datetime(2026, 9, 1, 6, 5, tzinfo=UTC),
                "created_at": datetime(2026, 9, 1, 6, 0, tzinfo=UTC),
            },
            {
                "academy_id": acad, "invoice_id": "inv-sep-hannah", "invoice_number": "INV-4", "parent_id": parent_id,
                "student_id": "s-hannah", "enrollment_id": "e-hannah", "period": "2026-09", "status": "void",
                "total_cents": 7000, "balance_due_cents": 0, "due_date": _dt(date(2026, 9, 8)),
                "void_reason": "enrollment paused", "voided_at": datetime(2026, 9, 4, 20, 0, tzinfo=UTC),
                "created_at": datetime(2026, 9, 1, 6, 0, tzinfo=UTC),
            },
            {
                "academy_id": acad, "invoice_id": "inv-aug-arjun", "invoice_number": "INV-1", "parent_id": parent_id,
                "student_id": "s-arjun", "enrollment_id": "e-arjun", "period": "2026-08", "status": "paid",
                "total_cents": 6000, "balance_due_cents": 0, "due_date": _dt(date(2026, 8, 8)),
                "paid_at": datetime(2026, 8, 4, 14, 0, tzinfo=UTC), "delivery_status": "sent",
                "last_sent_at": datetime(2026, 8, 1, 6, 5, tzinfo=UTC), "created_at": datetime(2026, 8, 1, 6, 0, tzinfo=UTC),
            },
        ]
    )
    await db["ledger_payments"].insert_one(
        {"academy_id": acad, "payment_id": "pay-aug", "parent_id": parent_id, "amount_cents": 6000, "payment_method": "card",
         "stripe_payment_intent_id": "pi_aug", "paid_at": datetime(2026, 8, 4, 14, 0, tzinfo=UTC), "created_at": NOW}
    )
    await db["payment_allocations"].insert_one(
        {"academy_id": acad, "payment_id": "pay-aug", "invoice_id": "inv-aug-arjun", "amount_cents": 6000}
    )
    await db["payment_attempts"].insert_one(
        {"academy_id": acad, "attempt_id": "at-1", "invoice_id": "inv-sep-arjun", "parent_id": parent_id, "amount_cents": 6000,
         "status": "declined", "failure_message": "Your card was declined.", "created_at": datetime(2026, 9, 8, 14, 0, tzinfo=UTC)}
    )
    await db["dunning_states"].insert_one(
        {"academy_id": acad, "invoice_id": "inv-sep-arjun", "status": "active", "attempt_count": 1,
         "last_notification_at": datetime(2026, 9, 8, 14, 1, tzinfo=UTC), "next_attempt_at": datetime(2026, 9, 11, 14, 0, tzinfo=UTC)}
    )
    await db["billing_audit_log"].insert_one(
        {"academy_id": acad, "audit_id": "a-1", "action": "autopay_paused", "actor_id": "admin-1", "parent_id": parent_id,
         "at": datetime(2026, 9, 4, 20, 1, tzinfo=UTC), "reason": "parent asked"}
    )
    await db["enrollment_events"].insert_one(
        {"academy_id": acad, "event_id": "ev-1", "event_type": "paused", "enrollment_id": "e-hannah", "student_id": "s-hannah",
         "occurred_at": datetime(2026, 9, 4, 19, 59, tzinfo=UTC), "actor_id": "admin-1", "reason": "travel",
         "effective_at": datetime(2026, 10, 1, 5, 0, tzinfo=UTC)}
    )


@pytest.mark.asyncio
async def test_full_family_view(db, acad) -> None:
    await _seed_family(db, acad)
    await _seed_invoices(db, acad)

    view = await _read_model(db).build("p-1")

    assert view is not None
    AdminFamilyBillingView.model_validate(view)  # shape matches the route model
    assert view["parent"] == {"parent_id": "p-1", "name": "Sahaya Vinodh", "email": "s@example.com", "phone": "555-0100"}
    header = view["header"]
    assert header["balance_cents"] == 6000
    assert header["open_invoice_count"] == 1
    assert header["autopay"]["state"] == "partial"
    assert header["autopay"]["card_last4"] == "4242"
    assert header["autopay"]["next_charge_on"] == "2026-09-08"
    assert header["autopay"]["next_charge_invoice_id"] == "inv-sep-arjun"
    assert header["last_payment"]["amount_cents"] == 6000
    assert header["last_payment"]["invoice_ids"] == ["inv-aug-arjun"]
    assert header["enrollment_counts"] == {"active": 1, "paused": 1, "cancelled": 0}

    students = {s["name"]: s for s in view["students"]}
    hannah = students["Hannah"]["enrollments"][0]
    assert hannah["session_title"] == "Wed 6:15 Intermediate"
    assert hannah["schedule"] == "Wed 18:15"
    assert hannah["monthly_price_cents"] == 7000
    assert hannah["override_price_cents"] == 6500
    assert hannah["resume_on"] == "2026-10-01"
    assert hannah["autopay_status"] == "paused"

    rows = {i["invoice_id"]: i for i in view["invoices"]}
    assert list(rows) == ["inv-sep-arjun", "inv-sep-hannah", "inv-aug-arjun"]  # period desc, then created desc
    assert rows["inv-aug-arjun"]["paid_cents"] == 6000
    assert rows["inv-aug-arjun"]["allocations"][0]["stripe_payment_intent_id"] == "pi_aug"
    assert rows["inv-aug-arjun"]["actions"] == ["refund"]
    assert rows["inv-sep-hannah"]["actions"] == []
    assert rows["inv-sep-arjun"]["chargeable"] is True

    codes = [e["code"] for e in view["timeline"]]
    assert codes[:3] == ["failure_notice_emailed", "charge_failed", "audit:autopay_paused"]
    assert "enrollment:paused" in codes
    assert "payment_received" in codes
    assert view["actions"] == ["autopay_on", "autopay_off", "send_invoice", "record_payment"]
    assert view["warnings"] == []


@pytest.mark.asyncio
async def test_unknown_or_foreign_parent_is_none(db, acad) -> None:
    await _seed_family(db, "other-acad")
    assert await _read_model(db).build("p-1") is None
    assert await _read_model(db).build("nobody") is None


@pytest.mark.asyncio
async def test_parent_with_no_students_or_invoices(db, acad) -> None:
    await db["academies"].insert_one({"academy_id": acad, "timezone": "America/Chicago"})
    await db["users"].insert_one({"user_id": "p-empty", "academy_id": acad, "display_name": "New Parent", "roles": ["parent"]})

    view = await _read_model(db).build("p-empty")

    assert view is not None
    assert view["students"] == []
    assert view["invoices"] == []
    assert view["timeline"] == []
    assert view["header"]["autopay"]["state"] == "needs_consent"
    assert view["header"]["registration"]["state"] == "not_invited"
    assert view["actions"] == ["send_invite"]


@pytest.mark.asyncio
async def test_foreign_tenant_invoices_for_same_parent_id_are_invisible(db, acad) -> None:
    await _seed_family(db, acad)
    await db["invoices"].insert_one(
        {"academy_id": "other-acad", "invoice_id": "inv-foreign", "parent_id": "p-1", "period": "2026-09",
         "status": "open", "total_cents": 99999, "balance_due_cents": 99999, "due_date": _dt(date(2026, 9, 8))}
    )

    view = await _read_model(db).build("p-1")

    assert view is not None
    assert [i["invoice_id"] for i in view["invoices"]] == []


@pytest.mark.asyncio
async def test_secondary_source_failure_becomes_a_warning(db, acad, monkeypatch) -> None:
    await _seed_family(db, acad)
    await _seed_invoices(db, acad)
    model = _read_model(db)

    async def boom(*_a, **_k):
        raise RuntimeError("attempts down")

    monkeypatch.setattr(model, "_attempts", boom)

    view = await model.build("p-1")

    assert view is not None
    assert view["warnings"] == ["attempts_unavailable"]
    assert "charge_failed" not in [e["code"] for e in view["timeline"]]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest v2/tests/contract/test_family_billing_read_model.py -q`
Expected: FAIL with `ModuleNotFoundError` (the views module arrives in Task 5; until then, comment out the `AdminFamilyBillingView` import and assertion, and restore them in Task 5).

- [ ] **Step 3: Implement the read model**

```python
# backend/v2/contexts/billing/infrastructure/family_billing_read_model.py
"""Mongo read model behind ``GET /admin/families/{parent_id}/billing``.

Spec: ``docs/superpowers/specs/2026-09-05-family-billing-design.md`` §3.1.

A fixed number of batched reads for ONE parent, every one scoped by the request
tenant (``current_academy_id()`` resolved at build time, never at composition
time), handed to the pure builder in :mod:`family_billing`. Nothing here
decides an action or an autopay state.

Error handling (spec §7): the parent, students and invoices are primary — if
they fail the build raises. Attempts, dunning, audit, events, discounts and
the customer row are secondary — a failure logs, leaves that source empty and
adds a ``warnings`` entry so the page still renders.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from bson import ObjectId

from backend.v2.contexts.billing.application.family_billing import (
    AllocationFacts,
    AttemptFacts,
    AuditFacts,
    CreditFacts,
    CustomerFacts,
    DunningFacts,
    EnrollmentFacts,
    EventFacts,
    FamilyFacts,
    InvoiceFacts,
    ParentFacts,
    StudentFacts,
    build_family_billing_view,
)
from backend.v2.contexts.billing.domain.payment_attempt_kinds import (
    exclude_non_charge_attempts,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.shared.tenancy import current_academy_id

log = logging.getLogger(__name__)

INVOICE_CAP = 200
_UTC_NAME = "UTC"
_WEEKDAY_SHORT = {
    "monday": "Mon", "mon": "Mon", "tuesday": "Tue", "tue": "Tue", "wednesday": "Wed", "wed": "Wed",
    "thursday": "Thu", "thu": "Thu", "friday": "Fri", "fri": "Fri", "saturday": "Sat", "sat": "Sat",
    "sunday": "Sun", "sun": "Sun",
}


class FamilyBillingUnavailable(RuntimeError):
    """A primary source (parent, students, invoices) could not be read."""


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, str) and value:
        try:
            return _as_utc(datetime.fromisoformat(value))
        except ValueError:
            return None
    return None


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _opt_int(value: Any) -> int | None:
    return None if value is None else _int(value)


def _student_name(doc: dict[str, Any]) -> str:
    full = _opt_str(doc.get("full_name"))
    if full:
        return full
    joined = " ".join(p for p in (_opt_str(doc.get("first_name")), _opt_str(doc.get("last_name"))) if p)
    return joined or str(doc.get("student_id") or "Student")


def _schedule(session: dict[str, Any] | None) -> str | None:
    if not session:
        return None
    days = session.get("days_of_week") or []
    if isinstance(days, str):
        days = [days]
    labels = [_WEEKDAY_SHORT.get(str(d).lower(), str(d)[:3].title()) for d in days]
    start = _opt_str(session.get("start_time"))
    parts = [", ".join(labels)] if labels else []
    if start:
        parts.append(start)
    return " ".join(parts) or None


class MongoFamilyBillingReadModel:
    """Batched facts → ``build_family_billing_view`` for one parent."""

    def __init__(
        self,
        db: Any,
        *,
        academy_timezone: Callable[[str], Awaitable[str | None]],
        connected_accounts: Any,
        billing_settings: Any,
        customers: Any,
        credits: Any,
        users: Any,
        audit: Any,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._db = db
        self._academy_timezone = academy_timezone
        self._connected_accounts = connected_accounts
        self._billing_settings = billing_settings
        self._customers = customers
        self._credits = credits
        self._users = users
        self._audit = audit
        self._clock = clock

    # ------------------------------------------------------------------ entry

    async def build(self, parent_id: str) -> dict[str, Any] | None:
        academy_id = current_academy_id()
        now = _as_utc(self._clock())
        tz_name = await self._resolve_timezone(academy_id)
        today = now.astimezone(ZoneInfo(tz_name)).date()
        warnings: list[str] = []

        try:
            parent = await self._parent(academy_id, parent_id)
            if parent is None:
                return None
            student_docs = await self._students(academy_id, parent_id)
            invoice_docs = await self._invoices(academy_id, parent_id)
        except Exception as exc:  # primary sources
            raise FamilyBillingUnavailable(str(exc)) from exc

        student_ids = [s["student_id"] for s in student_docs]
        enrollment_docs = await self._enrollments(academy_id, student_ids)
        enrollment_ids = [e["enrollment_id"] for e in enrollment_docs]
        session_by_id = await self._sessions(academy_id, {e["session_id"] for e in enrollment_docs if e.get("session_id")})
        billing_by_enrollment = await self._billing_enrollments(academy_id, enrollment_ids)
        deferral_by_enrollment = await self._deferrals(academy_id, enrollment_ids)
        discounts = await self._secondary("discounts_unavailable", warnings, self._discounts(academy_id, enrollment_ids), {})

        invoice_ids = [inv["invoice_id"] for inv in invoice_docs]
        allocations_by_invoice, payment_ids = await self._allocations(academy_id, invoice_ids)
        credits_by_invoice = await self._secondary("credits_unavailable", warnings, self._credit_applications(academy_id, invoice_ids), {})
        attempts = await self._secondary("attempts_unavailable", warnings, self._attempts(academy_id, invoice_ids), [])
        dunning = await self._secondary("dunning_unavailable", warnings, self._dunning(academy_id, invoice_ids), [])
        audit = await self._secondary(
            "audit_unavailable", warnings,
            self._audit.list_for_family(parent_id=parent_id, invoice_ids=invoice_ids, payment_ids=payment_ids, enrollment_ids=enrollment_ids),
            [],
        )
        events = await self._secondary("events_unavailable", warnings, self._events(academy_id, enrollment_ids), [])
        available_credit = await self._secondary("credits_unavailable", warnings, self._credits.balance_for_parent(parent_id), 0)
        customer = await self._customer(academy_id, parent_id, warnings)
        connected_ready = await self._connected_account_ready()

        name_by_student = {s["student_id"]: _student_name(s) for s in student_docs}
        name_by_enrollment = {e["enrollment_id"]: name_by_student.get(e["student_id"], "Student") for e in enrollment_docs}
        autopay_by_enrollment = {eid: _opt_str(doc.get("autopay_enrollment_status")) for eid, doc in billing_by_enrollment.items()}

        students = tuple(
            StudentFacts(
                student_id=s["student_id"],
                name=name_by_student[s["student_id"]],
                status=_opt_str(s.get("status")),
                enrollments=tuple(
                    self._enrollment_facts(e, session_by_id.get(e.get("session_id") or ""), billing_by_enrollment.get(e["enrollment_id"]), deferral_by_enrollment.get(e["enrollment_id"]), discounts.get(e["enrollment_id"]))
                    for e in enrollment_docs
                    if e["student_id"] == s["student_id"]
                ),
            )
            for s in student_docs
        )
        invoices = tuple(
            self._invoice_facts(
                inv,
                student_name=name_by_student.get(str(inv.get("student_id") or "")),
                autopay_status=autopay_by_enrollment.get(str(inv.get("enrollment_id") or "")),
                allocations=allocations_by_invoice.get(inv["invoice_id"], ()),
                credits=credits_by_invoice.get(inv["invoice_id"], ()),
            )
            for inv in invoice_docs
        )
        facts = FamilyFacts(
            parent=parent,
            students=students,
            invoices=invoices,
            attempts=tuple(attempts),
            dunning=tuple(dunning),
            audit=tuple(
                AuditFacts(
                    audit_id=a.audit_id, action=a.action, actor_id=a.actor_id, at=_as_utc(a.at),
                    invoice_id=a.invoice_id, payment_id=a.payment_id, reason=a.reason, before=a.before, after=a.after,
                )
                for a in audit
            ),
            events=tuple(
                EventFacts(
                    event_id=str(ev.get("event_id") or ev.get("_id")),
                    event_type=str(ev.get("event_type") or ""),
                    enrollment_id=str(ev.get("enrollment_id") or ""),
                    student_name=name_by_enrollment.get(str(ev.get("enrollment_id") or "")),
                    occurred_at=_to_datetime(ev.get("occurred_at")) or now,
                    actor_id=_opt_str(ev.get("actor_id")),
                    reason=_opt_str(ev.get("reason")),
                    effective_at=_to_datetime(ev.get("effective_at")),
                )
                for ev in events
            ),
            customer=customer,
            available_credit_cents=_int(available_credit),
            connected_account_ready=connected_ready,
            warnings=tuple(dict.fromkeys(warnings)),
        )
        if warnings:
            log.warning("family billing read model: %s for parent %s", warnings, parent_id)
        return build_family_billing_view(facts, timezone=tz_name, generated_at=now, today=today)

    # ------------------------------------------------------------------ shaping

    @staticmethod
    def _enrollment_facts(e, session, billing, deferral, discount) -> EnrollmentFacts:
        billing = billing or {}
        return EnrollmentFacts(
            enrollment_id=e["enrollment_id"],
            student_id=e["student_id"],
            session_id=_opt_str(e.get("session_id")),
            session_title=_opt_str((session or {}).get("title")) or _opt_str((session or {}).get("name")),
            schedule=_schedule(session),
            status=str(e.get("status") or ""),
            monthly_price_cents=_opt_int((session or {}).get("monthly_price_cents")),
            override_price_cents=_opt_int(billing.get("override_price_cents")),
            autopay_status=_opt_str(billing.get("autopay_enrollment_status")),
            recurring_discount=discount,
            resume_on=_to_date((deferral or {}).get("resume_on")),
        )

    @staticmethod
    def _invoice_facts(inv, *, student_name, autopay_status, allocations, credits) -> InvoiceFacts:
        return InvoiceFacts(
            invoice_id=inv["invoice_id"],
            invoice_number=_opt_str(inv.get("invoice_number")),
            period=str(inv.get("period") or ""),
            student_id=_opt_str(inv.get("student_id")),
            student_name=student_name,
            enrollment_id=_opt_str(inv.get("enrollment_id")),
            status=str(inv.get("status") or ""),
            total_cents=_int(inv.get("total_cents")),
            balance_due_cents=_int(inv.get("balance_due_cents")),
            due_date=_to_date(inv.get("due_date")),
            created_at=_to_datetime(inv.get("created_at")),
            paid_at=_to_datetime(inv.get("paid_at")),
            voided_at=_to_datetime(inv.get("voided_at")),
            void_reason=_opt_str(inv.get("void_reason")),
            delivery_status=str(inv.get("delivery_status") or "not_sent"),
            last_sent_at=_to_datetime(inv.get("last_sent_at")),
            autopay_status=autopay_status,
            allocations=tuple(allocations),
            credits=tuple(credits),
        )

    # ------------------------------------------------------------------ queries
    # Every query carries ``academy_id`` except ``users`` (global, keyed by user id).

    async def _secondary(self, warning: str, warnings: list[str], coro: Awaitable[Any], fallback: Any) -> Any:
        try:
            return await coro
        except Exception:
            log.warning("family billing read model: %s", warning, exc_info=True)
            warnings.append(warning)
            return fallback

    async def _resolve_timezone(self, academy_id: str) -> str:
        try:
            name = await self._academy_timezone(academy_id)
        except Exception:
            log.warning("family billing read model: timezone lookup failed", exc_info=True)
            name = None
        if not name:
            return _UTC_NAME
        try:
            ZoneInfo(name)
        except Exception:
            return _UTC_NAME
        return name

    async def _parent(self, academy_id: str, parent_id: str) -> ParentFacts | None:
        raw_ids: list[Any] = [parent_id]
        if ObjectId.is_valid(parent_id):
            raw_ids.append(ObjectId(parent_id))
        doc = await self._db["users"].find_one(
            {"$or": [{"user_id": parent_id}, {"auth_uid": parent_id}, {"_id": {"$in": raw_ids}}]},
            {"user_id": 1, "display_name": 1, "name": 1, "email": 1, "phone": 1, "roles": 1, "role": 1, "academy_id": 1},
        )
        if doc is None:
            return None
        # A parent belongs to this tenant when they have a student here or a
        # membership here; the students query below is tenant-scoped, so a
        # user with no student AND no membership in this academy is a 404.
        if not await self._belongs_to_tenant(academy_id, parent_id):
            return None
        return ParentFacts(
            parent_id=parent_id,
            name=_opt_str(doc.get("display_name")) or _opt_str(doc.get("name")),
            email=_opt_str(doc.get("email")),
            phone=_opt_str(doc.get("phone")),
        )

    async def _belongs_to_tenant(self, academy_id: str, parent_id: str) -> bool:
        if await self._db["students"].find_one({"academy_id": academy_id, "parent_id": parent_id}, {"_id": 1}):
            return True
        if await self._db["academy_memberships"].find_one({"academy_id": academy_id, "user_id": parent_id}, {"_id": 1}):
            return True
        return bool(await self._db["users"].find_one({"user_id": parent_id, "academy_id": academy_id}, {"_id": 1}))

    async def _students(self, academy_id: str, parent_id: str) -> list[dict[str, Any]]:
        cursor = self._db["students"].find(
            {"academy_id": academy_id, "parent_id": parent_id, "is_deleted": {"$ne": True}},
            {"_id": 0, "student_id": 1, "full_name": 1, "first_name": 1, "last_name": 1, "status": 1},
        )
        docs = [doc async for doc in cursor if doc.get("student_id")]
        for doc in docs:
            doc["student_id"] = str(doc["student_id"])
        docs.sort(key=lambda d: (_student_name(d), d["student_id"]))
        return docs

    async def _enrollments(self, academy_id: str, student_ids: list[str]) -> list[dict[str, Any]]:
        if not student_ids:
            return []
        cursor = self._db["enrollments"].find(
            {"academy_id": academy_id, "student_id": {"$in": student_ids}},
            {"_id": 0, "enrollment_id": 1, "student_id": 1, "session_id": 1, "status": 1},
        )
        docs = [doc async for doc in cursor if doc.get("enrollment_id") and doc.get("student_id")]
        for doc in docs:
            doc["enrollment_id"] = str(doc["enrollment_id"])
            doc["student_id"] = str(doc["student_id"])
        docs.sort(key=lambda d: (d.get("status") != "active", d["enrollment_id"]))
        return docs

    async def _sessions(self, academy_id: str, session_ids: set[str]) -> dict[str, dict[str, Any]]:
        if not session_ids:
            return {}
        cursor = self._db["sessions"].find(
            {"academy_id": academy_id, "session_id": {"$in": sorted(session_ids)}},
            {"_id": 0, "session_id": 1, "title": 1, "name": 1, "days_of_week": 1, "start_time": 1, "monthly_price_cents": 1},
        )
        return {str(doc["session_id"]): doc async for doc in cursor}

    async def _billing_enrollments(self, academy_id: str, enrollment_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not enrollment_ids:
            return {}
        cursor = self._db["student_billing_enrollments"].find(
            {"academy_id": academy_id, "enrollment_id": {"$in": enrollment_ids}},
            {"_id": 0, "enrollment_id": 1, "autopay_enrollment_status": 1, "override_price_cents": 1, "last_attempt_outcome": 1, "last_failure_code": 1},
        )
        return {str(doc["enrollment_id"]): doc async for doc in cursor}

    async def _deferrals(self, academy_id: str, enrollment_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not enrollment_ids:
            return {}
        cursor = self._db["enrollment_billing_deferrals"].find(
            {"academy_id": academy_id, "enrollment_id": {"$in": enrollment_ids}},
            {"_id": 0, "enrollment_id": 1, "resume_on": 1, "review_on": 1, "created_at": 1},
            sort=[("created_at", -1)],
        )
        out: dict[str, dict[str, Any]] = {}
        async for doc in cursor:
            out.setdefault(str(doc["enrollment_id"]), doc)
        return out

    async def _discounts(self, academy_id: str, enrollment_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not enrollment_ids:
            return {}
        cursor = self._db["enrollment_discounts"].find(
            {"academy_id": academy_id, "enrollment_id": {"$in": enrollment_ids}, "status": "active"},
            {"_id": 0, "enrollment_id": 1, "discount_id": 1, "category": 1, "category_label": 1, "kind": 1, "amount_cents": 1, "percent": 1, "note": 1},
        )
        return {str(doc["enrollment_id"]): doc async for doc in cursor}

    async def _invoices(self, academy_id: str, parent_id: str) -> list[dict[str, Any]]:
        cursor = self._db["invoices"].find(
            {
                "academy_id": academy_id,
                "$or": [{"parent_id": parent_id}, {"parent_user_id": parent_id}],
                "is_deleted": {"$ne": True},
            },
            {
                "_id": 0, "invoice_id": 1, "invoice_number": 1, "student_id": 1, "enrollment_id": 1, "period": 1,
                "status": 1, "total_cents": 1, "balance_due_cents": 1, "due_date": 1, "created_at": 1, "paid_at": 1,
                "voided_at": 1, "void_reason": 1, "delivery_status": 1, "last_sent_at": 1,
            },
        )
        docs = [doc async for doc in cursor if doc.get("invoice_id")]
        for doc in docs:
            doc["invoice_id"] = str(doc["invoice_id"])
        docs.sort(key=lambda d: (str(d.get("period") or ""), _to_datetime(d.get("created_at")) or datetime.min.replace(tzinfo=UTC), d["invoice_id"]), reverse=True)
        return docs[:INVOICE_CAP]

    async def _allocations(self, academy_id: str, invoice_ids: list[str]) -> tuple[dict[str, list[AllocationFacts]], list[str]]:
        if not invoice_ids:
            return {}, []
        alloc_cursor = self._db["payment_allocations"].find(
            {"academy_id": academy_id, "invoice_id": {"$in": invoice_ids}},
            {"_id": 0, "invoice_id": 1, "payment_id": 1, "amount_cents": 1},
        )
        allocations = [doc async for doc in alloc_cursor if doc.get("payment_id")]
        payment_ids = sorted({str(a["payment_id"]) for a in allocations})
        payments: dict[str, dict[str, Any]] = {}
        if payment_ids:
            pay_cursor = self._db["ledger_payments"].find(
                {"academy_id": academy_id, "payment_id": {"$in": payment_ids}},
                {"_id": 0, "payment_id": 1, "payment_method": 1, "paid_at": 1, "created_at": 1, "stripe_payment_intent_id": 1},
            )
            payments = {str(doc["payment_id"]): doc async for doc in pay_cursor}
        out: dict[str, list[AllocationFacts]] = {}
        for a in allocations:
            payment = payments.get(str(a["payment_id"]), {})
            out.setdefault(str(a["invoice_id"]), []).append(
                AllocationFacts(
                    payment_id=str(a["payment_id"]),
                    amount_cents=_int(a.get("amount_cents")),
                    method=_opt_str(payment.get("payment_method")),
                    paid_at=_to_datetime(payment.get("paid_at")) or _to_datetime(payment.get("created_at")),
                    stripe_payment_intent_id=_opt_str(payment.get("stripe_payment_intent_id")),
                )
            )
        return out, payment_ids

    async def _credit_applications(self, academy_id: str, invoice_ids: list[str]) -> dict[str, list[CreditFacts]]:
        if not invoice_ids:
            return {}
        cursor = self._db["credit_applications"].find(
            {"academy_id": academy_id, "invoice_id": {"$in": invoice_ids}},
            {"_id": 0, "invoice_id": 1, "credit_id": 1, "amount_cents": 1},
        )
        out: dict[str, list[CreditFacts]] = {}
        async for doc in cursor:
            out.setdefault(str(doc["invoice_id"]), []).append(
                CreditFacts(credit_id=str(doc.get("credit_id") or ""), amount_cents=_int(doc.get("amount_cents")))
            )
        return out

    async def _attempts(self, academy_id: str, invoice_ids: list[str]) -> list[AttemptFacts]:
        if not invoice_ids:
            return []
        cursor = self._db["payment_attempts"].find(
            exclude_non_charge_attempts({"academy_id": academy_id, "invoice_id": {"$in": invoice_ids}}),
            {"_id": 0, "attempt_id": 1, "invoice_id": 1, "status": 1, "failure_message": 1, "failure_code": 1, "amount_cents": 1, "created_at": 1},
            sort=[("created_at", 1)],
        )
        return [
            AttemptFacts(
                attempt_id=str(doc.get("attempt_id") or ""),
                invoice_id=str(doc["invoice_id"]),
                status=str(doc.get("status") or ""),
                failure_message=_opt_str(doc.get("failure_message")) or _opt_str(doc.get("failure_code")),
                amount_cents=_int(doc.get("amount_cents")),
                created_at=_to_datetime(doc.get("created_at")),
            )
            async for doc in cursor
        ]

    async def _dunning(self, academy_id: str, invoice_ids: list[str]) -> list[DunningFacts]:
        if not invoice_ids:
            return []
        cursor = self._db["dunning_states"].find(
            {"academy_id": academy_id, "invoice_id": {"$in": invoice_ids}},
            {"_id": 0, "invoice_id": 1, "status": 1, "attempt_count": 1, "autopay_disabled_at": 1, "last_notification_at": 1},
        )
        return [
            DunningFacts(
                invoice_id=str(doc["invoice_id"]),
                status=_opt_str(doc.get("status")),
                attempt_count=_int(doc.get("attempt_count")),
                autopay_disabled_at=_to_datetime(doc.get("autopay_disabled_at")),
                last_notification_at=_to_datetime(doc.get("last_notification_at")),
            )
            async for doc in cursor
        ]

    async def _events(self, academy_id: str, enrollment_ids: list[str]) -> list[dict[str, Any]]:
        if not enrollment_ids:
            return []
        cursor = self._db["enrollment_events"].find(
            {"academy_id": academy_id, "enrollment_id": {"$in": enrollment_ids}},
            {"_id": 1, "event_id": 1, "event_type": 1, "enrollment_id": 1, "occurred_at": 1, "actor_id": 1, "reason": 1, "effective_at": 1},
            sort=[("occurred_at", -1)],
            limit=INVOICE_CAP,
        )
        return [doc async for doc in cursor]

    async def _customer(self, academy_id: str, parent_id: str, warnings: list[str]) -> CustomerFacts:
        has_login = False
        try:
            has_login = parent_id in await self._users.list_existing_user_ids([parent_id], academy_id=academy_id)
        except Exception:
            log.warning("family billing read model: login lookup failed", exc_info=True)
        try:
            doc = await self._db["parent_billing_customers"].find_one({"academy_id": academy_id, "parent_id": parent_id})
        except Exception:
            log.warning("family billing read model: customer lookup failed", exc_info=True)
            warnings.append("customer_unavailable")
            return CustomerFacts(has_card=None, card_last4=None, card_label=None, last_invited_at=None, has_login_account=has_login)
        if doc is None:
            return CustomerFacts(has_card=False, card_last4=None, card_label=None, last_invited_at=None, has_login_account=has_login)
        label, last4 = MongoParentBillingCustomerRepository.display_payment_method(doc)
        return CustomerFacts(
            has_card=(label, last4) != (None, None),
            card_last4=last4,
            card_label=label,
            last_invited_at=_to_datetime(doc.get("billing_setup_last_invited_at")),
            has_login_account=has_login,
        )

    async def _connected_account_ready(self) -> bool | None:
        try:
            account = await self._connected_accounts.get_for_academy()
            settings = await self._billing_settings.get()
        except Exception:
            log.warning("family billing read model: connected-account lookup failed", exc_info=True)
            return None
        ready = account is not None and account.is_ready_for_charges()
        return bool(ready or getattr(settings, "allow_platform_charge_fallback", False))
```

Notes for the implementer: `MongoCreditLedgerRepository(db)` and `MongoUserRepository(db)` constructor shapes — check `grep -n "def __init__" -A3` on both; `MongoCreditLedgerRepository` is a `TenantScopedRepository` (constructor takes `db`). `_belongs_to_tenant` is what makes a foreign parent a 404 — keep all three checks. If mongomock rejects `sort=` as a `find()` kwarg, chain `.sort(...)` instead (the collections read model uses the kwarg form successfully, so it should be fine).

- [ ] **Step 4: Run the contract tests**

Run: `.venv/bin/python -m pytest v2/tests/contract/test_family_billing_read_model.py -q`
Expected: PASS (5 tests; the view-shape assertion is re-enabled in Task 5).

- [ ] **Step 5: Lint and commit**

```bash
cd backend && .venv/bin/ruff check v2/contexts/billing/infrastructure/family_billing_read_model.py v2/tests/contract/test_family_billing_read_model.py && .venv/bin/ruff format v2/contexts/billing/infrastructure/family_billing_read_model.py v2/tests/contract/test_family_billing_read_model.py
git add backend/v2/contexts/billing/infrastructure/family_billing_read_model.py backend/v2/tests/contract/test_family_billing_read_model.py
git commit -m "feat(billing): family billing Mongo read model"
```

---

### Task 4: `PauseFamilyAutopay` use case

**Files:**
- Create: `backend/v2/contexts/billing/application/use_cases/pause_family_autopay.py`
- Test: `backend/v2/tests/unit/test_pause_family_autopay.py`

**Interfaces:**
- Consumes: `StudentBillingEnrollment` (domain, `.enrollment_id`, `.autopay_enrollment_status`), `BillingAuditEntry` (Task 1 with `parent_id`), an idempotency store with `get(key) -> dict | None` / `put(key, value)`.
- Produces: `class PauseFamilyAutopay(*, enrollments, audit, idempotency, clock=...)`, `async execute(*, academy_id, parent_id, actor_id, reason, request_id) -> PauseFamilyAutopayResult(paused_count: int, active_count_before: int, warnings: list[str])`; raises `NothingToPause` (ValueError subclass) when no enrollment is `active`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/v2/tests/unit/test_pause_family_autopay.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.pause_family_autopay import (
    NothingToPause,
    PauseFamilyAutopay,
)
from backend.v2.contexts.billing.domain.session_type import StudentBillingEnrollment

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _sbe(eid: str, status: str) -> StudentBillingEnrollment:
    return StudentBillingEnrollment(
        enrollment_id=eid, academy_id="acad", student_id="s-1", parent_id="p-1",
        session_type_id="st-1", billing_start_date=NOW, autopay_enrollment_status=status,  # type: ignore[arg-type]
    )


class FakeEnrollments:
    def __init__(self, rows):
        self.rows = {r.enrollment_id: r for r in rows}
        self.writes: list[tuple[str, str]] = []
        self.reject: set[str] = set()

    async def list_for_parent(self, parent_id: str):
        return list(self.rows.values())

    async def set_autopay_enrollment_status(self, *, enrollment_id: str, status: str) -> bool:
        self.writes.append((enrollment_id, status))
        return enrollment_id not in self.reject


class FakeAudit:
    def __init__(self):
        self.entries = []

    async def append(self, entry):
        self.entries.append(entry)


class FakeIdem:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def put(self, key, value):
        self.store[key] = value


def _uc(enrollments, audit=None, idem=None):
    return PauseFamilyAutopay(
        enrollments=enrollments, audit=audit or FakeAudit(), idempotency=idem or FakeIdem(), clock=lambda: NOW
    )


@pytest.mark.asyncio
async def test_pauses_only_active_enrollments_and_audits_once() -> None:
    enr = FakeEnrollments([_sbe("e-1", "active"), _sbe("e-2", "paused"), _sbe("e-3", "active")])
    audit = FakeAudit()

    result = await _uc(enr, audit).execute(
        academy_id="acad", parent_id="p-1", actor_id="admin-1", reason="moving away", request_id="req-1"
    )

    assert result.paused_count == 2
    assert result.active_count_before == 2
    assert result.warnings == []
    assert sorted(enr.writes) == [("e-1", "paused"), ("e-3", "paused")]
    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry.action == "autopay_paused"
    assert entry.parent_id == "p-1"
    assert entry.reason == "moving away"
    assert entry.audit_id == "baud-family-autopay-pause-acad-p-1-req-1"
    assert entry.before == {"enrollment_ids": ["e-1", "e-3"], "status": "active"}
    assert entry.after == {"enrollment_ids": ["e-1", "e-3"], "status": "paused"}


@pytest.mark.asyncio
async def test_nothing_active_raises() -> None:
    with pytest.raises(NothingToPause):
        await _uc(FakeEnrollments([_sbe("e-1", "paused")])).execute(
            academy_id="acad", parent_id="p-1", actor_id="a", reason="x", request_id="r"
        )


@pytest.mark.asyncio
async def test_replay_with_same_request_id_returns_first_result_without_rewriting() -> None:
    enr = FakeEnrollments([_sbe("e-1", "active")])
    idem = FakeIdem()
    audit = FakeAudit()
    first = await _uc(enr, audit, idem).execute(academy_id="acad", parent_id="p-1", actor_id="a", reason="x", request_id="r")
    enr.rows["e-1"] = _sbe("e-1", "paused")

    second = await _uc(enr, audit, idem).execute(academy_id="acad", parent_id="p-1", actor_id="a", reason="x", request_id="r")

    assert second == first
    assert enr.writes == [("e-1", "paused")]
    assert len(audit.entries) == 1


@pytest.mark.asyncio
async def test_rejected_transition_is_reported_not_raised() -> None:
    enr = FakeEnrollments([_sbe("e-1", "active"), _sbe("e-2", "active")])
    enr.reject.add("e-2")

    result = await _uc(enr).execute(academy_id="acad", parent_id="p-1", actor_id="a", reason="x", request_id="r")

    assert result.paused_count == 1
    assert result.warnings == ["e-2: transition rejected"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest v2/tests/unit/test_pause_family_autopay.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/v2/contexts/billing/application/use_cases/pause_family_autopay.py
"""Family billing "Autopay OFF": pause every active enrollment of one parent.

Spec ``2026-09-05-family-billing-design.md`` §5. Mirrors the Billing Setup
enable path (``composition/admin.py::enable_billing_setup_autopay``): the
target list is persisted under an idempotency key BEFORE any write so a retry
finishes the same plan, each enrollment goes through the ONE guarded status
write, and one audit entry records who/why. Invoices and dunning states are
untouched — the worker skips non-active enrollments on its own.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.application.autopay_eligibility import AUTOPAY_ACTIVE_STATUS
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry

PAUSED_STATUS = "paused"


class NothingToPause(ValueError):
    """The parent has no enrollment with autopay ``active``."""


class FamilyAutopayEnrollments(Protocol):
    async def list_for_parent(self, parent_id: str) -> list[Any]: ...

    async def set_autopay_enrollment_status(self, *, enrollment_id: str, status: Any) -> bool: ...


class AuditAppender(Protocol):
    async def append(self, entry: BillingAuditEntry) -> None: ...


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...

    async def put(self, key: str, value: dict[str, Any]) -> None: ...


@dataclass(frozen=True)
class PauseFamilyAutopayResult:
    paused_count: int
    active_count_before: int
    warnings: list[str] = field(default_factory=list)


class PauseFamilyAutopay:
    def __init__(
        self,
        *,
        enrollments: FamilyAutopayEnrollments,
        audit: AuditAppender,
        idempotency: IdempotencyStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._audit = audit
        self._idempotency = idempotency
        self._clock = clock

    async def execute(
        self, *, academy_id: str, parent_id: str, actor_id: str, reason: str, request_id: str
    ) -> PauseFamilyAutopayResult:
        idem_key = f"family_autopay_pause:{academy_id}:{parent_id}:{request_id}"
        cached = await self._idempotency.get(idem_key)
        if cached is not None and "result" in cached:
            r = cached["result"]
            return PauseFamilyAutopayResult(int(r["paused_count"]), int(r["active_count_before"]), list(r.get("warnings", [])))

        if cached is None:
            rows = await self._enrollments.list_for_parent(parent_id)
            targets = sorted(
                r.enrollment_id for r in rows if r.autopay_enrollment_status == AUTOPAY_ACTIVE_STATUS
            )
            if not targets:
                raise NothingToPause("no_active_autopay: parent has no enrollment on autopay")
            plan = {"target_enrollment_ids": targets}
            try:
                await self._idempotency.put(idem_key, {"plan": plan})
            except DuplicateKeyError:
                cached = await self._idempotency.get(idem_key)
                if cached is None:
                    raise
                plan = cached["plan"]
        else:
            plan = cached["plan"]

        targets = list(plan["target_enrollment_ids"])
        paused: list[str] = []
        warnings: list[str] = []
        for enrollment_id in targets:
            ok = await self._enrollments.set_autopay_enrollment_status(
                enrollment_id=enrollment_id, status=PAUSED_STATUS
            )
            if ok:
                paused.append(enrollment_id)
            else:
                warnings.append(f"{enrollment_id}: transition rejected")

        await self._audit.append(
            BillingAuditEntry(
                audit_id=f"baud-family-autopay-pause-{academy_id}-{parent_id}-{request_id}",
                academy_id=academy_id,
                action="autopay_paused",
                actor_id=actor_id,
                at=self._clock(),
                parent_id=parent_id,
                reason=reason,
                before={"enrollment_ids": targets, "status": AUTOPAY_ACTIVE_STATUS},
                after={"enrollment_ids": paused, "status": PAUSED_STATUS},
            )
        )
        result = PauseFamilyAutopayResult(len(paused), len(targets), warnings)
        try:
            await self._idempotency.put(
                idem_key,
                {"plan": plan, "result": {"paused_count": result.paused_count, "active_count_before": result.active_count_before, "warnings": warnings}},
            )
        except DuplicateKeyError:
            pass  # Mongo store is insert-only; the plan key already exists. Replays re-run the (idempotent) writes.
        return result
```

`MongoIdempotencyStore.put` is `insert_one` — a second `put` under the same key raises `DuplicateKeyError`, which the code above tolerates; a replay then re-runs the guarded (no-op) writes and re-appends the audit entry, whose deterministic `audit_id` makes the append a no-op too. The unit test's `FakeIdem` overwrites, which exercises the cached-result branch. Check the Mongo store's `put` and, if it upserts instead, nothing changes.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest v2/tests/unit/test_pause_family_autopay.py -q` → PASS.

- [ ] **Step 5: Lint and commit**

```bash
cd backend && .venv/bin/ruff check v2/contexts/billing/application/use_cases/pause_family_autopay.py v2/tests/unit/test_pause_family_autopay.py && .venv/bin/ruff format v2/contexts/billing/application/use_cases/pause_family_autopay.py v2/tests/unit/test_pause_family_autopay.py
git add backend/v2/contexts/billing/application/use_cases/pause_family_autopay.py backend/v2/tests/unit/test_pause_family_autopay.py
git commit -m "feat(billing): PauseFamilyAutopay use case"
```

---

### Task 5: BFF routes, response models, composition, wiring

**Files:**
- Create: `backend/v2/interfaces/admin/families_views.py`, `backend/v2/interfaces/admin/families_routes.py`, `backend/v2/composition/families.py`
- Modify: `backend/v2/interfaces/admin/router.py` (import + `include_router(families_router)` right after `collections_router`), `backend/v2/main.py` (after `app.state.admin_collections = ...`: `app.state.admin_families = compose_admin_families(db)`; import from `backend.v2.composition.families`)
- Test: `backend/v2/tests/interface/test_admin_families_routes.py`; re-enable the view assertion in `tests/contract/test_family_billing_read_model.py`

**Interfaces:**
- Consumes: Task 3 `MongoFamilyBillingReadModel.build` / `FamilyBillingUnavailable`; Task 4 `PauseFamilyAutopay` / `NothingToPause`; Task 2 `strip_owner_actions`; `require_persona("admin")` from `backend.v2.shared.http`; `current_academy_id` from `backend.v2.shared.tenancy`.
- Produces: `GET /api/v2/admin/families/{parent_id}/billing` → `AdminFamilyBillingView`; `POST /api/v2/admin/families/{parent_id}/autopay/pause` body `PauseFamilyAutopayRequest{reason, request_id}` → `PauseFamilyAutopayResponse{paused_count, active_count_before, warnings}`; dependencies `get_admin_families(request) -> AdminFamiliesServices` with attributes `.reader` and `.pause_autopay`.

- [ ] **Step 1: Write the failing interface tests**

```python
# backend/v2/tests/interface/test_admin_families_routes.py
"""Interface tests for the family billing routes (spec §3, §5, §8)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.billing.application.use_cases.pause_family_autopay import (
    NothingToPause,
    PauseFamilyAutopayResult,
)
from backend.v2.contexts.billing.infrastructure.family_billing_read_model import (
    FamilyBillingUnavailable,
)
from backend.v2.interfaces.admin.families_routes import get_admin_families
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


def _view() -> dict[str, Any]:
    return {
        "generated_at": "2026-09-10T15:00:00+00:00",
        "timezone": "America/Chicago",
        "today": "2026-09-10",
        "parent": {"parent_id": "p-1", "name": "Sahaya", "email": "s@example.com", "phone": None},
        "header": {
            "balance_cents": 6000,
            "open_invoice_count": 1,
            "available_credit_cents": 0,
            "last_payment": None,
            "autopay": {"state": "on", "active_count": 1, "total_count": 1, "card_last4": "4242", "card_label": "Visa",
                        "next_charge_on": "2026-09-08", "next_charge_invoice_id": "inv-1", "last_failure": None},
            "registration": {"state": "registered", "card_on_file": True, "last_invited_at": None},
            "enrollment_counts": {"active": 1, "paused": 0, "cancelled": 0},
        },
        "students": [
            {"student_id": "s-1", "name": "Arjun", "status": "active", "enrollments": [
                {"enrollment_id": "e-1", "session_id": "sess-1", "session_title": "Sat 9:00", "schedule": "Sat 09:00",
                 "status": "active", "monthly_price_cents": 6000, "override_price_cents": None, "autopay_status": "active",
                 "recurring_discount": None, "resume_on": None, "actions": ["recurring_discount"]}
            ]}
        ],
        "invoices": [
            {"invoice_id": "inv-1", "invoice_number": "INV-1", "period": "2026-09", "student_id": "s-1", "student_name": "Arjun",
             "enrollment_id": "e-1", "status": "open", "total_cents": 6000, "paid_cents": 0, "balance_due_cents": 6000,
             "due_date": "2026-09-08", "created_at": "2026-09-01T06:00:00+00:00", "paid_at": None, "voided_at": None,
             "void_reason": None, "settlement_unlinked": False,
             "delivery": {"status": "sent", "last_sent_at": "2026-09-01T06:05:00+00:00", "kind": "autopay_notice"},
             "allocations": [], "credits": [], "chargeable": True,
             "actions": ["send", "record_payment", "charge_card", "void", "discount_once"]}
        ],
        "timeline": [
            {"at": "2026-09-01T06:00:00+00:00", "kind": "money", "code": "invoice_generated", "summary": "Sep 2026 invoice generated · Arjun · $60",
             "invoice_id": "inv-1", "invoice_ids": ["inv-1"], "enrollment_id": None, "student_name": "Arjun", "actor_id": None,
             "reason": None, "amount_cents": 6000, "muted": False}
        ],
        "actions": ["autopay_off", "send_invoice", "record_payment"],
        "warnings": [],
        "internal_marker": True,
    }


class FakeReader:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.result: dict[str, Any] | None = _view()
        self.error: Exception | None = None

    async def build(self, parent_id: str) -> dict[str, Any] | None:
        self.calls.append(parent_id)
        if self.error:
            raise self.error
        return self.result


class FakePause:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None

    async def execute(self, **kwargs: Any) -> PauseFamilyAutopayResult:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return PauseFamilyAutopayResult(paused_count=2, active_count_before=2, warnings=[])


class FakeServices:
    def __init__(self) -> None:
        self.reader = FakeReader()
        self.pause_autopay = FakePause()


def _claims(*roles: str) -> AuthClaims:
    return AuthClaims(user_id="u-1", email="u@example.com", academy_id="acad", roles=tuple(roles))  # type: ignore[arg-type]


def _make_app(roles: tuple[str, ...], services: FakeServices) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(*roles)
    app.dependency_overrides[get_admin_families] = lambda: services
    return app


@pytest.fixture
def services() -> FakeServices:
    return FakeServices()


@pytest.fixture
def admin(services: FakeServices) -> Iterator[TestClient]:
    with TestClient(_make_app(("admin",), services)) as c:
        yield c


@pytest.fixture
def owner(services: FakeServices) -> Iterator[TestClient]:
    with TestClient(_make_app(("admin", "owner"), services)) as c:
        yield c


@pytest.fixture
def coach(services: FakeServices) -> Iterator[TestClient]:
    with TestClient(_make_app(("coach",), services)) as c:
        yield c


def test_owner_gets_every_action(owner: TestClient, services: FakeServices) -> None:
    resp = owner.get("/api/v2/admin/families/p-1/billing")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parent"]["parent_id"] == "p-1"
    assert body["invoices"][0]["actions"] == ["send", "record_payment", "charge_card", "void", "discount_once"]
    assert body["students"][0]["enrollments"][0]["actions"] == ["recurring_discount"]
    assert "internal_marker" not in body
    assert services.reader.calls == ["p-1"]


def test_admin_loses_owner_only_actions(admin: TestClient) -> None:
    body = admin.get("/api/v2/admin/families/p-1/billing").json()
    assert body["invoices"][0]["actions"] == ["send", "record_payment", "charge_card"]
    assert body["students"][0]["enrollments"][0]["actions"] == []
    assert body["actions"] == ["autopay_off", "send_invoice", "record_payment"]


def test_coach_is_404(coach: TestClient, services: FakeServices) -> None:
    assert coach.get("/api/v2/admin/families/p-1/billing").status_code == 404
    assert services.reader.calls == []


def test_unknown_parent_is_404(admin: TestClient, services: FakeServices) -> None:
    services.reader.result = None
    assert admin.get("/api/v2/admin/families/nobody/billing").status_code == 404


def test_primary_source_failure_is_503(admin: TestClient, services: FakeServices) -> None:
    services.reader.error = FamilyBillingUnavailable("invoices down")
    assert admin.get("/api/v2/admin/families/p-1/billing").status_code == 503


def test_pause_autopay_happy_path(admin: TestClient, services: FakeServices) -> None:
    resp = admin.post("/api/v2/admin/families/p-1/autopay/pause", json={"reason": "parent asked", "request_id": "req-1"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"paused_count": 2, "active_count_before": 2, "warnings": []}
    assert services.pause_autopay.calls == [
        {"academy_id": "acad", "parent_id": "p-1", "actor_id": "u-1", "reason": "parent asked", "request_id": "req-1"}
    ]


def test_pause_autopay_requires_reason(admin: TestClient, services: FakeServices) -> None:
    resp = admin.post("/api/v2/admin/families/p-1/autopay/pause", json={"reason": "", "request_id": "req-1"})
    assert resp.status_code == 422
    assert services.pause_autopay.calls == []


def test_pause_autopay_nothing_to_pause_is_400(admin: TestClient, services: FakeServices) -> None:
    services.pause_autopay.error = NothingToPause("no_active_autopay: nothing")
    resp = admin.post("/api/v2/admin/families/p-1/autopay/pause", json={"reason": "x", "request_id": "r"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "no_active_autopay"


def test_pause_autopay_is_404_for_coach(coach: TestClient, services: FakeServices) -> None:
    resp = coach.post("/api/v2/admin/families/p-1/autopay/pause", json={"reason": "x", "request_id": "r"})
    assert resp.status_code == 404
    assert services.pause_autopay.calls == []
```

The `academy_id` passed to the use case comes from `current_academy_id()`; in this TestClient app there is no tenant middleware, so the route must fall back to `claims.academy_id`. Implement `_academy_id(claims)`: try `current_academy_id()`, on `LookupError`/`RuntimeError` return `claims.academy_id`. Check what `current_academy_id()` raises when unset: `sed -n 30,45p backend/v2/shared/tenancy/context.py`.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest v2/tests/interface/test_admin_families_routes.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement views, routes, composition, wiring**

```python
# backend/v2/interfaces/admin/families_views.py
"""Request/response models for ``/admin/families/{parent_id}/…``.

Field names follow spec §3.2 of
``docs/superpowers/specs/2026-09-05-family-billing-design.md``. The read model hands
back plain dicts; these models shape them and drop anything unnamed (``extra="ignore"``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AutopayState = Literal["on", "off", "partial", "needs_consent"]
RegistrationState = Literal["registered", "invited", "not_invited"]
FamilyAction = Literal["send_invite", "autopay_on", "autopay_off", "send_invoice", "record_payment"]
InvoiceAction = Literal["send", "record_payment", "charge_card", "void", "refund", "discount_once"]
EnrollmentAction = Literal["recurring_discount"]
TimelineKind = Literal["money", "admin", "lifecycle", "comms"]


class _View(BaseModel):
    model_config = ConfigDict(extra="ignore")


class FamilyParent(_View):
    parent_id: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None


class FamilyLastPayment(_View):
    amount_cents: int
    method: str | None = None
    paid_at: str | None = None
    invoice_ids: list[str] = []


class FamilyLastFailure(_View):
    code: str | None = None
    at: str | None = None


class FamilyAutopay(_View):
    state: AutopayState
    active_count: int
    total_count: int
    card_last4: str | None = None
    card_label: str | None = None
    next_charge_on: str | None = None
    next_charge_invoice_id: str | None = None
    last_failure: FamilyLastFailure | None = None


class FamilyRegistration(_View):
    state: RegistrationState
    card_on_file: bool
    last_invited_at: str | None = None


class FamilyEnrollmentCounts(_View):
    active: int
    paused: int
    cancelled: int


class FamilyHeader(_View):
    balance_cents: int
    open_invoice_count: int
    available_credit_cents: int
    last_payment: FamilyLastPayment | None = None
    autopay: FamilyAutopay
    registration: FamilyRegistration
    enrollment_counts: FamilyEnrollmentCounts


class FamilyEnrollment(_View):
    enrollment_id: str
    session_id: str | None = None
    session_title: str | None = None
    schedule: str | None = None
    status: str
    monthly_price_cents: int | None = None
    override_price_cents: int | None = None
    autopay_status: str | None = None
    recurring_discount: dict[str, Any] | None = None
    resume_on: str | None = None
    actions: list[EnrollmentAction] = []


class FamilyStudent(_View):
    student_id: str
    name: str
    status: str | None = None
    enrollments: list[FamilyEnrollment] = []


class FamilyDelivery(_View):
    status: str
    last_sent_at: str | None = None
    kind: Literal["invoice", "autopay_notice"]


class FamilyAllocation(_View):
    payment_id: str
    amount_cents: int
    method: str | None = None
    paid_at: str | None = None
    stripe_payment_intent_id: str | None = None


class FamilyCredit(_View):
    credit_id: str
    amount_cents: int


class FamilyInvoice(_View):
    invoice_id: str
    invoice_number: str | None = None
    period: str
    student_id: str | None = None
    student_name: str | None = None
    enrollment_id: str | None = None
    status: str
    total_cents: int
    paid_cents: int
    balance_due_cents: int
    due_date: str | None = None
    created_at: str | None = None
    paid_at: str | None = None
    voided_at: str | None = None
    void_reason: str | None = None
    settlement_unlinked: bool = False
    delivery: FamilyDelivery
    allocations: list[FamilyAllocation] = []
    credits: list[FamilyCredit] = []
    chargeable: bool = False
    actions: list[InvoiceAction] = []


class FamilyTimelineEntry(_View):
    at: str
    kind: TimelineKind
    code: str
    summary: str
    invoice_id: str | None = None
    invoice_ids: list[str] = []
    enrollment_id: str | None = None
    student_name: str | None = None
    actor_id: str | None = None
    reason: str | None = None
    amount_cents: int | None = None
    muted: bool = False


class AdminFamilyBillingView(_View):
    generated_at: str
    timezone: str
    today: str
    parent: FamilyParent
    header: FamilyHeader
    students: list[FamilyStudent] = []
    invoices: list[FamilyInvoice] = []
    timeline: list[FamilyTimelineEntry] = []
    actions: list[FamilyAction] = []
    warnings: list[str] = []


class PauseFamilyAutopayRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    request_id: str = Field(min_length=1, max_length=120)


class PauseFamilyAutopayResponse(BaseModel):
    paused_count: int
    active_count_before: int
    warnings: list[str] = []
```

```python
# backend/v2/interfaces/admin/families_routes.py
"""Admin BFF: the Family billing page.

Spec: ``docs/superpowers/specs/2026-09-05-family-billing-design.md`` §3, §5.

Services are attached at ``app.state.admin_families`` by
``composition/families.py`` (``composition/admin.py`` is at its line budget).
This module only knows their protocols. Owner-only actions are stripped here
for non-owner callers so the page never renders a button the backend refuses;
the write routes themselves keep their own ``require_owner`` guards.
"""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.v2.contexts.billing.application.family_billing import strip_owner_actions
from backend.v2.contexts.billing.application.use_cases.pause_family_autopay import (
    NothingToPause,
    PauseFamilyAutopayResult,
)
from backend.v2.contexts.billing.infrastructure.family_billing_read_model import (
    FamilyBillingUnavailable,
)
from backend.v2.interfaces.admin.families_views import (
    AdminFamilyBillingView,
    PauseFamilyAutopayRequest,
    PauseFamilyAutopayResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.tenancy import current_academy_id


class FamilyBillingReader(Protocol):
    async def build(self, parent_id: str) -> dict[str, Any] | None: ...


class FamilyAutopayPauser(Protocol):
    async def execute(
        self, *, academy_id: str, parent_id: str, actor_id: str, reason: str, request_id: str
    ) -> PauseFamilyAutopayResult: ...


class AdminFamiliesServices(Protocol):
    reader: FamilyBillingReader
    pause_autopay: FamilyAutopayPauser


def get_admin_families(request: Request) -> AdminFamiliesServices:
    services: AdminFamiliesServices = request.app.state.admin_families
    return services


def _academy_id(claims: AuthClaims) -> str:
    try:
        return current_academy_id()
    except (LookupError, RuntimeError):
        return claims.academy_id


router = APIRouter(tags=["admin.families"])


@router.get("/families/{parent_id}/billing", response_model=AdminFamilyBillingView)
async def family_billing(
    parent_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminFamiliesServices = Depends(get_admin_families),
) -> AdminFamilyBillingView:
    """One parent's billing picture: header, students, invoices, timeline, actions."""
    try:
        view = await services.reader.build(parent_id)
    except FamilyBillingUnavailable as exc:
        raise HTTPException(status_code=503, detail="family billing unavailable") from exc
    if view is None:
        raise HTTPException(status_code=404, detail="family not found")
    if "owner" not in claims.roles:
        view = strip_owner_actions(view)
    return AdminFamilyBillingView.model_validate(view)


@router.post("/families/{parent_id}/autopay/pause", response_model=PauseFamilyAutopayResponse)
async def pause_family_autopay(
    parent_id: str,
    body: PauseFamilyAutopayRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminFamiliesServices = Depends(get_admin_families),
) -> PauseFamilyAutopayResponse:
    """Autopay OFF for the whole family: every active enrollment becomes ``paused``."""
    try:
        result = await services.pause_autopay.execute(
            academy_id=_academy_id(claims),
            parent_id=parent_id,
            actor_id=claims.user_id,
            reason=body.reason,
            request_id=body.request_id,
        )
    except NothingToPause as exc:
        raise HTTPException(status_code=400, detail=str(exc).split(":", 1)[0]) from exc
    return PauseFamilyAutopayResponse(
        paused_count=result.paused_count,
        active_count_before=result.active_count_before,
        warnings=list(result.warnings),
    )
```

```python
# backend/v2/composition/families.py
"""Composition for the admin Family billing page (``/admin/families/{parent_id}/…``).

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget. Pure wiring: every repository resolves the tenant from
``current_academy_id()`` at request time, so nothing tenant-specific is
captured here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.contexts.billing.application.use_cases.pause_family_autopay import (
    PauseFamilyAutopay,
)
from backend.v2.contexts.billing.infrastructure.family_billing_read_model import (
    MongoFamilyBillingReadModel,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_student_billing_enrollment_repo import (
    MongoStudentBillingEnrollmentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup


@dataclass(frozen=True)
class AdminFamilies:
    reader: MongoFamilyBillingReadModel
    pause_autopay: PauseFamilyAutopay


def compose_admin_families(db: Any) -> AdminFamilies:
    audit = MongoBillingAuditLogRepository(db)
    reader = MongoFamilyBillingReadModel(
        db,
        academy_timezone=academy_timezone_lookup(db),
        connected_accounts=MongoConnectedAccountRepository(db),
        billing_settings=MongoBillingSettingsRepository(db),
        customers=MongoParentBillingCustomerRepository(db),
        credits=MongoCreditLedgerRepository(db),
        users=MongoUserRepository(db),
        audit=audit,
    )
    pause = PauseFamilyAutopay(
        enrollments=MongoStudentBillingEnrollmentRepository(db),
        audit=audit,
        idempotency=MongoIdempotencyStore(db),
    )
    return AdminFamilies(reader=reader, pause_autopay=pause)
```

Check each repository's constructor (`grep -n "def __init__" -A2` on `mongo_student_billing_enrollment_repo.py`, `mongo_credit_ledger_repo.py`, `mongo_connected_account_repo.py`) and pass what they need — the collections composition shows the first three take `db` only.

Router: in `interfaces/admin/router.py` add `from .families_routes import router as families_router` and `router.include_router(families_router)` after the collections line. Main: add the import and `app.state.admin_families = compose_admin_families(db)` after `admin_collections`.

Re-enable the `AdminFamilyBillingView` import/assertion in the contract test.

- [ ] **Step 4: Run interface + contract + structural tests**

Run: `.venv/bin/python -m pytest v2/tests/interface/test_admin_families_routes.py v2/tests/contract/test_family_billing_read_model.py v2/tests/structural v2/tests/unit/test_audit_inventory_manifest.py -q`
Expected: interface + contract PASS; structural owner-gate PASS (pause route is admin, not owner). The manifest test still passes because no frontend route exists yet.

- [ ] **Step 5: Boundaries, lint, commit**

Run from `backend/`: `PYTHONPATH=.. .venv/bin/lint-imports --config pyproject.toml` → all contracts kept.

```bash
cd backend && .venv/bin/ruff check v2 && .venv/bin/ruff format v2
git add backend/v2/interfaces/admin/families_views.py backend/v2/interfaces/admin/families_routes.py backend/v2/composition/families.py backend/v2/interfaces/admin/router.py backend/v2/main.py backend/v2/tests/interface/test_admin_families_routes.py backend/v2/tests/contract/test_family_billing_read_model.py
git commit -m "feat(admin): family billing endpoint and autopay pause route"
```

---

### Task 6: Frontend API client, query keys, view helpers

**Files:**
- Create: `frontend/lib/api/admin-families.ts`
- Create: `frontend/app/(admin)/admin/families/[parentId]/family-view.ts`, `family-view.test.ts`
- Modify: `frontend/lib/query/keys.ts` (inside `admin`): `families: () => ["admin", "families"] as const, familyBilling: (parentId: string) => ["admin", "families", parentId, "billing"] as const,`

**Interfaces:**
- Produces: types `AdminFamilyBillingView`, `FamilyInvoice`, `FamilyEnrollment`, `FamilyTimelineEntry`, `FamilyAction`, `InvoiceAction`; `fetchAdminFamilyBilling(parentId)`, `pauseFamilyAutopay(parentId, {reason, request_id})`; helpers `autopayToggle(header.autopay)`, `invoiceActionLabel(action)`, `registrationChip(state)`, `timelineTone(entry)`, `mintRequestId()`.

- [ ] **Step 1: Write the failing vitest**

```ts
// frontend/app/(admin)/admin/families/[parentId]/family-view.test.ts
import { describe, expect, it } from "vitest";

import {
  autopayToggle,
  invoiceActionLabel,
  registrationChip,
  timelineTone,
} from "./family-view";

describe("autopayToggle", () => {
  const base = { active_count: 1, total_count: 2, card_last4: "4242", card_label: "Visa", next_charge_on: "2026-09-08", next_charge_invoice_id: "inv-1", last_failure: null };
  it("on: checked, enabled, shows card and next charge", () => {
    expect(autopayToggle({ ...base, state: "on" })).toEqual({
      checked: true,
      disabled: false,
      label: "On",
      hint: "Visa ••4242 · next charge Sep 8",
    });
  });
  it("partial: checked with a count", () => {
    expect(autopayToggle({ ...base, state: "partial" }).label).toBe("On for 1 of 2");
  });
  it("off: unchecked, enabled", () => {
    expect(autopayToggle({ ...base, state: "off", next_charge_on: null })).toMatchObject({ checked: false, disabled: false, label: "Off" });
  });
  it("needs_consent: disabled with the invite hint", () => {
    expect(autopayToggle({ ...base, state: "needs_consent", card_last4: null, card_label: null, next_charge_on: null })).toEqual({
      checked: false,
      disabled: true,
      label: "Off",
      hint: "Needs parent consent — send invite",
    });
  });
});

describe("labels and chips", () => {
  it("maps invoice actions", () => {
    expect(invoiceActionLabel("charge_card")).toBe("Charge card now");
    expect(invoiceActionLabel("discount_once")).toBe("One-time discount");
  });
  it("maps registration states", () => {
    expect(registrationChip("registered")).toEqual({ label: "Card on file", variant: "success" });
    expect(registrationChip("invited")).toEqual({ label: "Invited", variant: "warning" });
    expect(registrationChip("not_invited")).toEqual({ label: "Not invited", variant: "neutral" });
  });
  it("mutes comms rows", () => {
    expect(timelineTone({ kind: "comms", muted: true })).toBe("muted");
    expect(timelineTone({ kind: "money", muted: false })).toBe("money");
  });
});
```

- [ ] **Step 2: Run** `cd frontend && pnpm exec vitest run "app/(admin)/admin/families"` → fails (module missing).

- [ ] **Step 3: Implement**

```ts
// frontend/lib/api/admin-families.ts
/**
 * Admin Family billing page — `GET /admin/families/{parentId}/billing` and
 * `POST /admin/families/{parentId}/autopay/pause`.
 * Spec: docs/superpowers/specs/2026-09-05-family-billing-design.md §3.2, §5.
 * Kept out of `admin.ts` so the family types stay in one file.
 */
import { apiFetch } from "./client";

export type AutopayState = "on" | "off" | "partial" | "needs_consent";
export type RegistrationState = "registered" | "invited" | "not_invited";
export type FamilyAction = "send_invite" | "autopay_on" | "autopay_off" | "send_invoice" | "record_payment";
export type InvoiceAction = "send" | "record_payment" | "charge_card" | "void" | "refund" | "discount_once";
export type TimelineKind = "money" | "admin" | "lifecycle" | "comms";

export interface FamilyAutopay {
  state: AutopayState;
  active_count: number;
  total_count: number;
  card_last4: string | null;
  card_label: string | null;
  next_charge_on: string | null;
  next_charge_invoice_id: string | null;
  last_failure: { code: string | null; at: string | null } | null;
}

export interface FamilyHeader {
  balance_cents: number;
  open_invoice_count: number;
  available_credit_cents: number;
  last_payment: { amount_cents: number; method: string | null; paid_at: string | null; invoice_ids: string[] } | null;
  autopay: FamilyAutopay;
  registration: { state: RegistrationState; card_on_file: boolean; last_invited_at: string | null };
  enrollment_counts: { active: number; paused: number; cancelled: number };
}

export interface FamilyEnrollment {
  enrollment_id: string;
  session_id: string | null;
  session_title: string | null;
  schedule: string | null;
  status: string;
  monthly_price_cents: number | null;
  override_price_cents: number | null;
  autopay_status: string | null;
  recurring_discount: Record<string, unknown> | null;
  resume_on: string | null;
  actions: "recurring_discount"[];
}

export interface FamilyStudent {
  student_id: string;
  name: string;
  status: string | null;
  enrollments: FamilyEnrollment[];
}

export interface FamilyInvoice {
  invoice_id: string;
  invoice_number: string | null;
  period: string;
  student_id: string | null;
  student_name: string | null;
  enrollment_id: string | null;
  status: string;
  total_cents: number;
  paid_cents: number;
  balance_due_cents: number;
  due_date: string | null;
  created_at: string | null;
  paid_at: string | null;
  voided_at: string | null;
  void_reason: string | null;
  settlement_unlinked: boolean;
  delivery: { status: string; last_sent_at: string | null; kind: "invoice" | "autopay_notice" };
  allocations: { payment_id: string; amount_cents: number; method: string | null; paid_at: string | null; stripe_payment_intent_id: string | null }[];
  credits: { credit_id: string; amount_cents: number }[];
  chargeable: boolean;
  actions: InvoiceAction[];
}

export interface FamilyTimelineEntry {
  at: string;
  kind: TimelineKind;
  code: string;
  summary: string;
  invoice_id: string | null;
  invoice_ids: string[];
  enrollment_id: string | null;
  student_name: string | null;
  actor_id: string | null;
  reason: string | null;
  amount_cents: number | null;
  muted: boolean;
}

export interface AdminFamilyBillingView {
  generated_at: string;
  timezone: string;
  today: string;
  parent: { parent_id: string; name: string | null; email: string | null; phone: string | null };
  header: FamilyHeader;
  students: FamilyStudent[];
  invoices: FamilyInvoice[];
  timeline: FamilyTimelineEntry[];
  actions: FamilyAction[];
  warnings: string[];
}

export function fetchAdminFamilyBilling(parentId: string): Promise<AdminFamilyBillingView> {
  return apiFetch<AdminFamilyBillingView>(`/admin/families/${encodeURIComponent(parentId)}/billing`);
}

export interface PauseFamilyAutopayResponse {
  paused_count: number;
  active_count_before: number;
  warnings: string[];
}

export function pauseFamilyAutopay(
  parentId: string,
  payload: { reason: string; request_id: string },
): Promise<PauseFamilyAutopayResponse> {
  return apiFetch<PauseFamilyAutopayResponse>(`/admin/families/${encodeURIComponent(parentId)}/autopay/pause`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
```

```ts
// frontend/app/(admin)/admin/families/[parentId]/family-view.ts
/** Pure view helpers for the Family billing page; no React, no fetch. */
import type { FamilyAutopay, InvoiceAction, RegistrationState, TimelineKind } from "@/lib/api/admin-families";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-09-08" → "Sep 8" without a timezone shift (dates are academy-local already). */
export function shortDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return null;
  return `${MONTHS[m - 1]} ${d}`;
}

export function periodLabel(period: string): string {
  const [y, m] = period.split("-").map(Number);
  return y && m ? `${MONTHS[m - 1]} ${y}` : period;
}

export interface ToggleProps {
  checked: boolean;
  disabled: boolean;
  label: string;
  hint: string;
}

export function autopayToggle(a: FamilyAutopay): ToggleProps {
  const card = a.card_last4 ? `${a.card_label ?? "Card"} ••${a.card_last4}` : "no card on file";
  const next = a.next_charge_on ? ` · next charge ${shortDate(a.next_charge_on)}` : "";
  switch (a.state) {
    case "on":
      return { checked: true, disabled: false, label: "On", hint: `${card}${next}` };
    case "partial":
      return { checked: true, disabled: false, label: `On for ${a.active_count} of ${a.total_count}`, hint: `${card}${next}` };
    case "off":
      return { checked: false, disabled: false, label: "Off", hint: card };
    case "needs_consent":
    default:
      return { checked: false, disabled: true, label: "Off", hint: "Needs parent consent — send invite" };
  }
}

const INVOICE_ACTION_LABELS: Record<InvoiceAction, string> = {
  send: "Send invoice",
  record_payment: "Record payment",
  charge_card: "Charge card now",
  void: "Void invoice",
  refund: "Refund",
  discount_once: "One-time discount",
};

export function invoiceActionLabel(action: InvoiceAction): string {
  return INVOICE_ACTION_LABELS[action];
}

export function registrationChip(state: RegistrationState): { label: string; variant: "success" | "warning" | "neutral" } {
  if (state === "registered") return { label: "Card on file", variant: "success" };
  if (state === "invited") return { label: "Invited", variant: "warning" };
  return { label: "Not invited", variant: "neutral" };
}

export function timelineTone(entry: { kind: TimelineKind; muted: boolean }): "muted" | TimelineKind {
  return entry.muted ? "muted" : entry.kind;
}

export function mintRequestId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `req-${Date.now()}`;
}
```

Check the `Chip` component's variant names (`grep -n "variant" frontend/components/ds/chip.tsx`) and use its real names in `registrationChip` and the test if they differ from `success | warning | neutral`.

- [ ] **Step 4: Run** `pnpm exec vitest run "app/(admin)/admin/families"` → PASS; `pnpm exec tsc --noEmit` → clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/api/admin-families.ts frontend/lib/query/keys.ts "frontend/app/(admin)/admin/families/[parentId]/family-view.ts" "frontend/app/(admin)/admin/families/[parentId]/family-view.test.ts"
git commit -m "feat(admin): family billing API client and view helpers"
```

---

### Task 7: The Family billing page

**Files:**
- Create: `frontend/app/(admin)/admin/families/[parentId]/page.tsx`, `FamilyHeader.tsx`, `StudentsPanel.tsx`, `InvoicesPanel.tsx`, `TimelinePanel.tsx`, `FixSomethingPanel.tsx`, `family-dialogs.tsx`
- Modify: `frontend/components/admin/screen-meta.ts` — add `"/admin/families/[parentId]": { title: "Family billing", subtitle: "Balance, autopay, invoices and what the system did", breadcrumbs: ["Admin", "Money", "Families", "Family"] }` next to the other Money entries (check how dynamic segments are keyed there: `grep -n "\[studentId\]\|\[id\]" screen-meta.ts` and copy that convention).

**Interfaces:**
- Consumes: Task 6 client/helpers; `RecordPaymentDialog` from `../../payments/buckets/RecordPaymentDialog` (props `open, invoices: {invoice_id,label,balance_due_cents}[], initialInvoiceId?, onClose, onSaved`); `formatCents` from `@/lib/money`; `invoiceStatusChip` from `@/lib/billing-status`; `useIsOwner` from `@/components/admin/owner-context`; DS `Card, Overline, Button, Chip, Skeleton, EmptyState, RallyModal, DialogActions, DialogError, Field`; API `voidAdminInvoice, refundAdminInvoice, applyAdminInvoiceAdjustment, sendAdminInvoice, chargeAdminInvoiceAutopay, inviteBillingSetupParent, enableBillingSetupAutopay` from `@/lib/api/admin`; `queryKeys.admin.familyBilling`, `queryKeys.admin.collectionsAll`.
- Produces: `data-testid`s used by Task 9: `admin-family-billing`, `family-balance`, `family-autopay-toggle`, `family-autopay-hint`, `family-last-payment`, `family-registration-chip`, `family-send-invite`, `family-students`, `enrollment-row-{id}`, `family-invoices`, `invoice-row-{id}`, `invoice-expand-{id}`, `invoice-allocations-{id}`, `invoice-action-{action}-{id}`, `family-timeline`, `timeline-entry-{code}`, `family-fix`, `fix-{action}`, `reason-dialog`, `reason-input`, `family-warnings`, `family-error`, `family-retry`.

- [ ] **Step 1: `family-dialogs.tsx` — one reason dialog for every correction**

```tsx
"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";

import { DialogActions, DialogError, Field, RallyModal } from "@/components/ds";
import { formatCents, parseDollarsToCents } from "@/lib/money";

export type ReasonDialogKind =
  | "void"
  | "refund"
  | "discount_once"
  | "charge_card"
  | "autopay_off"
  | "send_invoice";

const COPY: Record<ReasonDialogKind, { overline: string; title: string; description: string; submit: string }> = {
  void: { overline: "Fix something", title: "Void invoice", description: "The invoice is cancelled and nothing is owed on it. Only unpaid invoices can be voided.", submit: "Void invoice" },
  refund: { overline: "Fix something", title: "Refund", description: "Money goes back to the card that paid through Stripe.", submit: "Issue refund" },
  discount_once: { overline: "Fix something", title: "One-time discount", description: "Reduces this invoice only. Use a recurring discount for every month.", submit: "Apply discount" },
  charge_card: { overline: "Fix something", title: "Charge card now", description: "Charges the card on file for this invoice's balance right away.", submit: "Charge card" },
  autopay_off: { overline: "Autopay", title: "Turn autopay off", description: "Every class stops being charged automatically. Open invoices stay open and move to the manual list.", submit: "Turn off" },
  send_invoice: { overline: "Invoice", title: "Send invoice", description: "Emails the invoice to the parent.", submit: "Send" },
};

export interface ReasonDialogResult {
  reason: string;
  amount_cents?: number;
  description?: string;
}

export function ReasonDialog({
  kind,
  open,
  subject,
  maxAmountCents,
  onClose,
  onSubmit,
}: {
  kind: ReasonDialogKind;
  open: boolean;
  /** "Sep 2026 · Arjun · $60" — names what the action hits. */
  subject: string;
  /** Refund and discount cap; null for actions without an amount. */
  maxAmountCents: number | null;
  onClose: () => void;
  onSubmit: (result: ReasonDialogResult) => Promise<unknown>;
}) {
  const [reason, setReason] = useState("");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const wantsAmount = kind === "refund" || kind === "discount_once";
  const wantsDescription = kind === "discount_once";
  const copy = COPY[kind];

  useEffect(() => {
    if (open) {
      setReason("");
      setAmount(maxAmountCents != null ? (maxAmountCents / 100).toFixed(2) : "");
      setDescription(kind === "discount_once" ? "Discount" : "");
    }
  }, [open, kind, maxAmountCents]);

  const amountCents = wantsAmount ? parseDollarsToCents(amount) : undefined;
  const amountInvalid =
    wantsAmount && (amountCents == null || amountCents <= 0 || (maxAmountCents != null && amountCents > maxAmountCents));
  const mutation = useMutation({
    mutationFn: () => onSubmit({ reason: reason.trim(), amount_cents: amountCents, description: description.trim() || undefined }),
    onSuccess: onClose,
  });
  const disabled = reason.trim().length === 0 || amountInvalid || mutation.isPending;

  return (
    <RallyModal open={open} onOpenChange={(v) => !v && onClose()} title={copy.title} description={copy.description} overline={copy.overline}>
      <form
        data-testid="reason-dialog"
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (!disabled) mutation.mutate();
        }}
      >
        <p className="text-sm text-rally-ink" data-testid="reason-subject">{subject}</p>
        {wantsAmount && (
          <Field label={`Amount${maxAmountCents != null ? ` (up to ${formatCents(maxAmountCents)})` : ""}`} required>
            <input data-testid="amount-input" inputMode="decimal" className="w-full rounded-lg border border-rally-line px-3 py-2 text-sm" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </Field>
        )}
        {wantsDescription && (
          <Field label="Line description" required>
            <input data-testid="description-input" className="w-full rounded-lg border border-rally-line px-3 py-2 text-sm" value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
        )}
        <Field label="Reason" required>
          <textarea data-testid="reason-input" rows={2} className="w-full rounded-lg border border-rally-line px-3 py-2 text-sm" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why — this is written to the timeline" />
        </Field>
        {mutation.isError && <DialogError message={(mutation.error as Error).message} />}
        <DialogActions onCancel={onClose} submitLabel={mutation.isPending ? "Working…" : copy.submit}>
          <span />
        </DialogActions>
        <button type="submit" hidden disabled={disabled} aria-hidden="true" />
      </form>
    </RallyModal>
  );
}

export function DisabledFixItem({ label, hint }: { label: string; hint: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-dashed border-rally-line px-3 py-2 text-sm text-rally-muted">
      <span>{label}</span>
      <span className="text-xs">{hint}</span>
    </div>
  );
}

export function useReasonDialog() {
  const [state, setState] = useState<{ kind: ReasonDialogKind; invoiceId: string | null } | null>(null);
  return { state, open: (kind: ReasonDialogKind, invoiceId: string | null = null) => setState({ kind, invoiceId }), close: () => setState(null) };
}

export type { ReactNode };
```

Read `components/ds/dialog-chrome.tsx` first: `DialogActions` renders its own submit button (check whether it takes `disabled`/`submitting` props — lines 59–80). If it does, pass `disabled={disabled}` and drop the hidden button; if it renders `children` as the submit control, render `<Button type="submit" disabled={disabled}>{copy.submit}</Button>` as the child instead of `<span />`. The test in Task 9 clicks the button by its `copy.submit` label.

- [ ] **Step 2: `FamilyHeader.tsx`**

```tsx
"use client";

import Link from "next/link";

import { Button, Card, Chip, Overline } from "@/components/ds";
import type { AdminFamilyBillingView } from "@/lib/api/admin-families";
import { formatCents, formatInstantDay } from "@/lib/money";

import { autopayToggle, registrationChip } from "./family-view";

export function FamilyHeader({
  view,
  busy,
  onToggleAutopay,
  onSendInvite,
  onSendInvoice,
  onRecordPayment,
}: {
  view: AdminFamilyBillingView;
  busy: boolean;
  onToggleAutopay: (turnOn: boolean) => void;
  onSendInvite: () => void;
  onSendInvoice: () => void;
  onRecordPayment: () => void;
}) {
  const { parent, header, actions } = view;
  const toggle = autopayToggle(header.autopay);
  const reg = registrationChip(header.registration.state);
  const studentCount = view.students.length;
  return (
    <Card p={20}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-xl font-semibold text-rally-ink">{parent.name ?? "Parent"}</h1>
          <p className="text-sm text-rally-muted">
            {parent.email ?? "no email"} · {studentCount} {studentCount === 1 ? "student" : "students"}
            {parent.phone ? ` · ${parent.phone}` : ""}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span data-testid="family-registration-chip"><Chip variant={reg.variant} label={reg.label} /></span>
            {actions.includes("send_invite") && (
              <Button size="sm" variant="secondary" data-testid="family-send-invite" onClick={onSendInvite} disabled={busy}>
                {header.registration.last_invited_at ? "Resend invite" : "Send invite"}
              </Button>
            )}
            <Link href={`/admin/messages?dm=${encodeURIComponent(parent.parent_id)}`} className="text-sm text-rally-cobalt-700 hover:underline">Message</Link>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {actions.includes("send_invoice") && <Button size="sm" variant="secondary" data-testid="family-send-invoice" onClick={onSendInvoice} disabled={busy}>Send invoice</Button>}
          {actions.includes("record_payment") && <Button size="sm" variant="primary" data-testid="family-record-payment" onClick={onRecordPayment} disabled={busy}>Record payment</Button>}
        </div>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile overline="Balance" testId="family-balance" big={formatCents(header.balance_cents)} sub={`${header.open_invoice_count} open ${header.open_invoice_count === 1 ? "invoice" : "invoices"}${header.available_credit_cents > 0 ? ` · ${formatCents(header.available_credit_cents)} credit` : ""}`} />
        <div className="rounded-xl border border-rally-line p-3">
          <Overline>Autopay</Overline>
          <label className="mt-1 flex items-center gap-3">
            <input
              type="checkbox"
              role="switch"
              data-testid="family-autopay-toggle"
              aria-label="Autopay"
              aria-checked={toggle.checked}
              checked={toggle.checked}
              disabled={toggle.disabled || busy}
              onChange={(e) => onToggleAutopay(e.target.checked)}
              className="size-5 accent-rally-cobalt-600"
            />
            <span className="font-display text-lg font-semibold text-rally-ink">{toggle.label}</span>
          </label>
          <p className="mt-1 text-xs text-rally-muted" data-testid="family-autopay-hint">{toggle.hint}</p>
          {header.autopay.last_failure?.code && <p className="mt-1 text-xs text-rally-danger">Last failure: {header.autopay.last_failure.code}</p>}
        </div>
        <Tile overline="Last payment" testId="family-last-payment" big={header.last_payment ? formatCents(header.last_payment.amount_cents) : "—"} sub={header.last_payment ? `${formatInstantDay(header.last_payment.paid_at)} · ${header.last_payment.method ?? "payment"}` : "No payments yet"} />
        <Tile overline="Enrollments" testId="family-enrollments" big={String(header.enrollment_counts.active + header.enrollment_counts.paused)} sub={`${header.enrollment_counts.active} active · ${header.enrollment_counts.paused} paused`} />
      </div>
    </Card>
  );
}

function Tile({ overline, big, sub, testId }: { overline: string; big: string; sub: string; testId: string }) {
  return (
    <div className="rounded-xl border border-rally-line p-3" data-testid={testId}>
      <Overline>{overline}</Overline>
      <div className="mt-1 font-display text-lg font-semibold text-rally-ink">{big}</div>
      <p className="text-xs text-rally-muted">{sub}</p>
    </div>
  );
}
```

Check `formatInstantDay` handles null (it takes `string | null | undefined`). Replace `text-rally-danger` with whatever danger token the Tailwind config defines (`grep -n "danger\|coral\|red" frontend/tailwind.config.*`).

- [ ] **Step 3: `StudentsPanel.tsx`**

```tsx
"use client";

import Link from "next/link";

import { Card, Chip, Overline } from "@/components/ds";
import type { FamilyStudent } from "@/lib/api/admin-families";
import { formatCents } from "@/lib/money";

import { shortDate } from "./family-view";

const STATUS_CHIP: Record<string, { variant: "enrolled" | "paused" | "expired" | "pending"; label: string }> = {
  active: { variant: "enrolled", label: "Active" },
  paused: { variant: "paused", label: "Paused" },
  cancelled: { variant: "expired", label: "Cancelled" },
  withdrawn: { variant: "expired", label: "Withdrawn" },
};

export function StudentsPanel({ students, isOwner }: { students: FamilyStudent[]; isOwner: boolean }) {
  return (
    <Card p={20} data-testid="family-students">
      <Overline>Students and classes</Overline>
      {students.length === 0 ? (
        <p className="mt-2 text-sm text-rally-muted">No students on this family yet.</p>
      ) : (
        <ul className="mt-2 divide-y divide-rally-line">
          {students.flatMap((s) =>
            s.enrollments.length === 0
              ? [
                  <li key={s.student_id} className="flex items-center justify-between py-2 text-sm">
                    <Link href={`/admin/students/${encodeURIComponent(s.student_id)}`} className="font-semibold text-rally-ink hover:underline">{s.name}</Link>
                    <span className="text-rally-muted">no classes</span>
                  </li>,
                ]
              : s.enrollments.map((e) => {
                  const chip = STATUS_CHIP[e.status] ?? { variant: "pending" as const, label: e.status };
                  const price = e.override_price_cents ?? e.monthly_price_cents;
                  return (
                    <li key={e.enrollment_id} data-testid={`enrollment-row-${e.enrollment_id}`} className="grid gap-1 py-2 text-sm md:grid-cols-[minmax(0,1fr)_auto_auto_auto] md:items-center md:gap-4">
                      <div className="min-w-0">
                        <Link href={`/admin/students/${encodeURIComponent(s.student_id)}`} className="font-semibold text-rally-ink hover:underline">{s.name}</Link>
                        <span className="text-rally-muted"> · {e.session_title ?? "Class"}{e.schedule ? ` · ${e.schedule}` : ""}</span>
                        {e.status === "paused" && e.resume_on && <span className="text-rally-muted"> · resumes {shortDate(e.resume_on)}</span>}
                      </div>
                      <Chip variant={chip.variant} label={chip.label} />
                      <span className="text-rally-ink">
                        {price != null ? `${formatCents(price)}/mo` : "—"}
                        {e.override_price_cents != null && <span className="text-xs text-rally-muted"> (override)</span>}
                        {e.recurring_discount && <span className="text-xs text-rally-muted"> · discount</span>}
                      </span>
                      <span className="flex items-center gap-2 text-xs text-rally-muted">
                        {e.autopay_status === "active" ? <Chip variant="autopayOn" label="Autopay" /> : <Chip variant="manual" label={e.autopay_status === "paused" ? "Autopay off" : "Manual"} />}
                        {isOwner && e.actions.includes("recurring_discount") && (
                          <Link href={`/admin/students/${encodeURIComponent(s.student_id)}`} className="text-rally-cobalt-700 hover:underline" data-testid={`enrollment-discount-${e.enrollment_id}`}>Recurring discount</Link>
                        )}
                      </span>
                    </li>
                  );
                }),
          )}
        </ul>
      )}
    </Card>
  );
}
```

Recurring discount stays where its dialog already lives (the student page's Sessions tab, `SessionsPanel.tsx`); the class row links there. No new dialog.

- [ ] **Step 4: `InvoicesPanel.tsx`**

```tsx
"use client";

import { useState } from "react";

import { Button, Card, Chip, Overline } from "@/components/ds";
import type { FamilyInvoice, InvoiceAction } from "@/lib/api/admin-families";
import { invoiceStatusChip } from "@/lib/billing-status";
import { formatCents, formatInstantDay } from "@/lib/money";

import { invoiceActionLabel, periodLabel, shortDate } from "./family-view";

export function InvoicesPanel({
  invoices,
  busy,
  onAction,
  onFullAudit,
}: {
  invoices: FamilyInvoice[];
  busy: boolean;
  onAction: (action: InvoiceAction, invoice: FamilyInvoice) => void;
  onFullAudit: (invoice: FamilyInvoice) => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <Card p={20} data-testid="family-invoices">
      <Overline>Invoices</Overline>
      {invoices.length === 0 ? (
        <p className="mt-2 text-sm text-rally-muted">No invoices yet.</p>
      ) : (
        <ul className="mt-2 divide-y divide-rally-line">
          {invoices.map((inv) => {
            const chip = invoiceStatusChip(inv.status);
            const expanded = openId === inv.invoice_id;
            const delivery = inv.delivery.last_sent_at
              ? `${inv.delivery.kind === "autopay_notice" ? "notice" : "invoice"} emailed ${shortDate(inv.delivery.last_sent_at)}`
              : inv.status === "void" ? (inv.void_reason ?? "voided") : "not sent";
            return (
              <li key={inv.invoice_id} data-testid={`invoice-row-${inv.invoice_id}`} className="py-2 text-sm">
                <div className="grid gap-1 md:grid-cols-[minmax(0,1fr)_auto_auto_minmax(0,1fr)] md:items-center md:gap-4">
                  <button type="button" data-testid={`invoice-expand-${inv.invoice_id}`} onClick={() => setOpenId(expanded ? null : inv.invoice_id)} className="text-left font-semibold text-rally-ink hover:underline">
                    {expanded ? "▾" : "▸"} {periodLabel(inv.period)}{inv.student_name ? ` · ${inv.student_name}` : ""}
                    <span className="ml-1 text-xs font-normal text-rally-muted">{inv.invoice_number ?? ""}</span>
                  </button>
                  <span className="text-rally-ink">
                    {formatCents(inv.total_cents)}
                    {inv.paid_cents > 0 && inv.status !== "paid" && <span className="text-xs text-rally-muted"> · {formatCents(inv.paid_cents)} paid</span>}
                    {inv.balance_due_cents > 0 && <span className="text-xs text-rally-muted"> · {formatCents(inv.balance_due_cents)} due</span>}
                  </span>
                  <span className="flex items-center gap-2"><Chip variant={chip.variant} label={chip.label} />{inv.due_date && inv.balance_due_cents > 0 && <span className="text-xs text-rally-muted">due {shortDate(inv.due_date)}</span>}</span>
                  <span className="flex flex-wrap items-center justify-end gap-1">
                    <span className="mr-2 text-xs text-rally-muted">{delivery}</span>
                    {inv.actions.map((a) => (
                      <Button key={a} size="sm" variant={a === "void" || a === "refund" ? "danger" : "secondary"} data-testid={`invoice-action-${a}-${inv.invoice_id}`} onClick={() => onAction(a, inv)} disabled={busy}>
                        {invoiceActionLabel(a)}
                      </Button>
                    ))}
                  </span>
                </div>
                {expanded && (
                  <div className="mt-2 rounded-lg bg-rally-paper px-3 py-2 text-xs" data-testid={`invoice-allocations-${inv.invoice_id}`}>
                    {inv.settlement_unlinked && <p className="text-rally-muted">paid (no payment record)</p>}
                    {inv.allocations.map((a) => (
                      <p key={`${a.payment_id}-${a.amount_cents}`}>↳ {formatCents(a.amount_cents)} · {a.method ?? "payment"} · {formatInstantDay(a.paid_at)}{a.stripe_payment_intent_id ? ` · ${a.stripe_payment_intent_id}` : ""}</p>
                    ))}
                    {inv.credits.map((c) => <p key={c.credit_id}>↳ credit {formatCents(c.amount_cents)}</p>)}
                    {inv.allocations.length === 0 && inv.credits.length === 0 && !inv.settlement_unlinked && <p className="text-rally-muted">No payments applied.</p>}
                    <button type="button" className="mt-1 text-rally-cobalt-700 hover:underline" data-testid={`invoice-audit-${inv.invoice_id}`} onClick={() => onFullAudit(inv)}>Full audit</button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
```

Check `ButtonVariant` for a danger/destructive name (`sed -n 5,12p components/ds/button.tsx`) and use it; fall back to `"secondary"`.

- [ ] **Step 5: `TimelinePanel.tsx` and `FixSomethingPanel.tsx`**

```tsx
// TimelinePanel.tsx
"use client";

import { useState } from "react";

import { Button, Card, Overline } from "@/components/ds";
import type { FamilyTimelineEntry } from "@/lib/api/admin-families";
import { formatInstantDay } from "@/lib/money";

import { timelineTone } from "./family-view";

const PAGE = 50;

export function TimelinePanel({ timeline, warnings }: { timeline: FamilyTimelineEntry[]; warnings: string[] }) {
  const [shown, setShown] = useState(PAGE);
  return (
    <Card p={20} data-testid="family-timeline">
      <Overline>Timeline</Overline>
      {warnings.length > 0 && <p className="mt-1 text-xs text-rally-muted" data-testid="family-warnings">Some history is unavailable right now ({warnings.join(", ")}).</p>}
      {timeline.length === 0 ? (
        <p className="mt-2 text-sm text-rally-muted">No activity yet.</p>
      ) : (
        <ol className="mt-2 space-y-1 border-l-2 border-rally-line pl-3">
          {timeline.slice(0, shown).map((e, i) => {
            const tone = timelineTone(e);
            return (
              <li key={`${e.code}-${e.at}-${i}`} data-testid={`timeline-entry-${e.code}`} data-tone={tone} className={`text-sm ${tone === "muted" ? "text-rally-muted" : "text-rally-ink"}`}>
                <span className="mr-2 font-mono text-xs text-rally-muted">{formatInstantDay(e.at)}</span>
                <span className={tone === "money" || tone === "admin" ? "font-semibold" : ""}>{e.summary}</span>
              </li>
            );
          })}
        </ol>
      )}
      {timeline.length > shown && <Button size="sm" variant="secondary" className="mt-3" onClick={() => setShown((n) => n + PAGE)}>Show older</Button>}
    </Card>
  );
}
```

```tsx
// FixSomethingPanel.tsx
"use client";

import { Button, Card, Overline } from "@/components/ds";
import type { FamilyInvoice } from "@/lib/api/admin-families";

import { DisabledFixItem, type ReasonDialogKind } from "./family-dialogs";

const ITEMS: { kind: ReasonDialogKind; label: string; ownerOnly: boolean }[] = [
  { kind: "void", label: "Void invoice", ownerOnly: true },
  { kind: "refund", label: "Refund", ownerOnly: true },
  { kind: "discount_once", label: "One-time discount", ownerOnly: true },
  { kind: "charge_card", label: "Charge card now", ownerOnly: false },
];

export function FixSomethingPanel({ invoices, isOwner, onPick }: { invoices: FamilyInvoice[]; isOwner: boolean; onPick: (kind: ReasonDialogKind, invoiceId: string) => void }) {
  return (
    <Card p={20} data-testid="family-fix">
      <Overline>Fix something</Overline>
      <p className="mt-1 text-xs text-rally-muted">Every action asks for a reason and lands in the timeline.</p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {ITEMS.filter((it) => isOwner || !it.ownerOnly).map((it) => {
          const targets = invoices.filter((inv) => inv.actions.includes(it.kind as never));
          return (
            <div key={it.kind} className="rounded-lg border border-rally-line p-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-rally-ink">{it.label}</span>
                <span className="text-xs text-rally-muted">{targets.length} eligible</span>
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                {targets.slice(0, 4).map((inv) => (
                  <Button key={inv.invoice_id} size="sm" variant="secondary" data-testid={`fix-${it.kind}-${inv.invoice_id}`} onClick={() => onPick(it.kind, inv.invoice_id)}>
                    {inv.period}{inv.student_name ? ` · ${inv.student_name}` : ""}
                  </Button>
                ))}
                {targets.length === 0 && <span className="text-xs text-rally-muted">nothing eligible</span>}
              </div>
            </div>
          );
        })}
        <DisabledFixItem label="Account credit" hint="coming later" />
        <DisabledFixItem label="Undo manual payment" hint="coming later" />
      </div>
    </Card>
  );
}
```

- [ ] **Step 6: `page.tsx` — wiring, queries, mutations, dialogs**

```tsx
"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useIsOwner } from "@/components/admin/owner-context";
import { Button, Card, Skeleton } from "@/components/ds";
import {
  applyAdminInvoiceAdjustment,
  chargeAdminInvoiceAutopay,
  enableBillingSetupAutopay,
  fetchInvoiceAudit,
  inviteBillingSetupParent,
  refundAdminInvoice,
  sendAdminInvoice,
  voidAdminInvoice,
} from "@/lib/api/admin";
import { fetchAdminFamilyBilling, pauseFamilyAutopay, type FamilyInvoice, type InvoiceAction } from "@/lib/api/admin-families";
import { formatCents } from "@/lib/money";
import { queryKeys } from "@/lib/query/keys";

import { RecordPaymentDialog } from "../../payments/buckets/RecordPaymentDialog";
import { FamilyHeader } from "./FamilyHeader";
import { FixSomethingPanel } from "./FixSomethingPanel";
import { InvoicesPanel } from "./InvoicesPanel";
import { StudentsPanel } from "./StudentsPanel";
import { TimelinePanel } from "./TimelinePanel";
import { ReasonDialog, type ReasonDialogKind, type ReasonDialogResult } from "./family-dialogs";
import { mintRequestId, periodLabel } from "./family-view";

export default function FamilyBillingPage() {
  const params = useParams<{ parentId: string }>();
  const parentId = params.parentId;
  const queryClient = useQueryClient();
  const isOwner = useIsOwner();
  const [dialog, setDialog] = useState<{ kind: ReasonDialogKind; invoiceId: string | null } | null>(null);
  const [recordFor, setRecordFor] = useState<string | null | false>(false);
  const [audit, setAudit] = useState<{ invoice: FamilyInvoice; entries: unknown[] } | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const query = useQuery({
    queryKey: queryKeys.admin.familyBilling(parentId),
    queryFn: () => fetchAdminFamilyBilling(parentId),
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.admin.familyBilling(parentId) });
    await queryClient.invalidateQueries({ queryKey: queryKeys.admin.collectionsAll() });
  };

  const simple = useMutation({
    mutationFn: async (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => void refresh(),
    onError: (err: Error) => setToast(err.message),
  });

  const view = query.data;
  const invoiceById = new Map((view?.invoices ?? []).map((inv) => [inv.invoice_id, inv]));
  const target = dialog?.invoiceId ? invoiceById.get(dialog.invoiceId) ?? null : null;

  const submitReason = async (r: ReasonDialogResult) => {
    if (!dialog) return;
    switch (dialog.kind) {
      case "void":
        await voidAdminInvoice(dialog.invoiceId!, { reason: r.reason });
        break;
      case "refund":
        await refundAdminInvoice(dialog.invoiceId!, { amount_cents: r.amount_cents, reason: r.reason });
        break;
      case "discount_once":
        await applyAdminInvoiceAdjustment(dialog.invoiceId!, { description: r.description ?? "Discount", amount_cents: -(r.amount_cents ?? 0), reason: r.reason });
        break;
      case "charge_card":
        await chargeAdminInvoiceAutopay(dialog.invoiceId!);
        break;
      case "send_invoice":
        await sendAdminInvoice(dialog.invoiceId!);
        break;
      case "autopay_off":
        await pauseFamilyAutopay(parentId, { reason: r.reason, request_id: mintRequestId() });
        break;
    }
    await refresh();
  };

  const onInvoiceAction = (action: InvoiceAction, inv: FamilyInvoice) => {
    if (action === "record_payment") setRecordFor(inv.invoice_id);
    else if (action === "send") setDialog({ kind: "send_invoice", invoiceId: inv.invoice_id });
    else setDialog({ kind: action, invoiceId: inv.invoice_id });
  };

  if (query.isLoading) {
    return (
      <section data-testid="admin-family-billing" className="space-y-4">
        <Card p={20}><Skeleton lines={3} /></Card>
        <Card p={20}><Skeleton lines={4} /></Card>
        <Card p={20}><Skeleton lines={6} /></Card>
      </section>
    );
  }
  if (query.isError || !view) {
    return (
      <section data-testid="admin-family-billing" className="space-y-4">
        <Card p={20}>
          <p className="text-sm text-rally-ink" data-testid="family-error">Could not load this family. {(query.error as Error | null)?.message ?? ""}</p>
          <Button size="sm" variant="secondary" className="mt-2" data-testid="family-retry" onClick={() => query.refetch()}>Retry</Button>
        </Card>
      </section>
    );
  }

  const owingInvoices = view.invoices.filter((i) => i.actions.includes("record_payment")).map((i) => ({ invoice_id: i.invoice_id, label: `${periodLabel(i.period)}${i.student_name ? ` · ${i.student_name}` : ""} · ${formatCents(i.balance_due_cents)}`, balance_due_cents: i.balance_due_cents }));
  const subject = target ? `${periodLabel(target.period)}${target.student_name ? ` · ${target.student_name}` : ""} · ${formatCents(target.total_cents)}` : `${view.parent.name ?? "This family"} · ${view.header.autopay.active_count} enrollments on autopay`;
  const maxAmount = target && dialog?.kind === "refund" ? target.allocations.filter((a) => a.stripe_payment_intent_id).reduce((s, a) => s + a.amount_cents, 0) : target && dialog?.kind === "discount_once" ? target.balance_due_cents : null;

  return (
    <section data-testid="admin-family-billing" className="space-y-4">
      {toast && (
        <div role="status" className="rounded-lg border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink" data-testid="family-toast">
          {toast} <button type="button" className="ml-2 text-rally-muted" onClick={() => setToast(null)}>×</button>
        </div>
      )}
      <FamilyHeader
        view={view}
        busy={simple.isPending}
        onToggleAutopay={(turnOn) => {
          if (turnOn) simple.mutate(() => enableBillingSetupAutopay(parentId, mintRequestId()));
          else setDialog({ kind: "autopay_off", invoiceId: null });
        }}
        onSendInvite={() => simple.mutate(async () => { const r = await inviteBillingSetupParent(parentId); setToast(r.ok ? "Invite sent." : `Invite failed: ${r.failed_reason ?? "unknown"}`); })}
        onSendInvoice={() => { const first = view.invoices.find((i) => i.actions.includes("send")); if (first) setDialog({ kind: "send_invoice", invoiceId: first.invoice_id }); }}
        onRecordPayment={() => setRecordFor(null)}
      />
      <StudentsPanel students={view.students} isOwner={isOwner} />
      <InvoicesPanel invoices={view.invoices} busy={simple.isPending} onAction={onInvoiceAction} onFullAudit={(inv) => simple.mutate(async () => { const r = await fetchInvoiceAudit(inv.invoice_id); setAudit({ invoice: inv, entries: r.entries }); })} />
      <TimelinePanel timeline={view.timeline} warnings={view.warnings} />
      <FixSomethingPanel invoices={view.invoices} isOwner={isOwner} onPick={(kind, invoiceId) => setDialog({ kind, invoiceId })} />

      {dialog && (
        <ReasonDialog kind={dialog.kind} open subject={subject} maxAmountCents={maxAmount} onClose={() => setDialog(null)} onSubmit={submitReason} />
      )}
      <RecordPaymentDialog
        open={recordFor !== false}
        invoices={owingInvoices}
        initialInvoiceId={recordFor ?? undefined}
        onClose={() => setRecordFor(false)}
        onSaved={() => { setRecordFor(false); void refresh(); }}
      />
      {audit && (
        <Card p={20} data-testid="invoice-audit-drawer">
          <div className="flex items-center justify-between"><span className="font-semibold">Full audit · {periodLabel(audit.invoice.period)}</span><Button size="sm" variant="secondary" onClick={() => setAudit(null)}>Close</Button></div>
          <pre className="mt-2 max-h-80 overflow-auto rounded bg-rally-paper p-2 text-xs">{JSON.stringify(audit.entries, null, 2)}</pre>
        </Card>
      )}
    </section>
  );
}
```

`fetchInvoiceAudit` does not exist yet in `lib/api/admin.ts` (the audit route had no caller). Add next to `fetchInvoiceAttempts`:

```ts
export interface InvoiceAuditResponse {
  entries: Array<Record<string, unknown>>;
}
export function fetchInvoiceAudit(invoiceId: string): Promise<InvoiceAuditResponse> {
  return apiFetch<InvoiceAuditResponse>(`/admin/billing/invoices/${encodeURIComponent(invoiceId)}/audit`);
}
```

Check `RecordPaymentDialog`'s internals call `recordAdminInvoicePayment` itself (it does in spec 1) — the family page only passes options.

- [ ] **Step 7: Typecheck, lint, quick manual render**

Run from `frontend/`: `pnpm exec tsc --noEmit && pnpm exec eslint "app/(admin)/admin/families" lib/api/admin-families.ts lib/api/admin.ts`. Fix every error (typical: `Chip` variant names, `Button` variant names, `DialogActions` prop names).

- [ ] **Step 8: Commit**

```bash
git add "frontend/app/(admin)/admin/families/[parentId]" frontend/lib/api/admin.ts frontend/components/admin/screen-meta.ts
git commit -m "feat(admin): family billing page"
```

---

### Task 8: Families list, redirect, nav, student tab, bucket link

**Files:**
- Create: `frontend/app/(admin)/admin/families/page.tsx` (from `billing-setup/page.tsx`)
- Modify: `frontend/app/(admin)/admin/billing-setup/page.tsx` → redirect; `frontend/components/admin/screen-meta.ts` + `screen-meta.test.ts`; `frontend/app/(admin)/admin/students/[studentId]/page.tsx`; `frontend/app/(admin)/admin/payments/buckets/CollectionsTab.tsx`
- Create: `frontend/app/(admin)/admin/students/[studentId]/FamilyBillingLink.tsx`
- Delete: `frontend/app/(admin)/admin/students/[studentId]/BillingWorkflowPanel.tsx` (its dialogs file `billing-dialogs.tsx` stays because `BillingEnrollmentsPanel.tsx` imports the frame components; remove the now-unused `CreateInvoiceDialog`, `AddInvoiceLineDialog`, `RecordPaymentDialog`, `VoidInvoiceDialog` exports from it only if eslint flags them as unused exports — otherwise leave them).

- [ ] **Step 1: Families list**

`git mv "frontend/app/(admin)/admin/billing-setup/page.tsx" "frontend/app/(admin)/admin/families/page.tsx"`, then edit:
- Rename the component to `FamiliesPage`; keep the query/filter/search/paging code.
- Delete `inviteMutation`, `chargeMutation`, `enableAutopayMutation`, the toast state they fed, and the three row buttons; delete `BillingSetupTableRow`'s `onInvite/onCharge/onEnableAutopay/isInviting/isCharging/isEnablingAutopay` props.
- The parent-name cell becomes `<Link href={`/admin/families/${encodeURIComponent(row.parent_id)}`} data-testid={`family-link-${row.parent_id}`} className="font-medium text-slate-900 hover:underline">{row.parent_name}</Link>`; the Actions column becomes one link "Open" to the same href.
- Root element `data-testid="admin-families"`; page heading copy "Families · every parent, their card and autopay state; open one for the full picture".

Then write the redirect:

```tsx
// frontend/app/(admin)/admin/billing-setup/page.tsx
import { redirect } from "next/navigation";

/** Billing Setup was folded into Families (spec 2026-09-05-family-billing §6). */
export default function BillingSetupRedirect() {
  redirect("/admin/families");
}
```

- [ ] **Step 2: Nav and titles**

In `screen-meta.ts`: replace the Billing Setup nav item with `{ href: "/admin/families", label: "Families", icon: "user", match: startsWith("/admin/families") }`; replace the `"/admin/billing-setup"` meta entry with `"/admin/families": { title: "Families", subtitle: "Every parent: balance, card on file, autopay", breadcrumbs: ["Admin", "Money", "Families"] }` (keep the `[parentId]` entry from Task 7). In `screen-meta.test.ts` add `expect(visible).toContain("/admin/families");` to the admin-visible assertion and, if a test enumerates the Money group hrefs, swap `/admin/billing-setup` for `/admin/families`.

- [ ] **Step 3: Student page Billing tab → link panel**

```tsx
// frontend/app/(admin)/admin/students/[studentId]/FamilyBillingLink.tsx
"use client";

import Link from "next/link";

import { Button, Card, Overline } from "@/components/ds";

export function FamilyBillingLink({ parentId, parentName }: { parentId: string | null | undefined; parentName: string | null | undefined }) {
  return (
    <Card p={20} data-testid="admin-student-family-billing-link">
      <Overline>Billing</Overline>
      <p className="mt-1 text-sm text-rally-muted">Invoices, payments, autopay and corrections live on the family page, which covers every sibling.</p>
      {parentId ? (
        <Link href={`/admin/families/${encodeURIComponent(parentId)}`} className="mt-3 inline-block">
          <Button size="sm" variant="primary">Open family billing{parentName ? ` · ${parentName}` : ""}</Button>
        </Link>
      ) : (
        <p className="mt-2 text-sm text-rally-muted">This student has no parent on file.</p>
      )}
    </Card>
  );
}
```

In `students/[studentId]/page.tsx`: replace the `BillingWorkflowPanel` usage and import with `<FamilyBillingLink parentId={student.parent_id} parentName={student.parent_name} />` (keep `BillingEnrollmentsPanel` beneath it — price override and move belong to the student). Delete `BillingWorkflowPanel.tsx`. Run `pnpm exec tsc --noEmit`; if `billing-dialogs.tsx` exports become unused, leave them (they are not lint errors).

- [ ] **Step 4: Bucket rows link to the family page**

In `CollectionsTab.tsx` replace the `firstStudent ? <Link href=/admin/students/…>` block with an unconditional `<Link href={`/admin/families/${encodeURIComponent(family.parent_id)}`} data-testid={`family-link-${family.parent_id}`} …>{name}</Link>` and drop the `firstStudent` variable if unused. Update `admin-payments-buckets.spec.ts` if it asserts the student href (`grep -n "admin/students" frontend/e2e/specs/admin-payments-buckets.spec.ts`).

- [ ] **Step 5: Typecheck, lint, vitest, commit**

```bash
cd frontend && pnpm exec tsc --noEmit && pnpm exec eslint "app/(admin)/admin/families" "app/(admin)/admin/students/[studentId]" "app/(admin)/admin/payments/buckets" components/admin && pnpm exec vitest run components/admin
git add -A frontend/app frontend/components/admin
git commit -m "feat(admin): Families list replaces Billing Setup; student billing tab links to the family page"
```

---

### Task 9: Playwright, old specs, QA manifest

**Files:**
- Create: `frontend/e2e/specs/admin-family-billing.spec.ts`
- Modify: `frontend/e2e/specs/admin-students.spec.ts`, `frontend/e2e/specs/admin-payments-buckets.spec.ts` (if it asserted the student href), `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`

- [ ] **Step 1: The family spec**

```ts
import { test, expect, type Page } from "@playwright/test";

import { collectConsoleErrors, installTenantGuard } from "../fixtures/tenant-isolation";
import { ACADEMY_A, ADMIN_USER_A, fulfillJson, stubAcademy, stubMe, stubMemberships } from "../fixtures/saas-stubs";

/** Family billing page (spec 2026-09-05-family-billing §6, §8) with a stubbed family. */

const FAMILY = {
  generated_at: "2026-09-10T15:00:00Z",
  timezone: "America/Chicago",
  today: "2026-09-10",
  parent: { parent_id: "parent-1", name: "Sahaya Vinodh", email: "sahaya@example.com", phone: null },
  header: {
    balance_cents: 7000,
    open_invoice_count: 1,
    available_credit_cents: 0,
    last_payment: { amount_cents: 6000, method: "card", paid_at: "2026-08-04T14:00:00Z", invoice_ids: ["inv-aug"] },
    autopay: { state: "on", active_count: 1, total_count: 1, card_last4: "4242", card_label: "Visa", next_charge_on: "2026-09-08", next_charge_invoice_id: "inv-sep", last_failure: null },
    registration: { state: "registered", card_on_file: true, last_invited_at: null },
    enrollment_counts: { active: 1, paused: 1, cancelled: 0 },
  },
  students: [
    { student_id: "stu-hannah", name: "Hannah", status: "active", enrollments: [{ enrollment_id: "enr-hannah", session_id: "sess-wed", session_title: "Wed 6:15 Intermediate", schedule: "Wed 18:15", status: "paused", monthly_price_cents: 7000, override_price_cents: null, autopay_status: "paused", recurring_discount: null, resume_on: "2026-10-01", actions: ["recurring_discount"] }] },
    { student_id: "stu-arjun", name: "Arjun", status: "active", enrollments: [{ enrollment_id: "enr-arjun", session_id: "sess-sat", session_title: "Sat 9:00 Beginners", schedule: "Sat 09:00", status: "active", monthly_price_cents: 6000, override_price_cents: null, autopay_status: "active", recurring_discount: null, resume_on: null, actions: ["recurring_discount"] }] },
  ],
  invoices: [
    { invoice_id: "inv-sep", invoice_number: "INV-2026-09-003", period: "2026-09", student_id: "stu-arjun", student_name: "Arjun", enrollment_id: "enr-arjun", status: "open", total_cents: 7000, paid_cents: 0, balance_due_cents: 7000, due_date: "2026-09-08", created_at: "2026-09-01T06:00:00Z", paid_at: null, voided_at: null, void_reason: null, settlement_unlinked: false, delivery: { status: "sent", last_sent_at: "2026-09-01T06:05:00Z", kind: "autopay_notice" }, allocations: [], credits: [], chargeable: true, actions: ["send", "record_payment", "charge_card", "void", "discount_once"] },
    { invoice_id: "inv-aug", invoice_number: "INV-2026-08-001", period: "2026-08", student_id: "stu-arjun", student_name: "Arjun", enrollment_id: "enr-arjun", status: "paid", total_cents: 6000, paid_cents: 6000, balance_due_cents: 0, due_date: "2026-08-08", created_at: "2026-08-01T06:00:00Z", paid_at: "2026-08-04T14:00:00Z", voided_at: null, void_reason: null, settlement_unlinked: false, delivery: { status: "sent", last_sent_at: "2026-08-01T06:05:00Z", kind: "autopay_notice" }, allocations: [{ payment_id: "pay-aug", amount_cents: 6000, method: "card", paid_at: "2026-08-04T14:00:00Z", stripe_payment_intent_id: "pi_aug" }], credits: [], chargeable: false, actions: ["refund"] },
  ],
  timeline: [
    { at: "2026-09-04T20:00:00Z", kind: "money", code: "invoice_voided", summary: "Sep 2026 invoice voided · Hannah · enrollment paused", invoice_id: "inv-h", invoice_ids: ["inv-h"], enrollment_id: null, student_name: "Hannah", actor_id: null, reason: "enrollment paused", amount_cents: null, muted: false },
    { at: "2026-09-01T06:05:00Z", kind: "comms", code: "autopay_notice_emailed", summary: "Autopay notice emailed · Sep 2026 · Arjun", invoice_id: "inv-sep", invoice_ids: ["inv-sep"], enrollment_id: null, student_name: "Arjun", actor_id: null, reason: null, amount_cents: null, muted: true },
    { at: "2026-08-04T14:00:00Z", kind: "money", code: "payment_received", summary: "$60 received · card ••4242", invoice_id: null, invoice_ids: ["inv-aug"], enrollment_id: null, student_name: null, actor_id: null, reason: "pay-aug", amount_cents: 6000, muted: false },
  ],
  actions: ["autopay_off", "send_invoice", "record_payment"],
  warnings: [],
};

async function setup(page: Page, opts: { owner: boolean; view?: typeof FAMILY }) {
  const errors = collectConsoleErrors(page);
  await installTenantGuard(page, ACADEMY_A);
  await stubMe(page, opts.owner ? ADMIN_USER_A : { ...ADMIN_USER_A, roles: ["admin"] });
  await stubMemberships(page, ADMIN_USER_A, [ACADEMY_A]);
  await stubAcademy(page, ACADEMY_A);
  const posts: { url: string; body: unknown }[] = [];
  await page.route("**/api/v2/admin/families/**", (route) => {
    const req = route.request();
    if (req.method() === "POST") {
      posts.push({ url: req.url(), body: req.postDataJSON() });
      return fulfillJson(route, { paused_count: 1, active_count_before: 1, warnings: [] });
    }
    return fulfillJson(route, opts.view ?? FAMILY);
  });
  await page.route("**/api/v2/admin/billing/invoices/**", (route) => {
    const req = route.request();
    if (req.method() === "POST") {
      posts.push({ url: req.url(), body: req.postDataJSON() });
      return fulfillJson(route, { ok: true });
    }
    return fulfillJson(route, { entries: [{ action: "manual_payment_recorded", actor_id: "admin-1" }] });
  });
  await page.route("**/api/v2/admin/messages/**", (route) => fulfillJson(route, { messages: [] }));
  await page.goto("/admin/families/parent-1");
  await expect(page.getByTestId("admin-family-billing")).toBeVisible();
  return { errors, posts };
}

test.describe("Family billing", () => {
  test("header, students, invoices and timeline render from one response", async ({ page }) => {
    const { errors } = await setup(page, { owner: true });
    await expect(page.getByTestId("family-balance")).toContainText("$70");
    await expect(page.getByTestId("family-autopay-hint")).toContainText("Visa ••4242 · next charge Sep 8");
    await expect(page.getByTestId("family-last-payment")).toContainText("$60");
    await expect(page.getByTestId("family-registration-chip")).toContainText("Card on file");
    await expect(page.getByTestId("enrollment-row-enr-hannah")).toContainText("resumes Oct 1");
    await expect(page.getByTestId("invoice-row-inv-sep")).toContainText("Sep 2026 · Arjun");
    await page.getByTestId("invoice-expand-inv-aug").click();
    await expect(page.getByTestId("invoice-allocations-inv-aug")).toContainText("pi_aug");
    await expect(page.getByTestId("timeline-entry-autopay_notice_emailed")).toHaveAttribute("data-tone", "muted");
    await expect(page.getByTestId("timeline-entry-payment_received")).toContainText("$60 received");
    expect(errors).toEqual([]);
  });

  test("turning autopay off asks for a reason and posts to the pause route", async ({ page }) => {
    const { posts } = await setup(page, { owner: true });
    await page.getByTestId("family-autopay-toggle").click();
    await expect(page.getByTestId("reason-dialog")).toBeVisible();
    await expect(page.getByRole("button", { name: "Turn off" })).toBeDisabled();
    await page.getByTestId("reason-input").fill("parent asked to pause");
    await page.getByRole("button", { name: "Turn off" }).click();
    await expect.poll(() => posts.length).toBe(1);
    expect(posts[0].url).toContain("/admin/families/parent-1/autopay/pause");
    expect(posts[0].body).toMatchObject({ reason: "parent asked to pause" });
    expect((posts[0].body as { request_id: string }).request_id).toBeTruthy();
  });

  test("needs_consent disables the toggle and offers the invite", async ({ page }) => {
    const view = { ...FAMILY, actions: ["send_invite"], header: { ...FAMILY.header, autopay: { ...FAMILY.header.autopay, state: "needs_consent", card_last4: null, card_label: null, next_charge_on: null }, registration: { state: "not_invited", card_on_file: false, last_invited_at: null } } };
    await setup(page, { owner: true, view: view as typeof FAMILY });
    await expect(page.getByTestId("family-autopay-toggle")).toBeDisabled();
    await expect(page.getByTestId("family-autopay-hint")).toContainText("Needs parent consent");
    await expect(page.getByTestId("family-send-invite")).toBeVisible();
  });

  test("void requires a reason and posts it; refund hidden for a plain admin", async ({ page }) => {
    const { posts } = await setup(page, { owner: true });
    await page.getByTestId("invoice-action-void-inv-sep").click();
    await expect(page.getByRole("button", { name: "Void invoice" }).last()).toBeDisabled();
    await page.getByTestId("reason-input").fill("duplicate invoice");
    await page.getByRole("button", { name: "Void invoice" }).last().click();
    await expect.poll(() => posts.length).toBe(1);
    expect(posts[0].url).toContain("/admin/billing/invoices/inv-sep/void");
    expect(posts[0].body).toEqual({ reason: "duplicate invoice" });
  });

  test("admin without owner scope sees no owner-only buttons", async ({ page }) => {
    const view = { ...FAMILY, invoices: FAMILY.invoices.map((i) => ({ ...i, actions: i.actions.filter((a) => !["void", "refund", "discount_once"].includes(a)) })) };
    await setup(page, { owner: false, view: view as typeof FAMILY });
    await expect(page.getByTestId("invoice-action-void-inv-sep")).toHaveCount(0);
    await expect(page.getByTestId("invoice-action-refund-inv-aug")).toHaveCount(0);
    await expect(page.getByTestId("family-fix")).not.toContainText("Refund");
    await expect(page.getByTestId("family-fix")).toContainText("Charge card now");
  });

  test("full audit calls the audit route", async ({ page }) => {
    await setup(page, { owner: true });
    await page.getByTestId("invoice-expand-inv-aug").click();
    await page.getByTestId("invoice-audit-inv-aug").click();
    await expect(page.getByTestId("invoice-audit-drawer")).toContainText("manual_payment_recorded");
  });

  test("billing-setup redirects to families and the list links to a family", async ({ page }) => {
    await installTenantGuard(page, ACADEMY_A);
    await stubMe(page, ADMIN_USER_A);
    await stubMemberships(page, ADMIN_USER_A, [ACADEMY_A]);
    await stubAcademy(page, ACADEMY_A);
    await page.route("**/api/v2/admin/billing/setup*", (route) =>
      fulfillJson(route, { rows: [{ parent_id: "parent-1", parent_name: "Sahaya Vinodh", parent_email: "sahaya@example.com", students: [{ student_id: "stu-arjun", full_name: "Arjun" }], registration_state: "card_on_file", card_label: "Visa", card_last4: "4242", autopay_active_count: 1, autopay_eligible_count: 0, outstanding_balance_cents: 7000, charge_invoice_id: null, charge_amount_cents: 0, charge_autopay_eligible: false, last_invited_at: null }], summary: { total: 1, no_account: 0, account_no_card: 0, card_on_file: 1 }, next_cursor: null }),
    );
    await page.goto("/admin/billing-setup");
    await expect(page).toHaveURL(/\/admin\/families$/);
    await expect(page.getByTestId("admin-families")).toBeVisible();
    await expect(page.getByTestId("family-link-parent-1")).toHaveAttribute("href", "/admin/families/parent-1");
  });
});
```

Check the real `BillingSetupPageResponse` field names (`grep -n "export interface BillingSetupPageResponse" -A 8 frontend/lib/api/admin.ts`) and the `stubMe` `MockUser` shape before running; adjust the fixture to match. `installTenantGuard`'s signature: `sed -n 94,110p frontend/e2e/fixtures/tenant-isolation.ts`.

- [ ] **Step 2: Rewrite the student spec's Billing assertions**

In `admin-students.spec.ts`, replace the block from `await page.getByRole("tab", { name: "Billing" }).click();` through the last `admin-student-current-payment` assertion with:

```ts
    await page.getByRole("tab", { name: "Billing" }).click();
    await expect(page.getByTestId("admin-student-family-billing-link")).toContainText("Open family billing");
    await expect(page.getByTestId("admin-student-family-billing-link").getByRole("link")).toHaveAttribute("href", /\/admin\/families\//);
```

Remove the now-unneeded `billing/invoices/pay-1` and student-invoice stubs only if nothing else in the spec uses them (keep the `billing-enrollments*` and `session-types*` stubs: `BillingEnrollmentsPanel` still renders on the tab). Make sure the student fixture in that spec carries `parent_id`.

- [ ] **Step 3: Manifest**

In `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`: change the `/admin/billing-setup` entry's `workflows` to `["Redirect to /admin/families"]`, `controls` to empty lists, `states` `["redirect"]`, `risk_edges` `["Old bookmark lands on the redirect"]`, `acceptance` one line each; add two entries modelled on the `/admin/payments` entry:
- `/admin/families` (role admin, source `frontend/app/(admin)/admin/families/page.tsx`, workflows: filter and search families, open a family).
- `/admin/families/[parentId]` (role admin, source `frontend/app/(admin)/admin/families/[parentId]/page.tsx`, workflows: read balance/autopay/last payment, turn autopay off with a reason, record a payment, void/refund/discount with a reason, open full audit; risk edges: owner-only action shown to admin, action without reason, stale balance after action).

Run: `cd backend && .venv/bin/python -m pytest v2/tests/unit/test_audit_inventory_manifest.py -q` → PASS (route tree and manifest agree; the 49 floor still holds).

- [ ] **Step 4: Run the touched e2e specs**

From `frontend/` with the local stack's dev server convention used by spec 1 (see `admin-payments-buckets.spec.ts` header and `playwright.config.ts` `webServer`): `pnpm exec playwright test e2e/specs/admin-family-billing.spec.ts e2e/specs/admin-students.spec.ts e2e/specs/admin-payments-buckets.spec.ts --project=chromium`. Expected: all pass. Fix selectors, not assertions, unless the assertion contradicts the spec.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/specs/admin-family-billing.spec.ts frontend/e2e/specs/admin-students.spec.ts frontend/e2e/specs/admin-payments-buckets.spec.ts docs/qa/2026-06-28-production-scale-local-inventory-manifest.json
git commit -m "test(admin): family billing e2e, student billing tab, QA manifest"
```

---

### Task 10: Release note, full gates

**Files:**
- Create: `docs/release-notes/2026-09-06-feat-family-billing.md` (PR number filled in after the PR is opened; the Release Notes Gate needs the real number)

- [ ] **Step 1: Release note (three exact sections)**

```markdown
# feat-family-billing

PR: #NNN

## What changed
New admin **Family billing** page at `/admin/families/[parentId]`: one parent's balance,
autopay state with a family-level ON/OFF switch (card on file, next charge date), last
payment, students and classes, the invoice ledger with allocations and credits, a merged
timeline of what the system did (invoices generated/voided, payments, failed charges,
dunning, admin actions with reasons, enrollment lifecycle, emails), and a "Fix something"
block (void, refund, one-time discount, charge card now) where every action requires a
reason. Fed by one read-only endpoint `GET /admin/families/{parent_id}/billing`. One new
write endpoint `POST /admin/families/{parent_id}/autopay/pause` (admin; reason +
request_id; pauses every active enrollment's autopay; audited as `autopay_paused`).
**Billing Setup** is removed: `/admin/billing-setup` redirects to the new **Families**
list (`/admin/families`, same data, rows open the family page); its Send invite / Enable
autopay actions moved to the family header and Charge now became per-invoice. The
student page's Billing tab now links to the family page (price override and move stay).
Bucket rows on Payments link to the family page. The previously uncalled invoice audit
route backs the "Full audit" drawer.

## Deploy notes
None. No migration, no new env vars, no data change. `billing_audit_log` gains an
optional `parent_id` field on new rows only.

## Risk / rollback
Autopay OFF is the only new write; it goes through the existing guarded status
transition (`active → paused`) and never touches invoices or dunning, so the worst case
is a family that stops being auto-charged until the toggle is turned back on. Owner-only
corrections are enforced by the existing owner-gated routes regardless of what the page
shows. Rollback is reverting the PR; `/admin/billing-setup` bookmarks then work again.
```

- [ ] **Step 2: Backend gates (from `backend/`)**

```bash
.venv/bin/python -m pytest v2/tests -n auto -q
.venv/bin/ruff check v2 && .venv/bin/ruff format --check v2
PYTHONPATH=.. .venv/bin/lint-imports --config pyproject.toml
```

From the repo root: `backend/.venv/bin/mypy --config-file backend/pyproject.toml -p backend.v2 | backend/.venv/bin/mypy-baseline filter --baseline-path backend/mypy-baseline.txt --allow-unsynced` → no new errors and no "unused type: ignore" lines.

- [ ] **Step 3: Frontend gates (from `frontend/`)**

```bash
pnpm exec tsc --noEmit
pnpm exec eslint .
pnpm exec vitest run
pnpm exec playwright test e2e/specs/admin-family-billing.spec.ts e2e/specs/admin-students.spec.ts e2e/specs/admin-payments-buckets.spec.ts e2e/specs/admin-shell.spec.ts --project=chromium
```

- [ ] **Step 4: Commit the release note, then Phase C (review workflow) per the session instructions before pushing**

```bash
git add docs/release-notes/2026-09-06-feat-family-billing.md
git commit -m "docs(release-notes): family billing page"
```

## Self-review notes

- Spec §3.1 query list ↔ Task 3: every numbered source has a method (`_parent`, `_students`, `_enrollments`+`_sessions`, `_billing_enrollments`, `_discounts`, `_invoices`, `_allocations`, `_credit_applications`+`balance_for_parent`, `_attempts`, `_dunning`, `list_for_family`, `_events`, `_customer`, `_connected_account_ready`).
- Spec §3.4 ↔ Task 2 `invoice_actions`/`family_actions`, Task 5 owner stripping, Task 7 buttons from `actions` only.
- Spec §4 ↔ Task 2 `build_timeline` codes; receipts/reminders deliberately absent.
- Spec §5 ↔ Task 4 + Task 5 pause route (admin persona, so `OWNER_ONLY_ROUTE_PATHS` unchanged).
- Spec §6 ↔ Tasks 7–8 (page, list, redirect, nav, student tab, bucket link). Recurring discount is a link to the student page's existing dialog rather than a new dialog — YAGNI; note it in the PR.
- Spec §7 ↔ Task 3 warnings + Task 5 503/404, Task 7 error/retry panel.
- Spec §8 ↔ Tasks 1–6 tests, Task 9 e2e/manifest.
- Deviation from spec §5 wording: one audit entry per family (as written), stored with `parent_id`; the enable path's per-enrollment entries are found via `before.enrollment_id`.
