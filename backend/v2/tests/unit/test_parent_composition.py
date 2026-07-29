"""Parent composition launch-hardening checks."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.composition.parent import compose_parent, compose_parent_webhook_handler
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
from backend.v2.contexts.billing.domain.errors import CheckoutCreationFailed
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice
from backend.v2.contexts.onboarding.domain.errors import IncompleteApplication
from backend.v2.shared.config import get_settings
from backend.v2.shared.tenancy import tenant_scope


class _FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs

    def sort(self, spec: list[tuple[str, int]]) -> _FakeCursor:
        for field, direction in reversed(spec):
            self.docs.sort(key=lambda doc: doc.get(field), reverse=direction < 0)
        return self

    def limit(self, n: int) -> _FakeCursor:
        self.docs = self.docs[:n]
        return self

    def __aiter__(self) -> _FakeCursor:
        self._iter = iter(self.docs)
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []
        self.updates: list[dict[str, Any]] = []

    async def find_one(self, query: dict[str, Any], **_: Any) -> dict[str, Any] | None:
        for doc in self.docs:
            if _matches(doc, query):
                return doc
        return None

    def find(
        self,
        query: dict[str, Any],
        *_: Any,
        sort: list[tuple[str, int]] | None = None,
        limit: int = 0,
        **__: Any,
    ) -> _FakeCursor:
        docs = [doc for doc in self.docs if _matches(doc, query)]
        cursor = _FakeCursor(docs)
        if sort:
            cursor.sort(sort)
        if limit:
            cursor.limit(limit)
        return cursor

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], **_: Any) -> None:
        self.updates.append({"query": query, "update": update})


class _FakeDb:
    def __init__(self, collections: dict[str, _FakeCollection] | None = None) -> None:
        self.collections = collections or {}

    def __getitem__(self, name: str) -> _FakeCollection:
        if name not in self.collections:
            self.collections[name] = _FakeCollection()
        return self.collections[name]


class _PortalStripe:
    def __init__(self) -> None:
        self.portal_calls: list[dict[str, Any]] = []

    async def create_customer_portal_session(
        self, *, parent_id: str, return_url: str, stripe_customer_id: str | None
    ) -> str:
        self.portal_calls.append(
            {
                "parent_id": parent_id,
                "return_url": return_url,
                "stripe_customer_id": stripe_customer_id,
            }
        )
        if not stripe_customer_id:
            raise ValueError("missing stored stripe customer")
        return "https://billing.stripe.com/session"


class _InvoiceCheckoutStripe(_PortalStripe):
    def __init__(self, *, fail: bool = False) -> None:
        super().__init__()
        self.fail = fail
        self.invoice_checkout_calls: list[dict[str, Any]] = []

    async def create_invoice_checkout_session(self, **kwargs: Any) -> tuple[str, str]:
        self.invoice_checkout_calls.append(kwargs)
        if self.fail:
            raise RuntimeError("stripe rejected destination account")
        return "cs_invoice_test", "https://checkout.stripe.test/balance"


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(doc, option) for option in expected):
                return False
        elif isinstance(expected, dict) and "$in" in expected:
            if doc.get(key) not in expected["$in"]:
                return False
        elif doc.get(key) != expected:
            return False
    return True


def _invoice_doc(
    *,
    invoice_id: str,
    parent_id: str = "parent-1",
    balance_due_cents: int = 7_000,
    created_at: datetime | None = None,
    enrollment_id: str | None = None,
) -> dict[str, Any]:
    now = created_at or datetime(2026, 7, 3, 10, 0, tzinfo=UTC)
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="acad",
        parent_id=parent_id,
        student_id="student-1",
        enrollment_id=enrollment_id,
        period="2026-07",
        status="open",
        subtotal_cents=balance_due_cents,
        discount_cents=0,
        total_cents=balance_due_cents,
        balance_due_cents=balance_due_cents,
        currency="usd",
        due_date=date(2026, 7, 31),
        created_at=now,
        updated_at=now,
    ).model_dump(mode="python")


def _connected_account_doc(*, ready: bool = True) -> dict[str, Any]:
    account = ConnectedAccount.new(
        academy_id="acad",
        stripe_account_id="acct_ready",
    )
    if ready:
        account = account.with_status(status="active", charges_enabled=True)
    return account.model_dump(mode="python")


@pytest.fixture
def allow_app_origin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("V2_CORS_ORIGINS", "https://app.example.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_parent_composition_requires_explicit_academy_id() -> None:
    with pytest.raises(ValueError, match="academy_id is required"):
        compose_parent(
            _FakeDb(),
            outbox=object(),  # type: ignore[arg-type]
            idempotency_store=object(),  # type: ignore[arg-type]
            stripe=_PortalStripe(),  # type: ignore[arg-type]
        )


def test_parent_webhook_composition_requires_explicit_academy_id() -> None:
    with pytest.raises(ValueError, match="academy_id is required"):
        compose_parent_webhook_handler(
            _FakeDb(),
            outbox=object(),  # type: ignore[arg-type]
            stripe=_PortalStripe(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_parent_payment_history_suppresses_matching_legacy_projection() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 6, 17, 9, 0, tzinfo=UTC)
    db = _FakeDb(
        {
            "payments": _FakeCollection(
                [
                    {
                        "academy_id": "acad",
                        "payment_id": "legacy-projection",
                        "parent_id": "parent-1",
                        "amount_cents": 7_000,
                        "currency": "usd",
                        "status": "succeeded",
                        "refunded_cents": 0,
                        "stripe_payment_intent_id": "in_subscription_paid",
                        "created_at": now,
                        "updated_at": now,
                    }
                ]
            ),
            "ledger_payments": _FakeCollection(
                [
                    {
                        "academy_id": "acad",
                        "payment_id": "ledger-payment",
                        "parent_id": "parent-1",
                        "amount_cents": 7_000,
                        "currency": "usd",
                        "status": "succeeded",
                        "stripe_invoice_id": "in_subscription_paid",
                        "stripe_payment_intent_id": "in_subscription_paid",
                        "created_at": now,
                        "updated_at": now,
                    }
                ]
            ),
        }
    )
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=_PortalStripe(),  # type: ignore[arg-type]
        academy_id="acad",
    )

    assert callable(parent.start_balance_payment_for_parent)

    with tenant_scope("acad"):
        rows = await parent.list_payments_for_parent("parent-1")

    assert [row.payment_id for row in rows] == ["ledger-payment"]


@pytest.mark.asyncio
async def test_parent_single_invoice_payment_routes_checkout_to_ready_connected_account(
    allow_app_origin,
) -> None:
    stripe = _InvoiceCheckoutStripe()
    db = _FakeDb(
        {
            "invoices": _FakeCollection([_invoice_doc(invoice_id="inv-1")]),
            "academy_connected_accounts": _FakeCollection([_connected_account_doc()]),
        }
    )
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
    )

    with tenant_scope("acad"):
        result = await parent.start_invoice_payment_for_parent(
            parent_id="parent-1",
            invoice_id="inv-1",
            success_url="https://app.example.com/parent/payments?invoice=paid",
            cancel_url="https://app.example.com/parent/payments?invoice=cancelled",
        )

    assert result == {
        "invoice_id": "inv-1",
        "checkout_url": "https://checkout.stripe.test/balance",
    }
    assert stripe.invoice_checkout_calls[0]["connected_account_id"] == "acct_ready"


@pytest.mark.asyncio
async def test_parent_single_invoice_payment_refuses_platform_charge_without_ready_account(
    allow_app_origin,
) -> None:
    stripe = _InvoiceCheckoutStripe()
    db = _FakeDb(
        {
            "invoices": _FakeCollection([_invoice_doc(invoice_id="inv-1")]),
            "academy_connected_accounts": _FakeCollection([]),
        }
    )
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
    )

    with tenant_scope("acad"):
        with pytest.raises(ValueError, match="invoice payment link unavailable"):
            await parent.start_invoice_payment_for_parent(
                parent_id="parent-1",
                invoice_id="inv-1",
                success_url="https://app.example.com/parent/payments?invoice=paid",
                cancel_url="https://app.example.com/parent/payments?invoice=cancelled",
            )

    assert stripe.invoice_checkout_calls == []


@pytest.mark.asyncio
async def test_parent_balance_payment_routes_checkout_to_ready_connected_account(
    allow_app_origin,
) -> None:
    stripe = _InvoiceCheckoutStripe()
    db = _FakeDb(
        {
            "invoices": _FakeCollection(
                [
                    _invoice_doc(
                        invoice_id="inv-later",
                        created_at=datetime(2026, 7, 10, tzinfo=UTC),
                    ),
                    _invoice_doc(
                        invoice_id="inv-earlier",
                        balance_due_cents=5_000,
                        created_at=datetime(2026, 7, 1, tzinfo=UTC),
                    ),
                ]
            ),
            "academy_connected_accounts": _FakeCollection([_connected_account_doc()]),
        }
    )
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
    )

    with tenant_scope("acad"):
        result = await parent.start_balance_payment_for_parent(
            parent_id="parent-1",
            success_url="https://app.example.com/parent/payments?invoice=paid",
            cancel_url="https://app.example.com/parent/payments?invoice=cancelled",
        )

    assert result == {"redirect_url": "https://checkout.stripe.test/balance"}
    assert stripe.invoice_checkout_calls
    call = stripe.invoice_checkout_calls[0]
    assert call["amount_cents"] == 12_000
    assert call["connected_account_id"] == "acct_ready"
    assert call["metadata"]["invoice_ids"] == "inv-earlier,inv-later"
    assert call["metadata"]["type"] == "balance_payment"


@pytest.mark.asyncio
async def test_parent_single_invoice_payment_with_enroll_autopay_forwards_flag(
    allow_app_origin,
) -> None:
    stripe = _InvoiceCheckoutStripe()
    db = _FakeDb(
        {
            "invoices": _FakeCollection(
                [_invoice_doc(invoice_id="inv-1", enrollment_id="enroll-a")]
            ),
            "academy_connected_accounts": _FakeCollection([_connected_account_doc()]),
        }
    )
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
    )

    with tenant_scope("acad"):
        await parent.start_invoice_payment_for_parent(
            parent_id="parent-1",
            invoice_id="inv-1",
            success_url="https://app.example.com/parent/payments?invoice=paid",
            cancel_url="https://app.example.com/parent/payments?invoice=cancelled",
            enroll_autopay=True,
        )

    call = stripe.invoice_checkout_calls[0]
    assert call["save_payment_method_for_autopay"] is True
    assert call["autopay_enrollment_ids"] == ["enroll-a"]
    assert call["connected_account_id"] == "acct_ready"
    # Opted-in redirects must carry a checkout_session_id placeholder so the
    # parent app's checkout-status poll fires on return (not just the
    # webhook) — Stripe substitutes {CHECKOUT_SESSION_ID} at redirect time.
    assert call["success_url"] == (
        "https://app.example.com/parent/payments?invoice=paid"
        "&checkout_session_id={CHECKOUT_SESSION_ID}"
    )


@pytest.mark.asyncio
async def test_parent_balance_payment_with_enroll_autopay_collects_distinct_enrollment_ids(
    allow_app_origin,
) -> None:
    stripe = _InvoiceCheckoutStripe()
    db = _FakeDb(
        {
            "invoices": _FakeCollection(
                [
                    _invoice_doc(invoice_id="inv-1", enrollment_id="enroll-b"),
                    _invoice_doc(
                        invoice_id="inv-2",
                        balance_due_cents=5_000,
                        enrollment_id="enroll-a",
                    ),
                    _invoice_doc(
                        invoice_id="inv-3",
                        balance_due_cents=3_000,
                        enrollment_id="enroll-a",
                    ),
                    _invoice_doc(invoice_id="inv-4", balance_due_cents=2_000),
                ]
            ),
            "academy_connected_accounts": _FakeCollection([_connected_account_doc()]),
        }
    )
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
    )

    with tenant_scope("acad"):
        result = await parent.start_balance_payment_for_parent(
            parent_id="parent-1",
            success_url="https://app.example.com/parent/payments?invoice=paid",
            cancel_url="https://app.example.com/parent/payments?invoice=cancelled",
            enroll_autopay=True,
        )

    assert result == {"redirect_url": "https://checkout.stripe.test/balance"}
    call = stripe.invoice_checkout_calls[0]
    assert call["save_payment_method_for_autopay"] is True
    # Distinct, deterministic; invoices without an enrollment are excluded.
    assert call["autopay_enrollment_ids"] == ["enroll-a", "enroll-b"]
    # A distinct idempotency key so an earlier one-time balance session is not
    # replayed without the saved-payment-method params.
    assert str(call["idempotency_key"]).endswith(":autopay-optin")
    # Same checkout_session_id placeholder requirement as the single-invoice
    # path (see test above) — the balance payment path builds its own Stripe
    # call directly rather than delegating to SendInvoice.
    assert call["success_url"] == (
        "https://app.example.com/parent/payments?invoice=paid"
        "&checkout_session_id={CHECKOUT_SESSION_ID}"
    )


@pytest.mark.asyncio
async def test_parent_balance_payment_without_flag_omits_autopay_kwargs(
    allow_app_origin,
) -> None:
    stripe = _InvoiceCheckoutStripe()
    db = _FakeDb(
        {
            "invoices": _FakeCollection(
                [
                    _invoice_doc(invoice_id="inv-1", enrollment_id="enroll-a"),
                    _invoice_doc(
                        invoice_id="inv-2",
                        balance_due_cents=5_000,
                        enrollment_id="enroll-b",
                    ),
                ]
            ),
            "academy_connected_accounts": _FakeCollection([_connected_account_doc()]),
        }
    )
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
    )

    with tenant_scope("acad"):
        await parent.start_balance_payment_for_parent(
            parent_id="parent-1",
            success_url="https://app.example.com/parent/payments?invoice=paid",
            cancel_url="https://app.example.com/parent/payments?invoice=cancelled",
        )

    call = stripe.invoice_checkout_calls[0]
    assert "save_payment_method_for_autopay" not in call
    assert "autopay_enrollment_ids" not in call
    assert not str(call["idempotency_key"]).endswith(":autopay-optin")
    # Byte-identical redirect when not opted in — no checkout_session_id
    # placeholder appended.
    assert call["success_url"] == "https://app.example.com/parent/payments?invoice=paid"


@pytest.mark.asyncio
async def test_parent_balance_payment_refuses_platform_charge_without_ready_account(
    allow_app_origin,
) -> None:
    stripe = _InvoiceCheckoutStripe()
    db = _FakeDb(
        {
            "invoices": _FakeCollection(
                [
                    _invoice_doc(invoice_id="inv-1"),
                    _invoice_doc(invoice_id="inv-2", balance_due_cents=5_000),
                ]
            ),
            "academy_connected_accounts": _FakeCollection([]),
        }
    )
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
    )

    with tenant_scope("acad"):
        with pytest.raises(ValueError, match="balance payment unavailable"):
            await parent.start_balance_payment_for_parent(
                parent_id="parent-1",
                success_url="https://app.example.com/parent/payments?invoice=paid",
                cancel_url="https://app.example.com/parent/payments?invoice=cancelled",
            )

    assert stripe.invoice_checkout_calls == []


@pytest.mark.asyncio
async def test_parent_balance_payment_falls_back_to_platform_when_flag_on(
    allow_app_origin,
) -> None:
    stripe = _InvoiceCheckoutStripe()
    db = _FakeDb(
        {
            "invoices": _FakeCollection(
                [
                    _invoice_doc(invoice_id="inv-1"),
                    _invoice_doc(invoice_id="inv-2", balance_due_cents=5_000),
                ]
            ),
            "academy_connected_accounts": _FakeCollection([]),
            "billing_settings": _FakeCollection(
                [{"academy_id": "acad", "allow_platform_charge_fallback": True}]
            ),
        }
    )
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
    )

    with tenant_scope("acad"):
        result = await parent.start_balance_payment_for_parent(
            parent_id="parent-1",
            success_url="https://app.example.com/parent/payments?invoice=paid",
            cancel_url="https://app.example.com/parent/payments?invoice=cancelled",
        )

    assert result == {"redirect_url": "https://checkout.stripe.test/balance"}
    assert stripe.invoice_checkout_calls[0]["connected_account_id"] is None


@pytest.mark.asyncio
async def test_parent_balance_payment_provider_failure_returns_unavailable(
    allow_app_origin,
) -> None:
    stripe = _InvoiceCheckoutStripe(fail=True)
    db = _FakeDb(
        {
            "invoices": _FakeCollection(
                [
                    _invoice_doc(invoice_id="inv-1"),
                    _invoice_doc(invoice_id="inv-2", balance_due_cents=5_000),
                ]
            ),
            "academy_connected_accounts": _FakeCollection([_connected_account_doc()]),
        }
    )
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
    )

    with tenant_scope("acad"):
        with pytest.raises(ValueError, match="balance payment unavailable"):
            await parent.start_balance_payment_for_parent(
                parent_id="parent-1",
                success_url="https://app.example.com/parent/payments?invoice=paid",
                cancel_url="https://app.example.com/parent/payments?invoice=cancelled",
            )

    assert stripe.invoice_checkout_calls[0]["connected_account_id"] == "acct_ready"


@pytest.mark.asyncio
async def test_parent_payment_history_labels_ledger_payments_with_invoice_period() -> None:
    """Ledger payments are linked (via payment_allocations) to the invoice they
    paid, so the UI can render "Tuition · Apr 2026" instead of two identical
    monthly rows that look like a duplicate charge."""
    from datetime import UTC, datetime

    april = datetime(2026, 4, 3, 9, 0, tzinfo=UTC)
    may = datetime(2026, 5, 3, 9, 0, tzinfo=UTC)
    db = _FakeDb(
        {
            "ledger_payments": _FakeCollection(
                [
                    {
                        "academy_id": "acad",
                        "payment_id": "pay-apr",
                        "parent_id": "parent-1",
                        "amount_cents": 6_000,
                        "currency": "usd",
                        "status": "succeeded",
                        "stripe_payment_intent_id": "pi_apr",
                        "created_at": april,
                        "updated_at": april,
                    },
                    {
                        "academy_id": "acad",
                        "payment_id": "pay-may",
                        "parent_id": "parent-1",
                        "amount_cents": 6_000,
                        "currency": "usd",
                        "status": "succeeded",
                        "stripe_payment_intent_id": "pi_may",
                        "created_at": may,
                        "updated_at": may,
                    },
                ]
            ),
            "payment_allocations": _FakeCollection(
                [
                    {
                        "academy_id": "acad",
                        "allocation_id": "alloc-1",
                        "payment_id": "pay-apr",
                        "invoice_id": "inv-apr",
                        "amount_cents": 6_000,
                    },
                    {
                        "academy_id": "acad",
                        "allocation_id": "alloc-2",
                        "payment_id": "pay-may",
                        "invoice_id": "inv-may",
                        "amount_cents": 6_000,
                    },
                ]
            ),
            "invoices": _FakeCollection(
                [
                    {"academy_id": "acad", "invoice_id": "inv-apr", "period": "2026-04"},
                    {"academy_id": "acad", "invoice_id": "inv-may", "period": "2026-05"},
                ]
            ),
        }
    )
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=_PortalStripe(),  # type: ignore[arg-type]
        academy_id="acad",
    )

    with tenant_scope("acad"):
        rows = await parent.list_payments_for_parent("parent-1")

    by_id = {row.payment_id: row for row in rows}
    assert by_id["pay-apr"].invoice_id == "inv-apr"
    assert by_id["pay-apr"].invoice_period == "2026-04"
    assert by_id["pay-may"].invoice_id == "inv-may"
    assert by_id["pay-may"].invoice_period == "2026-05"


@pytest.mark.asyncio
async def test_parent_enrollment_visibility_uses_app_owned_autopay_projection() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    db = _FakeDb(
        {
            "students": _FakeCollection(
                [
                    {
                        "academy_id": "acad",
                        "student_id": "student-1",
                        "parent_id": "parent-1",
                        "full_name": "Alice Smith",
                    }
                ]
            ),
            "enrollments": _FakeCollection(
                [
                    {
                        "academy_id": "acad",
                        "enrollment_id": "enr-1",
                        "student_id": "student-1",
                        "session_id": "sess-1",
                        "status": "active",
                        "payment_mode": "monthly",
                        "subscription_status": "incomplete",
                        "created_at": now,
                    }
                ]
            ),
            "sessions": _FakeCollection(
                [
                    {
                        "academy_id": "acad",
                        "session_id": "sess-1",
                        "title": "Morning Squad",
                    }
                ]
            ),
            "student_billing_enrollments": _FakeCollection(
                [
                    {
                        "academy_id": "acad",
                        "enrollment_id": "enr-1",
                        "student_id": "student-1",
                        "parent_id": "parent-1",
                        "session_type_id": "stype-1",
                        "billing_start_date": now,
                        "status": "active",
                        "autopay_enrollment_status": "active",
                        "last_attempt_outcome": "declined",
                        "last_attempt_at": now,
                        "last_failure_code": "insufficient_funds",
                        "enrolled_at": now,
                        "updated_at": now,
                    }
                ]
            ),
            "parent_billing_customers": _FakeCollection(
                [
                    {
                        "academy_id": "acad",
                        "parent_id": "parent-1",
                        "primary_payment_method_type": "us_bank_account",
                        "primary_payment_method_label": "Stripe Test Bank",
                        "primary_payment_method_last4": "6789",
                        "primary_setup_status": "active",
                    }
                ]
            ),
        }
    )
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=_PortalStripe(),  # type: ignore[arg-type]
        academy_id="acad",
    )

    with tenant_scope("acad"):
        rows = await parent.list_enrollments_for_parent("parent-1")

    assert rows == [
        {
            "enrollment_id": "enr-1",
            "student_id": "student-1",
            "student_name": "Alice Smith",
            "session_id": "sess-1",
            "session_title": "Morning Squad",
            "status": "active",
            "payment_mode": "monthly",
            "subscription_status": "incomplete",
            "autopay_enrollment_status": "active",
            "last_attempt_outcome": "declined",
            "last_attempt_at": now,
            "last_failure_code": "insufficient_funds",
            "autopay_payment_method_type": "us_bank_account",
            "autopay_payment_method_label": "Stripe Test Bank",
            "autopay_payment_method_last4": "6789",
            "autopay_setup_status": "active",
        }
    ]


@pytest.mark.asyncio
async def test_billing_portal_does_not_fall_back_to_global_email_customer_lookup(
    monkeypatch,
) -> None:
    # The portal return_url must be on the redirect allowlist (P0-1); configure it.
    from backend.v2.shared.config.settings import get_settings

    monkeypatch.setenv("V2_CORS_ORIGINS", "https://app.example.com")
    get_settings.cache_clear()
    try:
        stripe = _PortalStripe()
        db = _FakeDb(
            {
                "users": _FakeCollection(
                    [
                        {
                            "_id": "mongo-parent",
                            "academy_id": "acad",
                            "user_id": "parent-1",
                            "email": "parent@example.com",
                        }
                    ]
                )
            }
        )
        parent = compose_parent(
            db,  # type: ignore[arg-type]
            outbox=object(),  # type: ignore[arg-type]
            idempotency_store=object(),  # type: ignore[arg-type]
            stripe=stripe,  # type: ignore[arg-type]
            academy_id="acad",
        )

        with (
            tenant_scope("acad"),
            pytest.raises(CheckoutCreationFailed, match="missing stored stripe customer"),
        ):
            await parent.open_billing_portal(
                parent_id="parent-1",
                return_url="https://app.example.com/parent/payments",
            )

        assert not hasattr(stripe, "find_customer_id_by_email")
        assert stripe.portal_calls == [
            {
                "parent_id": "parent-1",
                "return_url": "https://app.example.com/parent/payments",
                "stripe_customer_id": None,
            }
        ]
    finally:
        get_settings.cache_clear()


class _AutopaySetupStripe(_PortalStripe):
    def __init__(self) -> None:
        super().__init__()
        self.autopay_setup_checkouts: list[dict[str, Any]] = []

    async def create_autopay_setup_checkout_session(
        self,
        *,
        parent_id: str,
        enrollment_id: str,
        session_id: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
        connected_account_id: str | None = None,
    ) -> tuple[str, str]:
        self.autopay_setup_checkouts.append(
            {
                "parent_id": parent_id,
                "enrollment_id": enrollment_id,
                "session_id": session_id,
                "connected_account_id": connected_account_id,
                "metadata": metadata,
            }
        )
        return "cs_setup_test", "https://checkout.stripe.test/autopay"


@pytest.mark.asyncio
async def test_start_autopay_does_not_stamp_dangling_subscription_fields(
    allow_app_origin,
) -> None:
    """Autopay setup stopped writing a subscriptions doc in #266, so the
    enrollment must not be stamped with a subscription_id pointing at a
    nonexistent doc, nor a subscription_status that then stays "incomplete"
    forever. Autopay state lives on
    student_billing_enrollments.autopay_enrollment_status.
    """
    start = datetime(2026, 7, 10, 17, 0, tzinfo=UTC)
    stripe = _AutopaySetupStripe()
    db = _FakeDb(
        {
            "enrollments": _FakeCollection(
                [
                    {
                        "academy_id": "acad",
                        "enrollment_id": "enr-1",
                        "student_id": "student-1",
                        "session_id": "sess-1",
                    }
                ]
            ),
            "students": _FakeCollection(
                [
                    {
                        "academy_id": "acad",
                        "student_id": "student-1",
                        "parent_id": "parent-1",
                    }
                ]
            ),
            "sessions": _FakeCollection(
                [
                    {
                        "academy_id": "acad",
                        "session_id": "sess-1",
                        "coach_id": "coach-1",
                        "title": "Monday Squad",
                        "start_at": start,
                        "end_at": datetime(2026, 7, 10, 18, 0, tzinfo=UTC),
                        "amount_cents": 12_000,
                        "status": "scheduled",
                    }
                ]
            ),
            "academy_connected_accounts": _FakeCollection([_connected_account_doc()]),
        }
    )
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
    )

    with tenant_scope("acad"):
        result = await parent.start_autopay_for_enrollment(
            parent_id="parent-1",
            enrollment_id="enr-1",
            success_url="https://app.example.com/parent/autopay?status=success",
            cancel_url="https://app.example.com/parent/autopay?status=cancelled",
        )

    assert result.redirect_url == "https://checkout.stripe.test/autopay"
    assert stripe.autopay_setup_checkouts[0]["connected_account_id"] == "acct_ready"

    enrollment_updates = db["enrollments"].updates
    assert len(enrollment_updates) == 1
    set_fields = enrollment_updates[0]["update"]["$set"]
    assert set_fields["payment_mode"] == "monthly"
    assert "subscription_id" not in set_fields
    assert "subscription_status" not in set_fields


@pytest.mark.asyncio
async def test_zero_amount_checkout_skips_stripe_and_moves_to_pending_approval(
    allow_app_origin,
) -> None:
    """A $0 first-month quote (0 billable classes left this month) must not
    reach Stripe — zero-amount Checkout Sessions are rejected and used to
    surface as a 500 to the parent. The application skips payment and goes
    straight to admin review."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["zero-amount-checkout"]

    now = datetime.now(UTC)
    from datetime import timedelta

    await db["onboarding_applications"].insert_one(
        {
            "application_id": "app-1",
            "academy_id": "acad",
            "parent_user_id": "parent-1",
            "parent_email": "parent@example.com",
            "status": "DRAFT",
            "selected_session_id": "sess-1",
            "expires_at": now + timedelta(days=7),
            "created_at": now,
            "updated_at": now,
            "parent_profile": {"first_name": "Meera", "last_name": "Raghavan", "phone": "+1 555 0100"},
            "child_profile": {
                "first_name": "Aanya",
                "last_name": "Raghavan",
                "date_of_birth": "2015-04-02",
                "emergency_contact_name": "Vikram Raghavan",
                "emergency_contact_phone": "+1 555 0111",
            },
        }
    )
    # A bookable one-off session whose only class starts inside the 2-hour
    # same-day cutoff: still listed in the parent catalog (start_at is in the
    # future) but the proration policy bills 0 of 1 classes → $0 first month.
    await db["sessions"].insert_one(
        {
            "session_id": "sess-1",
            "academy_id": "acad",
            "status": "scheduled",
            "title": "Beginner",
            "start_at": now + timedelta(minutes=10),
            "end_at": now + timedelta(minutes=70),
            "capacity": 8,
            "amount_cents": 6_000,
        }
    )

    class _RefusingStripe:
        def __init__(self) -> None:
            self.checkout_calls: list[dict[str, Any]] = []

        async def create_checkout_session(self, **kwargs: Any) -> tuple[str, str]:
            self.checkout_calls.append(kwargs)
            return "cs_should_not_exist", "https://checkout.stripe.test/should-not-exist"

    stripe = _RefusingStripe()
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
    )

    success_url = "https://app.example.com/parent/checkout/return?application_id=app-1"
    with tenant_scope("acad"):
        result = await parent.start_checkout_for_application(
            parent_id="parent-1",
            application_id="app-1",
            success_url=success_url,
            cancel_url="https://app.example.com/parent/onboarding",
        )

    assert stripe.checkout_calls == []
    assert result.payment_id == ""
    assert result.redirect_url == success_url
    app_doc = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    assert app_doc["status"] == "PENDING_APPROVAL"
    assert app_doc["zero_quote_period"] == now.strftime("%Y-%m")


