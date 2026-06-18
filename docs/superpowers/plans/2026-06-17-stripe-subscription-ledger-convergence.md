# Stripe Subscription Ledger Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Stripe subscription `invoice.paid` the authoritative local payment event for monthly autopay by converging Stripe invoice payments into the local AR ledger exactly once, preventing duplicate charge/allocation behavior, and making the result visible in admin and parent billing UIs.

**Architecture:** Keep ADR-0012 as the source-of-truth rule: `LedgerInvoice` represents what is owed, `LedgerPayment` represents money received, and `PaymentAllocation` applies money to invoices. Legacy `Payment` remains only a temporary read projection until Phase 5. Stripe webhook handling resolves tenant-owned identity through local subscription/enrollment records, writes ledger rows idempotently by Stripe invoice id, and lets admin/parent views read one deduped billing history.

**Tech Stack:** Backend FastAPI v2, MongoDB/Motor, Stripe Checkout/Subscriptions/Invoices/PaymentIntents, Pydantic domain models, pytest. Frontend Next.js App Router, React Query, TypeScript v2 API clients.

---

## Business Problem

Monthly autopay is a trust-critical billing workflow. A parent turns on autopay expecting the academy to collect tuition every month, show a receipt, reduce the balance due to zero, and never charge the same obligation twice. An admin expects the student Billing tab to show the current invoice as paid after Stripe collects the subscription invoice.

Today the business experience can diverge:

- Stripe successfully creates a subscription invoice and charges the parent.
- Webhooks arrive and return 200.
- Local subscription/autopay state can become active.
- A legacy `payments` row can be created for parent/admin history.
- The canonical ledger invoice can still remain open or missing.

That means the money was received in Stripe, but the local AR ledger may not know the obligation was satisfied. The admin may still see a current invoice due, the parent may not see a coherent billing history, and later collection paths can behave as if the invoice still has a balance.

This is not just a UI defect. It is a financial integrity problem:

- A paid Stripe invoice must map to exactly one local payment fact.
- A local monthly invoice for the same enrollment/period must be paid down exactly once.
- A webhook replay must not create duplicate `ledger_payments`, duplicate `payment_allocations`, or duplicate legacy projection rows.
- An already-paid or zero-balance invoice must not produce another Stripe Checkout link or off-session PaymentIntent.
- Tenant identity must be explicit; subscription invoice money for one academy/enrollment cannot be inferred from email or accidentally processed under the default academy.

## Current Behavior Found

Current branch: `feat/stripe-ledger-payments-fix`, clean and ahead of origin by one commit.

Evidence from current files:

- `HandleWebhookEvent._on_invoice_paid()` first tries `_handle_session_type_invoice()`. If that returns false, it calls `_payment_from_invoice()` and saves only a legacy `Payment`.
- `_stripe_subscription_id_from_invoice()` already supports Stripe's newer `invoice.parent.subscription_details.subscription` shape.
- `_handle_session_type_invoice()` writes ledger invoice, ledger payment, and allocation with idempotency keys derived from the Stripe invoice id, but it only applies to `StudentBillingEnrollment` session-type subscriptions.
- `MongoBillingLedgerRepository` supports `get_open_invoice_for_student()`, `create_invoice()`, `record_payment()`, and `allocate_payment()`. It does not currently expose enrollment-period lookup, Stripe invoice lookup, or explicit `stripe_invoice_id` fields.
- `SendInvoice.execute()` skips Checkout when balance is zero, but it creates Checkout for any positive-balance status after finalizing drafts. It should gate by payable financial status too.
- `ChargeInvoiceViaAutopay.execute()` blocks paid/void/draft and zero-balance invoices before calling Stripe, but it has no atomic balance claim before external charge.
- Parent payment history currently unions legacy `payments` and `ledger_payments` without a dedupe key.
- Admin student payment history reads legacy `payments` by `student_id` or active `enrollment_id`, then appends invoice shims by `student_id` only. Ledger invoices linked only by `enrollment_id` can be missed.

Worker-thread consensus:

- Ledger is canonical; legacy `Payment` is transition-only.
- Stripe invoice id should be the business idempotency root.
- `payment_intent.succeeded` before `invoice.paid` should not block later invoice allocation.
- Parent/admin read surfaces need one deduped billing history, not independent raw unions.
- Live Docker SaaS proof must query ledger rows, not just legacy `payments`.

## Target Behavior

For a Stripe subscription `invoice.paid` event:

1. Extract Stripe invoice id.
2. Extract Stripe subscription id from `invoice.subscription`, or from `invoice.parent.subscription_details.subscription`.
3. Resolve local `Subscription` by Stripe subscription id.
4. Verify tenant and local identity:
   - `academy_id`
   - `parent_id`
   - `enrollment_id`
   - `session_id`
   - `student_id` from the enrollment row
5. Determine invoice period from Stripe `period_start`.
6. Find a matching local ledger invoice in this order:
   - exact Stripe invoice id, if already linked
   - `academy_id + enrollment_id + period`, including open/partially-paid/draft and paid records
   - `academy_id + student_id + period` only if unambiguous
7. If a payable local invoice exists, record a `LedgerPayment` and allocate to that invoice.
8. If no local invoice exists, create a Stripe-derived ledger invoice, line, payment, and allocation.
9. If the matching local invoice is already paid:
   - same Stripe invoice id: no-op replay
   - different Stripe invoice id for same obligation: do not allocate again; record/quarantine per explicit duplicate-obligation policy
10. Write at most one legacy `Payment` projection for transition history.
11. Mark webhook processed only after idempotent local writes succeed or after a deliberate no-op/quarantine outcome.

Idempotency keys:

- Ledger invoice: `stripe-subscription-invoice:<stripe_invoice_id>`
- Ledger payment: `stripe-invoice-payment:<stripe_invoice_id>`
- Ledger allocation: `stripe-invoice-allocation:<stripe_invoice_id>`
- Legacy projection payment identifier: `payment_intent` if present, else `invoice.id`

UI behavior after webhook:

- Parent payments page shows exactly one succeeded subscription invoice payment.
- Admin student Billing tab shows the current invoice no longer due.
- Admin invoice detail shows allocation/payment evidence.
- Autopay remains active.
- Replay of the same event does not change row counts.

## File Structure

Modify:

- `backend/v2/contexts/billing/domain/ledger.py`
  - Add optional provider identity fields if needed: `stripe_invoice_id` on `LedgerInvoice` and `LedgerPayment`.
- `backend/v2/contexts/billing/application/ports.py`
  - Extend `LedgerRepository` with enrollment-period and Stripe invoice lookup.
  - Add `EnrollmentBillingIdentityRepository` port.
- `backend/v2/contexts/billing/application/use_cases/handle_webhook_event.py`
  - Add generic subscription ledger sync before legacy projection.
  - Add safe tenant/enrollment identity resolution.
  - Add duplicate-obligation handling.
- `backend/v2/contexts/billing/application/use_cases/send_invoice.py`
  - Tighten payable-status guard before creating Checkout.
- `backend/v2/contexts/billing/application/use_cases/charge_invoice_via_autopay.py`
  - Add stronger no-second-charge proof and stale-balance guard.
- `backend/v2/contexts/billing/infrastructure/mongo_billing_ledger_repo.py`
  - Add invoice lookup methods and duplicate-key handling where missing.
- `backend/v2/composition/parent.py`
  - Wire enrollment identity resolver and update parent billing read-model dedupe.
- `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py`
  - Update admin student billing history to include ledger invoices/payments by `enrollment_id` and dedupe legacy projections.
- `backend/v2/migrations/<next>_stripe_subscription_ledger_indexes.py`
  - Add indexes for new lookup fields.
- `backend/v2/tests/application/test_webhook_handler.py`
- `backend/v2/tests/contract/test_billing_idempotency.py`
- `backend/v2/tests/unit/test_send_invoice_use_case.py`
- `backend/v2/tests/unit/test_charge_autopay_use_case.py`
- `backend/v2/tests/interface/test_admin_billing.py`
- `backend/v2/tests/interface/test_parent_payment_routes.py` or existing parent payment route test file
- `backend/v2/tests/contract/test_stripe_webhook_fixture_replay.py`
- `frontend/e2e/specs/qa-defects.spec.ts` or existing parent/admin billing E2E spec if UI checks are broadened.

Do not modify:

- Legacy `/api/*` routes.
- Production secrets or `.env` files.
- Historical payment data outside explicit migration/backfill scripts.

---

## Task 1: Lock The Regression Contract For Subscription `invoice.paid`

**Files:**
- Modify: `backend/v2/tests/application/test_webhook_handler.py`

- [ ] **Step 1: Add a fake enrollment identity port**

Add a test fake near existing fakes:

```python
class FakeEnrollmentBillingIdentity:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, str | None]] = {}

    def seed(
        self,
        *,
        academy_id: str = "acad",
        enrollment_id: str,
        parent_id: str,
        student_id: str | None,
        session_id: str | None,
    ) -> None:
        self.rows[enrollment_id] = {
            "academy_id": academy_id,
            "parent_id": parent_id,
            "student_id": student_id,
            "enrollment_id": enrollment_id,
            "session_id": session_id,
        }

    async def get_billing_identity(
        self,
        enrollment_id: str,
    ) -> dict[str, str | None] | None:
        return self.rows.get(enrollment_id)
```

- [ ] **Step 2: Extend `FakeBillingLedger` to model real idempotency**

Add fake support for:

```python
async def get_open_invoice_for_enrollment(
    self,
    enrollment_id: str,
    period: str,
) -> LedgerInvoice | None:
    for invoice in self.invoices.values():
        if (
            invoice.enrollment_id == enrollment_id
            and invoice.period == period
            and invoice.status in {"draft", "open", "partially_paid"}
        ):
            return invoice
    return None
```

Also track:

```python
self.invoice_keys: dict[str, str] = {}
self.payment_keys: dict[str, str] = {}
self.allocation_keys: set[str] = set()
```

`record_payment()` must return the existing payment for an existing idempotency key. `allocate_payment()` must no-op for an existing allocation idempotency key and must reduce `invoice.balance_due_cents` only once.

- [ ] **Step 3: Add test for Stripe API 2026 invoice shape**

Test name:

```python
async def test_subscription_invoice_paid_parent_subscription_details_allocates_existing_ledger_invoice() -> None:
```

Arrange:

- local `Subscription` with `stripe_subscription_id="sub_api_2026"`, `enrollment_id="enr-1"`, `parent_id="parent-1"`, `session_id="session-1"`
- enrollment identity for `enr-1` with `student_id="student-1"`
- existing ledger invoice `invoice_id="inv-monthly-enr-1-2026-06"`, `period="2026-06"`, `balance_due_cents=7000`
- Stripe event:

```python
{
    "id": "evt_sub_invoice_paid_1",
    "type": "invoice.paid",
    "data": {
        "object": {
            "id": "in_api_2026",
            "subscription": None,
            "parent": {
                "subscription_details": {
                    "subscription": "sub_api_2026",
                }
            },
            "payment_intent": None,
            "amount_paid": 7000,
            "amount_due": 7000,
            "currency": "usd",
            "period_start": 1781712000,
        }
    },
}
```

Assert:

```python
assert ledger.invoices["inv-monthly-enr-1-2026-06"].status == "paid"
assert ledger.invoices["inv-monthly-enr-1-2026-06"].balance_due_cents == 0
assert ledger.payments["ledger-pay-in_api_2026"].stripe_payment_intent_id == "in_api_2026"
assert ledger.allocations[0]["idempotency_key"] == "stripe-invoice-allocation:in_api_2026"
assert repo.by_pi["in_api_2026"].enrollment_id == "enr-1"
```

- [ ] **Step 4: Add replay test with different event ids**

Test name:

```python
async def test_subscription_invoice_paid_replay_does_not_duplicate_ledger_payment_or_allocation() -> None:
```

Run same invoice object twice with event ids `evt_replay_1` and `evt_replay_2`.

Assert:

```python
assert len(ledger.payments) == 1
assert len(ledger.allocations) == 1
assert len(repo.by_id) == 1
assert ledger.invoices["inv-monthly-enr-1-2026-06"].balance_due_cents == 0
```

- [ ] **Step 5: Add out-of-order payment intent test**

Test name:

```python
async def test_subscription_payment_intent_before_invoice_paid_does_not_block_invoice_allocation() -> None:
```