async def test_zero_amount_checkout_still_rejects_an_incomplete_application(
    allow_app_origin,
) -> None:
    """The completeness guard (issue #380) must run BEFORE the zero-amount
    branch — otherwise a $0 registration could skip Stripe AND skip ever
    having to supply DOB/emergency contact, landing a permanently incomplete
    student record with no further checkout to catch it."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["zero-amount-checkout-incomplete"]

    now = datetime.now(UTC)
    from datetime import timedelta

    await db["onboarding_applications"].insert_one(
        {
            "application_id": "app-1",
            "academy_id": "acad",
            "parent_user_id": "parent-1",
            "parent_email": "parent@example.com",
            "status": "DRAFT",
            "selected_session_id": "sess-1",
            "expires_at": now + timedelta(days=7),
            "created_at": now,
            "updated_at": now,
            # No parent_profile/child_profile at all — the common case for an
            # application started before issue #380's wizard fields existed.
        }
    )
    await db["sessions"].insert_one(
        {
            "session_id": "sess-1",
            "academy_id": "acad",
            "status": "scheduled",
            "title": "Beginner",
            "start_at": now + timedelta(minutes=10),
            "end_at": now + timedelta(minutes=70),
            "capacity": 8,
            "amount_cents": 6_000,
        }
    )

    class _RefusingStripe:
        async def create_checkout_session(self, **kwargs: Any) -> tuple[str, str]:
            raise AssertionError("Stripe must not be reached for an incomplete application")

    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=_RefusingStripe(),  # type: ignore[arg-type]
        academy_id="acad",
    )

    with tenant_scope("acad"), pytest.raises(IncompleteApplication):
        await parent.start_checkout_for_application(
            parent_id="parent-1",
            application_id="app-1",
            success_url="https://app.example.com/parent/checkout/return?application_id=app-1",
            cancel_url="https://app.example.com/parent/onboarding",
        )

    app_doc = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    assert app_doc["status"] == "DRAFT"  # never transitioned


# ---------------------------------------------------------------------------
# Self-service profile (issue #380)
# ---------------------------------------------------------------------------


async def _compose_profile_parent(db: Any) -> Any:
    return compose_parent(
        db,
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=object(),  # type: ignore[arg-type]
        academy_id="acad",
    )


async def _seed_profile_fixture(db: Any, *, phone: str | None = "+1 555 0100") -> None:
    await db["users"].insert_one(
        {
            "user_id": "parent-1",
            "academy_id": "acad",
            "email": "parent@example.com",
            "display_name": "Meera Raghavan",
            "phone": phone,
            "roles": ["parent"],
        }
    )
    await db["students"].insert_one(
        {
            "student_id": "stu-1",
            "academy_id": "acad",
            "parent_id": "parent-1",
            "full_name": "Aanya Raghavan",
            "date_of_birth": "2015-04-02",
        }
    )
    await db["students"].insert_one(
        {
            "student_id": "stu-other-parent",
            "academy_id": "acad",
            "parent_id": "someone-else",
            "full_name": "Not Aanya",
        }
    )


async def test_get_parent_profile_reports_gaps_for_missing_fields() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-profile"]
    await _seed_profile_fixture(db, phone=None)
    parent = await _compose_profile_parent(db)

    with tenant_scope("acad"):
        profile = await parent.get_parent_profile("parent-1")

    assert profile["display_name"] == "Meera Raghavan"
    assert profile["email_confirmed"] is False
    assert set(profile["gaps"]["parent"]) == {"phone", "email_confirmed"}
    child_gaps = profile["gaps"]["children"]["stu-1"]
    assert set(child_gaps) == {
        "emergency_contact_name",
        "emergency_contact_phone",
        "medical_notes",
    }
    assert profile["gaps"]["is_complete"] is False
    # Another parent's child never appears in this parent's profile at all.
    assert "stu-other-parent" not in profile["gaps"]["children"]


async def test_update_parent_profile_closes_the_phone_gap() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-profile"]
    await _seed_profile_fixture(db, phone=None)
    parent = await _compose_profile_parent(db)

    class _Request:
        display_name = None
        phone = "+1 555 0199"

    with tenant_scope("acad"):
        profile = await parent.update_parent_profile("parent-1", _Request())

    assert profile["phone"] == "+1 555 0199"
    assert "phone" not in profile["gaps"]["parent"]


async def test_confirm_parent_email_closes_the_email_gap() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-profile"]
    await _seed_profile_fixture(db)
    parent = await _compose_profile_parent(db)

    with tenant_scope("acad"):
        profile = await parent.confirm_parent_email("parent-1")

    assert profile["email_confirmed"] is True
    assert "email_confirmed" not in profile["gaps"]["parent"]


async def test_update_parent_child_writes_emergency_contact_and_closes_gaps() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-profile"]
    await _seed_profile_fixture(db)
    parent = await _compose_profile_parent(db)

    class _Request:
        date_of_birth = None
        emergency_contact_name = "Vikram Raghavan"
        emergency_contact_phone = "+1 555 0111"
        medical_notes = None
        no_medical_conditions = True

    with tenant_scope("acad"):
        profile = await parent.update_parent_child("parent-1", "stu-1", _Request())

    child = next(c for c in profile["children"] if c["student_id"] == "stu-1")
    assert child["emergency_contact_name"] == "Vikram Raghavan"
    assert child["no_medical_conditions"] is True
    assert child["medical_notes"] is None  # sentinel is never surfaced to the parent
    assert profile["gaps"]["children"]["stu-1"] == []

    student_doc = await db["students"].find_one({"student_id": "stu-1"})
    assert student_doc["medical_notes"] == "__none_declared__"


async def test_update_parent_child_refuses_a_student_owned_by_another_parent() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-profile"]
    await _seed_profile_fixture(db)
    parent = await _compose_profile_parent(db)

    class _Request:
        date_of_birth = None
        emergency_contact_name = "Someone"
        emergency_contact_phone = None
        medical_notes = None
        no_medical_conditions = False

    with tenant_scope("acad"):
        result = await parent.update_parent_child("parent-1", "stu-other-parent", _Request())

    assert result is None
    untouched = await db["students"].find_one({"student_id": "stu-other-parent"})
    assert untouched["full_name"] == "Not Aanya"  # confirms nothing was written


async def test_update_parent_child_refuses_an_unknown_student_id() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-profile"]
    await _seed_profile_fixture(db)
    parent = await _compose_profile_parent(db)

    class _Request:
        date_of_birth = None
        emergency_contact_name = "Someone"
        emergency_contact_phone = None
        medical_notes = None
        no_medical_conditions = False

    with tenant_scope("acad"):
        result = await parent.update_parent_child("parent-1", "does-not-exist", _Request())

    assert result is None