First send:

```python
{"id": "evt_pi_first", "type": "payment_intent.succeeded", "data": {"object": {"id": "pi_sub_first", "amount": 7000, "currency": "usd"}}}
```

Then send the `invoice.paid` with `payment_intent="pi_sub_first"`.

Assert:

```python
assert ledger.payments["ledger-pay-in_sub_first"].stripe_payment_intent_id == "pi_sub_first"
assert len(ledger.allocations) == 1
```

- [ ] **Step 6: Run the tests red**

Run:

```bash
cd /Users/ramc/Documents/Code/academy-manager
source backend/.venv/bin/activate
pytest backend/v2/tests/application/test_webhook_handler.py -q
```

Expected before implementation: new tests fail because generic subscription `invoice.paid` only writes legacy `Payment`.

---

## Task 2: Add Provider Identity And Ledger Lookup Support

**Files:**
- Modify: `backend/v2/contexts/billing/domain/ledger.py`
- Modify: `backend/v2/contexts/billing/application/ports.py`
- Modify: `backend/v2/contexts/billing/infrastructure/mongo_billing_ledger_repo.py`
- Create: `backend/v2/migrations/<next>_stripe_subscription_ledger_indexes.py`
- Test: `backend/v2/tests/contract/test_billing_idempotency.py`

- [ ] **Step 1: Add optional Stripe invoice identity to ledger models**

In `LedgerInvoice`, add:

```python
stripe_invoice_id: str | None = None
source_type: str | None = None
source_id: str | None = None
```

In `LedgerPayment`, add:

```python
stripe_invoice_id: str | None = None
```

Rationale: using `stripe_payment_intent_id` to hold invoice ids when `payment_intent=None` works for short-term idempotency, but is weak for audit and reconciliation.

- [ ] **Step 2: Extend `LedgerRepository` port**

Add methods:

```python
async def get_invoice_by_stripe_invoice_id(
    self,
    stripe_invoice_id: str,
) -> LedgerInvoice | None: ...

async def get_invoice_for_enrollment_period(
    self,
    enrollment_id: str,
    period: str,
    *,
    statuses: set[str] | None = None,
) -> LedgerInvoice | None: ...
```

Keep `get_open_invoice_for_student()` for backward compatibility, but do not use it as the primary subscription match.

- [ ] **Step 3: Implement Mongo methods**

In `MongoBillingLedgerRepository`:

```python
async def get_invoice_by_stripe_invoice_id(
    self,
    stripe_invoice_id: str,
) -> LedgerInvoice | None:
    doc = await self._find_one({"stripe_invoice_id": stripe_invoice_id})
    return self._invoice_from_doc(doc) if doc else None
```

```python
async def get_invoice_for_enrollment_period(
    self,
    enrollment_id: str,
    period: str,
    *,
    statuses: set[str] | None = None,
) -> LedgerInvoice | None:
    query: dict[str, object] = {
        "enrollment_id": enrollment_id,
        "period": period,
    }
    if statuses is not None:
        query["status"] = {"$in": sorted(statuses)}
    doc = await self._find_one(query, sort=[("created_at", -1), ("invoice_id", -1)])
    return self._invoice_from_doc(doc) if doc else None
```

If `_find_one()` does not accept `sort`, add a small local collection call that preserves tenant scoping:

```python
doc = await self.collection.find_one(
    {"academy_id": current_academy_id(), **query},
    sort=[("created_at", -1), ("invoice_id", -1)],
)
```

- [ ] **Step 4: Harden allocation duplicate race**

Wrap allocation insert in `DuplicateKeyError` handling:

```python
try:
    await self._db["payment_allocations"].insert_one(allocation_doc)
except DuplicateKeyError:
    existing = await self._db["payment_allocations"].find_one(
        {"academy_id": academy_id, "idempotency_key": idempotency_key}
    )
    if existing is not None:
        return await self._existing_allocation_result(existing)
    raise
```

- [ ] **Step 5: Add indexes**

Migration should create:

```python
await db["invoices"].create_index(
    [("academy_id", 1), ("stripe_invoice_id", 1)],
    name="academy_stripe_invoice_unique",
    unique=True,
    partialFilterExpression={"stripe_invoice_id": {"$type": "string"}},
)
await db["invoices"].create_index(
    [("academy_id", 1), ("enrollment_id", 1), ("period", 1), ("status", 1)],
    name="academy_enrollment_period_status",
)
await db["ledger_payments"].create_index(
    [("academy_id", 1), ("stripe_invoice_id", 1)],
    name="academy_ledger_payment_stripe_invoice",
    partialFilterExpression={"stripe_invoice_id": {"$type": "string"}},
)
await db["payment_allocations"].create_index(
    [("academy_id", 1), ("idempotency_key", 1)],
    name="academy_payment_allocation_idempotency_unique",
    unique=True,
)
```

- [ ] **Step 6: Add Mongo-backed idempotency test**

In `test_billing_idempotency.py`, add:

```python
async def test_subscription_invoice_paid_allocates_existing_ledger_invoice_idempotently(db, acad) -> None:
```

Arrange a real `MongoBillingLedgerRepository` invoice with `enrollment_id="enr-1"` and a fake local subscription with `stripe_subscription_id="sub_stripe_1"`.

Replay the same Stripe invoice with two event ids.

Assert:

```python
assert await db["ledger_payments"].count_documents({"academy_id": acad}) == 1
assert await db["payment_allocations"].count_documents({"academy_id": acad}) == 1
assert (await db["invoices"].find_one({"academy_id": acad, "invoice_id": invoice_id}))["balance_due_cents"] == 0
assert await db["payments"].count_documents({"academy_id": acad}) == 1
```

- [ ] **Step 7: Run contract tests red**

Run:

```bash
source backend/.venv/bin/activate
pytest backend/v2/tests/contract/test_billing_idempotency.py -q
```

Expected before implementation: new subscription invoice contract fails.

---

## Task 3: Add Tenant-Owned Enrollment Billing Identity Resolution

**Files:**
- Modify: `backend/v2/contexts/billing/application/ports.py`
- Modify: `backend/v2/composition/parent.py`
- Test: `backend/v2/tests/unit/test_parent_composition.py`
- Test: `backend/v2/tests/application/test_webhook_handler.py`

- [ ] **Step 1: Add identity model and port**

In `ports.py`:

```python
class EnrollmentBillingIdentity(BaseModel):
    academy_id: str
    parent_id: str
    student_id: str | None = None
    enrollment_id: str
    session_id: str | None = None


class EnrollmentBillingIdentityRepository(Protocol):
    async def get_billing_identity(
        self,
        enrollment_id: str,
    ) -> EnrollmentBillingIdentity | None: ...
```

- [ ] **Step 2: Add optional dependency to `HandleWebhookEvent.__init__`**

Parameter:

```python
enrollment_identity: EnrollmentBillingIdentityRepository | None = None
```

Store as:

```python
self._enrollment_identity = enrollment_identity
```

- [ ] **Step 3: Wire parent composition**

In `backend/v2/composition/parent.py`, create a small adapter:

```python
class _MongoEnrollmentBillingIdentity:
    def __init__(self, db: Any, *, academy_id: str) -> None:
        self._db = db
        self._academy_id = academy_id

    async def get_billing_identity(
        self,
        enrollment_id: str,
    ) -> EnrollmentBillingIdentity | None:
        doc = await self._db["enrollments"].find_one(
            {"academy_id": self._academy_id, "enrollment_id": enrollment_id}
        )
        if doc is None:
            return None
        return EnrollmentBillingIdentity(
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc.get("parent_id") or ""),
            student_id=str(doc["student_id"]) if doc.get("student_id") else None,
            enrollment_id=str(doc["enrollment_id"]),
            session_id=str(doc["session_id"]) if doc.get("session_id") else None,
        )
```

Inject it into `HandleWebhookEvent`.

- [ ] **Step 4: Validate tenant mismatches**

Add helper behavior in `HandleWebhookEvent`:

```python
if identity.academy_id != subscription.academy_id:
    raise _QuarantineStripeEvent("subscription enrollment academy mismatch")
if identity.parent_id and identity.parent_id != subscription.parent_id:
    raise _QuarantineStripeEvent("subscription enrollment parent mismatch")
```

- [ ] **Step 5: Add mismatch tests**

Add tests:

```python
async def test_subscription_invoice_paid_quarantines_enrollment_academy_mismatch() -> None:
async def test_subscription_invoice_paid_quarantines_enrollment_parent_mismatch() -> None:
```

Expected: event is not marked successful as a financial write; no ledger payment/allocation is created.

---

## Task 4: Implement Generic Subscription Invoice Ledger Sync

**Files:**
- Modify: `backend/v2/contexts/billing/application/use_cases/handle_webhook_event.py`
- Test: `backend/v2/tests/application/test_webhook_handler.py`
- Test: `backend/v2/tests/contract/test_billing_idempotency.py`

- [ ] **Step 1: Route generic subscription invoice through ledger before legacy projection**

Change `_on_invoice_paid()` from:

```python
if await self._handle_session_type_invoice(invoice, paid=True):
    return
payment = await self._payment_from_invoice(invoice, status="succeeded")
```

To:

```python
if await self._handle_session_type_invoice(invoice, paid=True):
    return
ledger_invoice = await self._sync_subscription_invoice_ledger(invoice, paid=True)
payment = await self._payment_from_invoice(invoice, status="succeeded")
```

Legacy projection remains after ledger write during transition.

- [ ] **Step 2: Add `_sync_subscription_invoice_ledger()`**

Behavior:

```python
async def _sync_subscription_invoice_ledger(
    self,
    invoice: dict[str, Any],
    *,
    paid: bool,
) -> LedgerInvoice | None:
    if self._billing_ledger is None:
        return None
    stripe_invoice_id = str(invoice.get("id") or "")
    if not stripe_invoice_id:
        raise _QuarantineStripeEvent("subscription invoice missing id")
    stripe_subscription_id = self._stripe_subscription_id_from_invoice(invoice)
    if not stripe_subscription_id:
        return None
    subscription = await self._subscriptions.get_by_stripe_sub(stripe_subscription_id)
    if subscription is None:
        raise _QuarantineStripeEvent(f"unknown subscription invoice={stripe_invoice_id}")
    if subscription.academy_id != self._academy_id:
        raise _QuarantineStripeEvent("subscription invoice academy mismatch")
```

Then resolve identity:

```python
identity = await self._subscription_enrollment_identity(subscription)
```

Compute:

```python
amount_cents = int(invoice.get("amount_paid" if paid else "amount_due") or invoice.get("amount_due") or 0)
period = self._invoice_period_label(invoice, self._now())
currency = str(invoice.get("currency") or "usd").lower()
```

If `amount_cents <= 0`, return existing or created invoice without recording a payment.

- [ ] **Step 3: Find or create ledger invoice**

Lookup:

```python
ledger_invoice = await self._billing_ledger.get_invoice_by_stripe_invoice_id(stripe_invoice_id)
if ledger_invoice is None and subscription.enrollment_id:
    ledger_invoice = await self._billing_ledger.get_invoice_for_enrollment_period(
        subscription.enrollment_id,
        period,
        statuses={"draft", "open", "partially_paid", "paid"},
    )
if ledger_invoice is None and identity.student_id:
    ledger_invoice = await self._billing_ledger.get_open_invoice_for_student(identity.student_id, period)
```

If missing, create:

```python
invoice_id = f"ledger-{stripe_invoice_id}"
ledger_invoice = await self._billing_ledger.create_invoice(
    LedgerInvoice(
        invoice_id=invoice_id,
        academy_id=subscription.academy_id,
        parent_id=subscription.parent_id,
        student_id=identity.student_id,
        enrollment_id=subscription.enrollment_id,
        period=period,
        status="open",
        subtotal_cents=amount_cents,
        discount_cents=0,
        total_cents=amount_cents,
        balance_due_cents=amount_cents,
        currency=currency,
        due_date=self._invoice_due_date(invoice, self._now()),
        stripe_invoice_id=stripe_invoice_id,
        source_type="stripe_subscription",
        source_id=stripe_subscription_id,
        created_at=self._now(),
        updated_at=self._now(),
    ),
    lines=[...],
    idempotency_key=f"stripe-subscription-invoice:{stripe_invoice_id}",
)
```

If found and missing `stripe_invoice_id`, update/save it only when this is the first Stripe invoice mapped to that obligation.

- [ ] **Step 4: Handle already-paid local invoice**

Rules:

```python
if ledger_invoice.status == "paid" or ledger_invoice.balance_due_cents <= 0:
    if ledger_invoice.stripe_invoice_id == stripe_invoice_id:
        return ledger_invoice
    # different Stripe invoice for already-satisfied local obligation
    await self._record_unapplied_subscription_payment_for_review(...)
    return ledger_invoice
```

If no unapplied-review path exists yet, quarantine with a clear message and do not create a second invoice or allocation:

```python
raise _QuarantineStripeEvent(
    f"subscription invoice {stripe_invoice_id} matched already-paid invoice {ledger_invoice.invoice_id}"
)
```

Choose one policy before implementation. Recommended for launch safety: quarantine different-invoice duplicate obligations, because it prevents local double-allocation and forces manual review of a real extra Stripe charge.

- [ ] **Step 5: Record ledger payment and allocation**

```python
stripe_payment_id = str(invoice.get("payment_intent") or stripe_invoice_id)
payment = await self._billing_ledger.record_payment(
    LedgerPayment(
        payment_id=f"ledger-pay-{stripe_invoice_id}",
        academy_id=ledger_invoice.academy_id,
        parent_id=ledger_invoice.parent_id,
        amount_cents=amount_cents,
        unapplied_amount_cents=amount_cents,
        currency=currency,
        status="succeeded",
        payment_method="stripe_subscription",
        stripe_payment_intent_id=stripe_payment_id,
        stripe_invoice_id=stripe_invoice_id,
        paid_at=self._now(),
        created_at=self._now(),
        updated_at=self._now(),
    ),
    idempotency_key=f"stripe-invoice-payment:{stripe_invoice_id}",
)
result = await self._billing_ledger.allocate_payment(
    payment_id=payment.payment_id,
    invoice_id=ledger_invoice.invoice_id,
    amount_cents=amount_cents,
    idempotency_key=f"stripe-invoice-allocation:{stripe_invoice_id}",
)
return result.invoice
```

- [ ] **Step 6: Preserve one legacy projection**

Keep `_payment_from_invoice()` but make it clearly projection-only. Ensure it uses:

```python
stripe_pi = str(invoice.get("payment_intent") or invoice.get("id"))
```

and that `get_by_stripe_pi(stripe_pi)` prevents duplicate projection rows.

- [ ] **Step 7: Run focused green tests**

Run:

```bash
source backend/.venv/bin/activate
pytest backend/v2/tests/application/test_webhook_handler.py backend/v2/tests/contract/test_billing_idempotency.py -q
```

Expected: new tests pass, existing webhook behavior stays green.

---

## Task 5: Tighten Duplicate-Charge Guards

**Files:**
- Modify: `backend/v2/contexts/billing/application/use_cases/send_invoice.py`
- Modify: `backend/v2/contexts/billing/application/use_cases/charge_invoice_via_autopay.py`
- Modify: `backend/v2/contexts/billing/infrastructure/stripe_gateway.py`
- Test: `backend/v2/tests/unit/test_send_invoice_use_case.py`
- Test: `backend/v2/tests/unit/test_charge_autopay_use_case.py`

- [ ] **Step 1: Add SendInvoice payable-status guard**

After finalizing draft invoices:

```python
payable_statuses = {"open", "partially_paid"}
can_create_checkout = invoice.status in payable_statuses and invoice.balance_due_cents > 0
```

Only call Stripe when `can_create_checkout`.

For `paid`, `void`, and positive-balance inconsistent states, skip Stripe and return delivery/email behavior only.

- [ ] **Step 2: Add tests for paid/void positive-balance anomalies**

Tests:

```python
async def test_send_invoice_skips_checkout_for_paid_invoice_even_with_positive_balance() -> None:
async def test_send_invoice_skips_checkout_for_void_invoice_even_with_positive_balance() -> None:
```

Use fake Stripe object with call counter:

```python
assert stripe.calls == []
assert result.checkout_url is None
```

- [ ] **Step 3: Add Stripe Checkout idempotency key support**

In `StripeBillingGateway.create_invoice_checkout_session()`, accept:

```python
idempotency_key: str | None = None
```

Pass to Stripe request options:

```python
self._stripe.checkout.Session.create(
    ...,
    idempotency_key=idempotency_key,
)
```

Use:

```python
idempotency_key=f"invoice-checkout:{invoice.invoice_id}:{invoice.balance_due_cents}"
```

This reduces duplicate Checkout session creation on repeated send clicks. If Stripe library expects request options separately, follow the established adapter pattern in this repo.

- [ ] **Step 4: Add autopay stale-balance recheck**

Immediately before `create_off_session_payment_intent()`, re-read invoice:

```python
fresh = await self._ledger.get_invoice(invoice_id)
if fresh is None:
    raise ValueError(f"invoice {invoice_id!r} not found")
if fresh.status not in _CHARGEABLE_STATUSES or fresh.balance_due_cents <= 0:
    raise ValueError(f"invoice {invoice_id!r} no longer chargeable")
invoice = fresh
```

This does not fully lock all races, but it blocks common stale reads. A later collection-attempt lock can be added if staging shows concurrent admin behavior risk.

- [ ] **Step 5: Add autopay no-Stripe-call tests**

Tests:

```python
async def test_charge_autopay_paid_invoice_does_not_lookup_card_or_call_stripe() -> None:
async def test_charge_autopay_zero_balance_invoice_does_not_lookup_card_or_call_stripe() -> None:
```

Assert:

```python
assert stripe.default_payment_method_calls == []
assert stripe.payment_intent_calls == []
```

- [ ] **Step 6: Run focused duplicate-charge tests**

Run:

```bash
source backend/.venv/bin/activate
pytest backend/v2/tests/unit/test_send_invoice_use_case.py backend/v2/tests/unit/test_charge_autopay_use_case.py -q
```

Expected: all tests pass and fake Stripe call counters prove no external call for paid/zero-balance invoices.

---

## Task 6: Converge Admin And Parent Billing Read Models

**Files:**
- Modify: `backend/v2/composition/parent.py`
- Modify: `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py`
- Test: parent payment route tests, admin student repo tests

- [ ] **Step 1: Define dedupe rule**

For transition rows, prefer ledger rows over legacy projection rows when either matches:

- same `stripe_invoice_id`
- same `stripe_payment_intent_id`
- legacy `stripe_payment_intent_id == ledger.stripe_invoice_id` for null-PI invoices
- same `parent_id + amount_cents + created_at day + subscription_id` only as a last resort

Do not dedupe unrelated manual payments with the same amount.

- [ ] **Step 2: Update parent payment list**

In `list_payments_for_parent`, collect legacy rows and ledger rows with source metadata:

```python
source: Literal["legacy_payment", "ledger_payment"]
stripe_invoice_id: str | None
stripe_payment_intent_id: str | None
```

Build a set of ledger provider keys:

```python
ledger_keys = {
    key
    for row in ledger_rows
    for key in (row.stripe_invoice_id, row.stripe_payment_intent_id)
    if key
}
```

Suppress legacy rows whose `stripe_payment_intent_id` is in `ledger_keys`.

- [ ] **Step 3: Update admin student payment history invoice query**

Change invoice lookup from `student_id` only to:

```python
invoice_owner_filters = [{"student_id": student_id}]
if enrollment_ids:
    invoice_owner_filters.append({"enrollment_id": {"$in": enrollment_ids}})
```

Then:

```python
{
    "academy_id": academy_id,
    "$or": invoice_owner_filters,
    "status": {"$nin": ["void"]},
    "is_deleted": {"$ne": True},
}
```

- [ ] **Step 4: Include allocation/payment evidence in admin invoice detail if missing**

If admin invoice detail already includes allocations from `payment_allocations`, leave it. If not, add a route/composition test that confirms payment allocation row is visible after webhook processing.

- [ ] **Step 5: Add read-model regression tests**

Tests:

```python
async def test_parent_payments_suppresses_legacy_projection_when_ledger_payment_exists() -> None:
async def test_admin_student_history_includes_invoice_linked_only_by_enrollment_id() -> None:
async def test_admin_student_history_does_not_duplicate_legacy_projection_and_paid_invoice() -> None:
```

Expected:

- parent history count for a subscription invoice is one
- admin history shows the paid invoice/payment once
- current invoice balance is zero

---

## Task 7: Add Stripe Fixture And Live-Like Replay Coverage

**Files:**
- Add: `backend/v2/tests/contract/stripe_fixtures/invoice_paid_subscription_api_2026.json`
- Add or modify: `backend/v2/tests/contract/test_stripe_webhook_fixture_replay.py`

- [ ] **Step 1: Add captured-shaped fixture**

Fixture must include:

```json
{
  "id": "evt_invoice_paid_subscription_api_2026",
  "type": "invoice.paid",
  "data": {
    "object": {
      "id": "in_subscription_api_2026",
      "object": "invoice",
      "subscription": null,
      "payment_intent": null,
      "parent": {
        "subscription_details": {
          "subscription": "sub_subscription_api_2026"
        }
      },
      "amount_paid": 7000,
      "amount_due": 7000,
      "currency": "usd",
      "period_start": 1781712000,
      "metadata": {
        "academy_id": "acad",
        "parent_id": "parent-1",
        "enrollment_id": "enr-1",
        "session_id": "session-1",
        "app_subscription_id": "sub-local-1"
      }
    }
  }
}
```

- [ ] **Step 2: Add fixture replay test**

Test:

```python
async def test_fixture_subscription_invoice_paid_api_2026_converges_ledger() -> None:
```

Assert one ledger payment, one allocation, one legacy projection, invoice paid.

- [ ] **Step 3: Run replay tests**

Run:

```bash
source backend/.venv/bin/activate
pytest backend/v2/tests/contract/test_stripe_webhook_fixture_replay.py -q
```

Expected: all fixture replay tests pass.

---

## Task 8: Docker SaaS Staging Proof

**Files:**
- No code changes expected.
- Update active ledger only through `scripts/dev/test_result.py`.

- [x] **Step 1: Start staging**

Run:

```bash
cd /Users/ramc/Documents/Code/academy-manager
scripts/dev/saas_staging.sh up
scripts/dev/saas_staging.sh blno-seed
scripts/dev/saas_staging.sh status
```

Expected: backend, frontend, Mongo, and Firebase emulator healthy.

- [x] **Step 2: Start Stripe forwarding**

Run in a separate terminal:

```bash
STRIPE_API_KEY=sk_test_... scripts/dev/saas_staging.sh stripe-listen
```

Expected:

- backend restarts with `STRIPE_WEBHOOK_SECRET`
- `curl http://127.0.0.1:8001/api/v2/healthz` returns healthy
- terminal remains open forwarding to `/api/v2/parent/webhooks/stripe`

- [x] **Step 3: Complete real sandbox subscription checkout**

Browser:

```text
http://blno-academy.localhost:3000
```

Complete autopay checkout for a seeded parent/enrollment with Stripe test card:

```text
4242 4242 4242 4242
```

Expected Stripe events:

- `checkout.session.completed`
- `invoice.paid`
- `payment_intent.succeeded`
- `customer.subscription.updated`

- [x] **Step 4: Query Mongo for exact-once ledger proof**

Run:

```bash
mongosh mongodb://127.0.0.1:27017/academy_manager_saas_staging
```

Queries:

```javascript
const academy = "blno";
db.stripe_webhook_events.find({academy_id: academy}).sort({received_at: -1}).limit(10);

const stripeInvoiceId = "in_...";
db.ledger_payments.countDocuments({
  academy_id: academy,
  ledger_idempotency_key: `stripe-invoice-payment:${stripeInvoiceId}`
});
db.payment_allocations.countDocuments({
  academy_id: academy,
  idempotency_key: `stripe-invoice-allocation:${stripeInvoiceId}`
});
db.invoices.findOne({
  academy_id: academy,
  stripe_invoice_id: stripeInvoiceId
});
db.payments.countDocuments({
  academy_id: academy,
  stripe_payment_intent_id: stripeInvoiceId
});
db.ledger_payments.aggregate([
  {$match: {academy_id: academy, ledger_idempotency_key: /^stripe-invoice-payment:/}},
  {$group: {_id: "$ledger_idempotency_key", n: {$sum: 1}}},
  {$match: {n: {$ne: 1}}}
]);
db.payment_allocations.aggregate([
  {$match: {academy_id: academy, idempotency_key: /^stripe-invoice-allocation:/}},
  {$group: {_id: "$idempotency_key", n: {$sum: 1}}},
  {$match: {n: {$ne: 1}}}
]);
```

Pass signal:

- exactly one ledger payment
- exactly one allocation
- invoice `balance_due_cents == 0`
- duplicate aggregations return no rows
- parent/admin UI shows one payment record

- [x] **Step 5: Replay same event**

Use Stripe CLI replay or resend the captured event through the local webhook endpoint with a valid Stripe signature from CLI tooling.

Repeat Mongo queries. Counts must remain unchanged.

- [x] **Step 6: Try to charge paid invoice**

Use admin Billing tab or direct admin route for charge autopay on the paid invoice.

Expected:

- backend rejects or returns no-op
- Stripe PaymentIntent creation is not called
- invoice remains paid
- no new ledger payment/allocation appears

- [x] **Step 7: Record proof in ledger**

Use:

```bash
scripts/dev/test_result.py verify 2026-06-16-production-stripe-autopay-billing-fix --message "Docker SaaS staging Stripe subscription ledger proof: <summarize events, invoice id, ledger_payment count, allocation count, invoice balance, replay result, paid-invoice charge result>"
```

---

## Task 9: Full Verification Block

Run focused tests:

```bash
cd /Users/ramc/Documents/Code/academy-manager
source backend/.venv/bin/activate
pytest backend/v2/tests/application/test_webhook_handler.py backend/v2/tests/contract/test_billing_idempotency.py backend/v2/tests/contract/test_stripe_webhook_fixture_replay.py -q
pytest backend/v2/tests/unit/test_send_invoice_use_case.py backend/v2/tests/unit/test_charge_autopay_use_case.py -q
pytest backend/v2/tests/interface/test_admin_billing.py backend/v2/tests/interface/test_parent_sessions_checkout.py -q
```

Run style:

```bash
cd /Users/ramc/Documents/Code/academy-manager/backend
source .venv/bin/activate
ruff format --check v2
ruff check v2
```

Run frontend checks if response shape changes:

```bash
cd /Users/ramc/Documents/Code/academy-manager/frontend
pnpm typecheck
pnpm lint
pnpm build
```

Run broader pre-push before pushing:

```bash
cd /Users/ramc/Documents/Code/academy-manager
scripts/dev/pre-push-checks.sh
```

Expected:

- no duplicate webhook rows
- no duplicate ledger rows
- admin/parent views show one payment
- no Stripe calls for paid/zero balance invoices
- no tenant mismatch silently succeeds

---

## Acceptance Criteria

- Stripe subscription `invoice.paid` with `invoice.parent.subscription_details.subscription` maps to local `Subscription`.
- `payment_intent=null` uses Stripe invoice id as payment fallback and stores explicit `stripe_invoice_id`.
- Existing local invoice for same enrollment/period is paid down to zero.
- Missing local invoice creates a Stripe-derived ledger invoice and pays it.
- Same Stripe invoice replay creates no duplicate `LedgerPayment`, `PaymentAllocation`, or legacy projection.
- `payment_intent.succeeded` before `invoice.paid` does not prevent later ledger convergence.
- Paid/zero-balance invoices cannot trigger another Checkout session or PaymentIntent.
- Parent payments history shows one row for the subscription invoice payment.
- Admin student Billing shows no current due balance after webhook processing.
- Tenant mismatch or unknown subscription is quarantined, not silently processed.
- Docker SaaS staging proof records exact DB counts and UI outcome.

## Risks And Explicit Decisions

- **Already-paid local invoice with a new Stripe invoice:** recommended launch-safe decision is quarantine/manual review, not double allocation and not silent invoice creation.
- **Atomic external charge race:** re-read before Stripe call is a near-term improvement. A full Mongo collection-attempt lock is stronger and should be added if concurrent admin collection is realistic.
- **Read-model duplication:** dual-write is acceptable only if parent/admin read models prefer ledger rows and suppress matching legacy projections.
- **Tenant routing:** current webhook receiver uses app composition scoped to runtime academy. SaaS mode should resolve tenant before durable event storage where possible.
- **Schema compatibility:** optional `stripe_invoice_id` fields are backward-compatible, but indexes must be added before relying on efficient lookup.
- **Legacy Phase 5:** do not delete legacy `Payment` paths in this work.

## Cross-Check Against Payment-System Design Guidance

Reference reviewed: [Designing a Payment Backend with Stripe Integration](https://newsletter.systemdesign.one/p/design-a-payment-system), published 2026-06-10.

The article reinforces that this work is a correctness-under-failure problem, not a feature-richness problem. The useful ideas for this repo are:

- Webhooks are at-least-once and can arrive out of order.
- Exactly-once behavior is achieved through idempotency keys, durable state, and reconciliation, not through trusting delivery order.
- Stripe integration should stay behind an adapter boundary.
- Webhook receipt should be durable and quick; business processing should be retryable.
- Payment state transitions should be explicit and enforceable.
- A reconciliation path should compare local records against Stripe records after the fact.

This plan already covers the first three through invoice-id idempotency, replay tests, and the existing Stripe gateway/use-case boundary. The following additions close the remaining practical gaps without overbuilding Kafka or a full double-entry payment platform.

---

## Task 10: Add Recovery Points And Processing Outcome States

**Why this matters:** A webhook can fail after writing a ledger payment but before allocation, or after allocation but before writing the legacy projection. Event-id dedupe alone can then hide a partially-applied business transaction. The system needs a recoverable business idempotency state keyed by Stripe invoice id.

**Files:**
- Modify: `backend/v2/contexts/billing/application/use_cases/handle_webhook_event.py`
- Modify or add repository support near existing Stripe webhook event storage.
- Test: `backend/v2/tests/contract/test_stripe_event_dedup.py`
- Test: `backend/v2/tests/application/test_webhook_handler.py`

- [x] **Step 1: Define business recovery points for subscription invoice processing**

Use explicit recovery point strings:

```python
SUBSCRIPTION_INVOICE_RECOVERY_POINTS = {
    "received",
    "subscription_resolved",
    "ledger_invoice_synced",
    "ledger_payment_recorded",
    "ledger_allocated",
    "legacy_projection_saved",
    "processed",
    "quarantined",
}
```

These are not financial states. They are processing checkpoints for retry/reconciliation.

- [x] **Step 2: Store recovery point by Stripe invoice id**

Persist a business processing record keyed by:

```python
business_key = f"stripe_invoice:{stripe_invoice_id}"
```

Minimum fields:

```python
{
    "academy_id": academy_id,
    "business_key": business_key,
    "stripe_invoice_id": stripe_invoice_id,
    "stripe_subscription_id": stripe_subscription_id,
    "event_ids": [event_id],
    "recovery_point": "ledger_allocated",
    "ledger_invoice_id": ledger_invoice_id,
    "ledger_payment_id": ledger_payment_id,
    "legacy_payment_id": legacy_payment_id,
    "last_error": None,
    "updated_at": now,
}
```

If an existing row is at `ledger_allocated`, a replay must resume at legacy projection and not repeat allocation.

- [x] **Step 3: Add tests for partial-failure retry**

Tests:

```python
async def test_subscription_invoice_paid_retry_after_ledger_payment_before_allocation_resumes_without_duplicate_payment() -> None:
async def test_subscription_invoice_paid_retry_after_allocation_before_legacy_projection_resumes_without_duplicate_allocation() -> None:
```

Use fakes that fail once at a named step, then rerun same invoice with a different Stripe event id.

Assert:

```python
assert len(ledger.payments) == 1
assert len(ledger.allocations) == 1
assert len(repo.by_id) == 1
```

---

## Task 11: Add A Stripe Subscription Reconciliation Check

**Why this matters:** Stripe is the external payment processor. Even with perfect webhook logic, operators need a way to prove that local ledger state matches Stripe after a real checkout or replay.

**Files:**
- Create: `backend/v2/contexts/billing/application/use_cases/reconcile_stripe_subscription_invoice.py`
- Create or extend: `backend/v2/interfaces/admin/billing_routes.py` for an admin-only diagnostic route if existing conventions allow it.
- Test: `backend/v2/tests/application/test_reconcile_stripe_subscription_invoice.py`

- [ ] **Step 1: Implement a read-only reconciliation use case**

Input:

```python
class ReconcileStripeSubscriptionInvoiceInput(BaseModel):
    stripe_invoice_id: str
```

Output:

```python
class ReconcileStripeSubscriptionInvoiceResult(BaseModel):
    stripe_invoice_id: str
    stripe_subscription_id: str | None
    local_subscription_id: str | None
    ledger_invoice_id: str | None
    ledger_payment_count: int
    allocation_count: int
    legacy_projection_count: int
    invoice_balance_due_cents: int | None
    status: Literal["matched", "missing_ledger", "duplicate_local_rows", "tenant_mismatch", "unknown_subscription"]
    findings: list[str]
```

The use case retrieves the current Stripe invoice through the existing Stripe gateway, then checks local `subscriptions`, `invoices`, `ledger_payments`, `payment_allocations`, and legacy `payments`.

- [ ] **Step 2: Add unit tests**

Tests:

```python
async def test_reconcile_subscription_invoice_reports_matched_when_one_payment_one_allocation_zero_balance() -> None:
async def test_reconcile_subscription_invoice_reports_duplicate_local_rows() -> None:
async def test_reconcile_subscription_invoice_reports_missing_ledger() -> None:
```

- [ ] **Step 3: Use it in Docker SaaS proof**

After checkout and replay, run the reconciliation use case or diagnostic route for the Stripe invoice id.

Expected:

```text
status=matched
ledger_payment_count=1
allocation_count=1
invoice_balance_due_cents=0
```

---

## Task 12: Make Payment State Transitions Explicit For Webhook Projection Rows

**Why this matters:** The article calls out finite-state-machine enforcement. The ledger already encodes invoice/payment allocation rules, but legacy `Payment` projection rows can still be overwritten casually during transition.

**Files:**
- Modify: `backend/v2/contexts/billing/domain/models.py`
- Modify: `backend/v2/contexts/billing/application/use_cases/handle_webhook_event.py`
- Test: `backend/v2/tests/application/test_webhook_handler.py`

- [x] **Step 1: Add a tiny transition helper for legacy projection status**

Allowed projection transitions:

```python
ALLOWED_PAYMENT_PROJECTION_TRANSITIONS = {
    "pending": {"succeeded", "failed", "cancelled"},
    "failed": {"succeeded"},
    "succeeded": {"partially_refunded", "refunded"},
    "partially_refunded": {"refunded"},
    "refunded": set(),
    "cancelled": set(),
}
```

Helper:

```python
def can_transition_payment_projection(current: str, target: str) -> bool:
    if current == target:
        return True
    return target in ALLOWED_PAYMENT_PROJECTION_TRANSITIONS.get(current, set())
```

- [x] **Step 2: Use helper before saving webhook-created legacy projection**

If an existing legacy payment row exists for the provider id:

```python
if not can_transition_payment_projection(existing.status, target_status):
    raise _QuarantineStripeEvent(
        f"invalid payment projection transition {existing.status}->{target_status}"
    )
```

- [x] **Step 3: Add invalid transition tests**

Tests:

```python
async def test_invoice_paid_does_not_downgrade_refunded_projection_to_succeeded() -> None:
async def test_invoice_payment_failed_does_not_downgrade_succeeded_projection_to_failed() -> None:
```

---

## Decision: What Not To Adopt From The Article

Do not add these as part of this fix:

- A new PSP abstraction beyond the existing Stripe gateway. The current adapter boundary is enough.
- Kafka/SQS/RabbitMQ. Current persisted webhook events and retryable handlers are enough at this product scale.
- Custom card entry with Stripe Elements. Hosted Checkout remains correct for this app.
- A full double-entry general ledger redesign. The existing AR ledger is sufficient for invoice/payment allocation; changing the accounting model is out of scope.
- Five-nines availability work. The launch risk is correctness and reconciliation, not raw uptime.

## Self-Review

- Business problem included: yes.
- Current behavior found included: yes.
- Files likely affected included: yes.
- Proposed change included: yes.
- Risks included: yes.
- Verification steps included: yes.
- No application code changes in this plan: yes.
