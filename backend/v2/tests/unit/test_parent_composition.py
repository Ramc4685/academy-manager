"""Parent composition launch-hardening checks."""

from __future__ import annotations

import inspect
import logging
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from backend.v2.composition.parent import compose_parent, compose_parent_webhook_handler
from backend.v2.contexts.billing.application.ports import (
    StripeCheckoutSessionNotExpirable,
)
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
from backend.v2.contexts.billing.domain.errors import (
    CheckoutCreationFailed,
    InvoicePayLinkUnavailable,
    QuoteExpired,
)
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice
from backend.v2.contexts.enrollment.application.use_cases.get_child_schedule import (
    GetChildSchedule,
)
from backend.v2.contexts.onboarding.domain.errors import (
    ApplicationNotEditable,
    IncompleteApplication,
)
from backend.v2.interfaces.parent.views import EnrollmentQuoteRequest
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

    async def insert_one(self, doc: dict[str, Any], **_: Any) -> None:
        self.docs.append(doc)


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


def _enrollment_doc(
    enrollment_id: str,
    *,
    status: str | None = "active",
    student_id: str = "student-1",
    session_id: str = "sess-1",
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "academy_id": "acad",
        "enrollment_id": enrollment_id,
        "student_id": student_id,
        "session_id": session_id,
    }
    if status is not None:
        doc["status"] = status
    return doc


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
        with pytest.raises(
            InvoicePayLinkUnavailable, match="invoice payment link unavailable"
        ) as exc_info:
            await parent.start_invoice_payment_for_parent(
                parent_id="parent-1",
                invoice_id="inv-1",
                success_url="https://app.example.com/parent/payments?invoice=paid",
                cancel_url="https://app.example.com/parent/payments?invoice=cancelled",
            )

    assert stripe.invoice_checkout_calls == []
    # 409 preserved, but now with a code the parent app can map (issue #426).
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "Billing.InvoicePayLinkUnavailable"


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
            "enrollments": _FakeCollection([_enrollment_doc("enroll-a", status="active")]),
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
@pytest.mark.parametrize("status", ["paused", "cancelled", "withdrawn"])
async def test_parent_single_invoice_payment_ignores_enroll_autopay_for_inactive_enrollment(
    allow_app_origin, status: str
) -> None:
    """Issue #651: the final invoice of a cancelled/paused/withdrawn enrollment
    is still payable, but the opt-in flag must not re-enrol it in autopay.
    The payment goes through as a plain one-time payment."""
    stripe = _InvoiceCheckoutStripe()
    db = _FakeDb(
        {
            "invoices": _FakeCollection(
                [_invoice_doc(invoice_id="inv-1", enrollment_id="enroll-a")]
            ),
            "enrollments": _FakeCollection([_enrollment_doc("enroll-a", status=status)]),
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
            enroll_autopay=True,
        )

    assert result is not None
    call = stripe.invoice_checkout_calls[0]
    assert "save_payment_method_for_autopay" not in call
    assert "autopay_enrollment_ids" not in call
    # Issue #635: EVERY checkout return carries a checkout_session_id so the
    # parent app can poll settlement, opted in or not.
    assert call["success_url"] == (
        "https://app.example.com/parent/payments?invoice=paid"
        "&checkout_session_id={CHECKOUT_SESSION_ID}"
    )


@pytest.mark.asyncio
async def test_parent_single_invoice_payment_ignores_enroll_autopay_for_missing_enrollment(
    allow_app_origin,
) -> None:
    stripe = _InvoiceCheckoutStripe()
    db = _FakeDb(
        {
            "invoices": _FakeCollection(
                [_invoice_doc(invoice_id="inv-1", enrollment_id="enroll-gone")]
            ),
            "enrollments": _FakeCollection([]),
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

    assert "save_payment_method_for_autopay" not in stripe.invoice_checkout_calls[0]


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
            # Issue #651: only ACTIVE enrollments are placed on autopay.
            "enrollments": _FakeCollection(
                [_enrollment_doc("enroll-a"), _enrollment_doc("enroll-b")]
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
    # Issue #635: the balance path also always returns with a
    # checkout_session_id so the settlement poll can run without autopay.
    assert call["success_url"] == (
        "https://app.example.com/parent/payments?invoice=paid"
        "&checkout_session_id={CHECKOUT_SESSION_ID}"
    )


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
        with pytest.raises(InvoicePayLinkUnavailable, match="balance payment unavailable") as exc:
            await parent.start_balance_payment_for_parent(
                parent_id="parent-1",
                success_url="https://app.example.com/parent/payments?invoice=paid",
                cancel_url="https://app.example.com/parent/payments?invoice=cancelled",
            )

    assert stripe.invoice_checkout_calls == []
    assert exc.value.status_code == 409, "still a 409, now with a code"
    # No connected-account row at all: this academy never onboarded online
    # payments, so nothing is "broken" and no failure reason is attributed.
    assert exc.value.details.get("reason") is None


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
        with pytest.raises(InvoicePayLinkUnavailable, match="balance payment unavailable") as exc:
            await parent.start_balance_payment_for_parent(
                parent_id="parent-1",
                success_url="https://app.example.com/parent/payments?invoice=paid",
                cancel_url="https://app.example.com/parent/payments?invoice=cancelled",
            )

    assert stripe.invoice_checkout_calls[0]["connected_account_id"] == "acct_ready"
    # The parent portal's primary CTA blew up: loud, attributed, and recorded
    # once per invoice behind the link (issue #426).
    assert exc.value.details.get("reason") == "checkout_creation_failed"
    attempts = db["payment_attempts"].docs
    assert {a["invoice_id"] for a in attempts} == {"inv-1", "inv-2"}
    assert all(a["status"] == "checkout_mint_failed" for a in attempts)
    # Each invoice's OWN balance, not the 12_000 bundle total.
    assert {a["amount_cents"] for a in attempts} == {7_000, 5_000}


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
            "pending_cancellation_at": None,
            "hold_return_on": None,
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
@pytest.mark.parametrize("status", ["paused", "cancelled", "withdrawn"])
async def test_start_autopay_rejects_an_enrollment_that_is_not_active(
    allow_app_origin, status: str
) -> None:
    """Issue #651: after a pause/cancel/withdraw the lifecycle sync moves the
    enrollment's autopay to paused/disabled. The parent must not be able to
    re-enable it from the payments page; the route maps ValueError to the
    same 409 the non-payable-invoice path uses."""
    stripe = _AutopaySetupStripe()
    db = _FakeDb(
        {
            "enrollments": _FakeCollection([_enrollment_doc("enr-1", status=status)]),
            "students": _FakeCollection(
                [{"academy_id": "acad", "student_id": "student-1", "parent_id": "parent-1"}]
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

    with tenant_scope("acad"), pytest.raises(ValueError, match="enrollment is not active"):
        await parent.start_autopay_for_enrollment(
            parent_id="parent-1",
            enrollment_id="enr-1",
            success_url="https://app.example.com/parent/autopay?status=success",
            cancel_url="https://app.example.com/parent/autopay?status=cancelled",
        )

    # Fail-closed: no Stripe session minted, enrollment untouched.
    assert stripe.autopay_setup_checkouts == []
    assert db["enrollments"].updates == []


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
            "parent_profile": {
                "first_name": "Meera",
                "last_name": "Raghavan",
                "phone": "+1 555 0100",
            },
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
    # The stamped period is the session-local one (#541): the session carries
    # no timezone, so QuoteEnrollment defaults it to America/Chicago, and a
    # UTC label would disagree for the evening hours before local month-end.
    assert app_doc["zero_quote_period"] == now.astimezone(ZoneInfo("America/Chicago")).strftime(
        "%Y-%m"
    )


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

    with tenant_scope("acad"), pytest.raises(IncompleteApplication) as excinfo:
        await parent.start_checkout_for_application(
            parent_id="parent-1",
            application_id="app-1",
            success_url="https://app.example.com/parent/checkout/return?application_id=app-1",
            cancel_url="https://app.example.com/parent/onboarding",
        )

    # The wizard reads `missing` to send the parent back to the step that owns
    # the field, so the names are part of the contract, not just the message.
    assert excinfo.value.details["missing"] == [
        "date_of_birth",
        "emergency_contact_name",
        "emergency_contact_phone",
        "parent_phone",
    ]

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


def _checkout_ready_application(now: datetime, *, status: str, **extra: Any) -> dict[str, Any]:
    from datetime import timedelta

    doc: dict[str, Any] = {
        "application_id": "app-1",
        "academy_id": "acad",
        "parent_user_id": "parent-1",
        "parent_email": "parent@example.com",
        "status": status,
        "selected_session_id": "sess-1",
        "expires_at": now + timedelta(days=7),
        "created_at": now,
        "updated_at": now,
        "parent_profile": {
            "first_name": "Meera",
            "last_name": "Raghavan",
            "phone": "+1 555 0100",
        },
        "child_profile": {
            "first_name": "Aanya",
            "last_name": "Raghavan",
            "date_of_birth": "2015-04-02",
            "emergency_contact_name": "Vikram Raghavan",
            "emergency_contact_phone": "+1 555 0111",
        },
    }
    doc.update(extra)
    return doc


def _pinned_quote_clock() -> datetime:
    """The instant the checkout tests price against.

    Every quote is "what is LEFT of this month", so a test that prices against
    the wall clock changes shape as the month runs out: run it in the last
    half hour of a month and the last class has already elapsed, the quote
    falls to $0, and checkout takes the zero-amount branch that never calls
    Stripe at all. Pinning to the first instant of the month makes the whole
    month billable no matter when the suite runs.

    It is deliberately tied to the REAL current month rather than a fixed
    calendar date: the parent session CATALOG still uses the wall clock (it
    only lists sessions meeting in the next 30 days), so the session has to be
    live now as well as billable then.

    The month is the SESSION-LOCAL one (#541). Quotes are periodised in the
    session's timezone, so pinning to the first UTC instant of the month lands
    on the evening of the 31st in Chicago: the quote would cover the previous
    local month, none of this month's classes would be eligible, and every
    test here would silently fall into the $0 branch that never calls Stripe.
    """
    tz = ZoneInfo("America/Chicago")
    now = datetime.now(tz)
    return datetime(now.year, now.month, 1, tzinfo=tz)


def _billable_session(quote_now: datetime) -> dict[str, Any]:
    """A recurring session that meets every day of `quote_now`'s month.

    Priced against `_pinned_quote_clock`, every occurrence in the month is
    still ahead of the quote, so `final_amount_cents` is positive and checkout
    actually reaches Stripe. Running into next month keeps the session inside
    the catalog's rolling 30-day wall-clock window too.
    """
    from datetime import timedelta

    month_start = quote_now.date().replace(day=1)
    end_of_next_month = (month_start + timedelta(days=62)).replace(day=1) - timedelta(days=1)
    return {
        "session_id": "sess-1",
        "academy_id": "acad",
        "status": "scheduled",
        "title": "Beginner",
        "start_at": datetime.now(UTC) + timedelta(hours=3),
        "end_at": datetime.now(UTC) + timedelta(hours=4),
        "start_date": month_start.isoformat(),
        "end_date": end_of_next_month.isoformat(),
        "days_of_week": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "start_time": "17:00",
        "end_time": "18:00",
        "capacity": 8,
        "amount_cents": 6_000,
    }


def _pending_ledger_payment(payment_id: str, checkout_session_id: str) -> dict[str, Any]:
    """The pending Payment a live Checkout Session leaves behind."""
    now = datetime.now(UTC)
    return {
        "academy_id": "acad",
        "payment_id": payment_id,
        "parent_id": "parent-1",
        "session_id": "sess-1",
        "stripe_checkout_session_id": checkout_session_id,
        "amount_cents": 6_000,
        "currency": "usd",
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }


async def test_restarting_checkout_repoints_the_application_at_the_new_payment(
    allow_app_origin,
) -> None:
    """Cancel-then-pay-again must not orphan the paid registration.

    The application is already CHECKOUT_PENDING from the first (cancelled)
    session, so the transition does not change status — but the second Stripe
    session's payment_id is the only handle `checkout.session.completed` has
    back to the application (`get_by_payment_id`). If the application keeps the
    FIRST payment_id, the success handler finds nothing, the application never
    reaches PENDING_APPROVAL, and the first session's later `expired` webhook
    parks it in terminal CHECKOUT_EXPIRED — parent charged, registration lost."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["restart-checkout"]

    quote_now = _pinned_quote_clock()
    await db["onboarding_applications"].insert_one(
        _checkout_ready_application(
            datetime.now(UTC),
            status="CHECKOUT_PENDING",
            stripe_checkout_session_id="cs_first",
            payment_id="pay-first",
        )
    )
    await db["sessions"].insert_one(_billable_session(quote_now))
    await db["academy_connected_accounts"].insert_one(_connected_account_doc())
    await db["ledger_payments"].insert_one(_pending_ledger_payment("pay-first", "cs_first"))

    class _Stripe:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self.expired: list[str] = []

        async def create_checkout_session(self, **kwargs: Any) -> tuple[str, str]:
            self.calls.append(kwargs)
            return "cs_second", "https://checkout.stripe.test/second"

        async def expire_checkout_session(self, checkout_session_id: str) -> None:
            self.expired.append(checkout_session_id)

    stripe = _Stripe()
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
        clock=lambda: quote_now,
    )

    with tenant_scope("acad"):
        result = await parent.start_checkout_for_application(
            parent_id="parent-1",
            application_id="app-1",
            success_url="https://app.example.com/parent/checkout/return?application_id=app-1",
            cancel_url="https://app.example.com/parent/onboarding",
        )

    assert len(stripe.calls) == 1
    app_doc = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    assert app_doc["status"] == "CHECKOUT_PENDING"
    assert app_doc["payment_id"] == result.payment_id
    assert app_doc["payment_id"] != "pay-first"
    assert app_doc["stripe_checkout_session_id"] == "cs_second"
    # Only ONE payable session may survive: the first is expired at Stripe and
    # its pending Payment parked, so the parent cannot be charged twice for the
    # same enrollment by going back to the old tab.
    assert stripe.expired == ["cs_first"]
    first_payment = await db["ledger_payments"].find_one({"payment_id": "pay-first"})
    assert first_payment["status"] == "expired"


async def test_checkout_from_a_terminal_status_fails_before_any_side_effect(
    allow_app_origin,
) -> None:
    """CHECKOUT_EXPIRED has no outbound transition, so the transition at the
    END of start_checkout_for_application always raises. That refusal must
    happen BEFORE Stripe is called and before the Payment/quote writes, or
    every retry from an expired application leaves a dangling pending payment
    row and burns the quote snapshot."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["expired-checkout-retry"]

    quote_now = _pinned_quote_clock()
    await db["onboarding_applications"].insert_one(
        _checkout_ready_application(datetime.now(UTC), status="CHECKOUT_EXPIRED")
    )
    await db["sessions"].insert_one(_billable_session(quote_now))
    await db["academy_connected_accounts"].insert_one(_connected_account_doc())

    class _RefusingStripe:
        async def create_checkout_session(self, **kwargs: Any) -> tuple[str, str]:
            raise AssertionError("Stripe must not be reached for a non-restartable application")

    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=_RefusingStripe(),  # type: ignore[arg-type]
        academy_id="acad",
        clock=lambda: quote_now,
    )

    with tenant_scope("acad"), pytest.raises(ApplicationNotEditable) as excinfo:
        await parent.start_checkout_for_application(
            parent_id="parent-1",
            application_id="app-1",
            success_url="https://app.example.com/parent/checkout/return?application_id=app-1",
            cancel_url="https://app.example.com/parent/onboarding",
        )

    assert excinfo.value.details["from_status"] == "CHECKOUT_EXPIRED"
    assert await db["ledger_payments"].count_documents({}) == 0
    assert await db["payments"].count_documents({}) == 0
    # The quote is a side effect too: a snapshot minted here is consumed
    # before the transition raises, so the parent's next legitimate attempt
    # would price against a burnt snapshot.
    assert await db["billing_calculation_snapshots"].count_documents({}) == 0
    app_doc = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    assert app_doc["status"] == "CHECKOUT_EXPIRED"


async def test_retiring_an_already_paid_checkout_does_not_corrupt_state(
    allow_app_origin,
) -> None:
    """Stripe REJECTS expiring a session that is already complete.

    That is exactly the race a supersede has to survive, so the failure must be
    swallowed — and the succeeded Payment behind it must be left alone. Parking
    it as `expired` here would erase a real charge from the parent's history.
    """
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["retire-paid-checkout"]

    quote_now = _pinned_quote_clock()
    await db["onboarding_applications"].insert_one(
        _checkout_ready_application(
            datetime.now(UTC),
            status="CHECKOUT_PENDING",
            stripe_checkout_session_id="cs_first",
            payment_id="pay-first",
        )
    )
    await db["sessions"].insert_one(_billable_session(quote_now))
    await db["academy_connected_accounts"].insert_one(_connected_account_doc())
    paid = _pending_ledger_payment("pay-first", "cs_first")
    paid["status"] = "succeeded"
    await db["ledger_payments"].insert_one(paid)

    class _StripeThatRefusesExpiry:
        def __init__(self) -> None:
            self.expire_attempts: list[str] = []

        async def create_checkout_session(self, **_: Any) -> tuple[str, str]:
            return "cs_second", "https://checkout.stripe.test/second"

        async def expire_checkout_session(self, checkout_session_id: str) -> None:
            self.expire_attempts.append(checkout_session_id)
            raise StripeCheckoutSessionNotExpirable("You may only expire an open Checkout Session.")

    stripe = _StripeThatRefusesExpiry()
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
        clock=lambda: quote_now,
    )

    with tenant_scope("acad"):
        result = await parent.start_checkout_for_application(
            parent_id="parent-1",
            application_id="app-1",
            success_url="https://app.example.com/parent/checkout/return?application_id=app-1",
            cancel_url="https://app.example.com/parent/onboarding",
        )

    assert stripe.expire_attempts == ["cs_first"]
    # The restart still committed — the expiry failure must not unpick it.
    app_doc = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    assert app_doc["payment_id"] == result.payment_id
    # The already-succeeded payment is untouched.
    first_payment = await db["ledger_payments"].find_one({"payment_id": "pay-first"})
    assert first_payment["status"] == "succeeded"


# ---------------------------------------------------------------------------
# Issue #590: the mint-then-transition window
# ---------------------------------------------------------------------------


def _registered_student(student_id: str, **extra: Any) -> dict[str, Any]:
    """A students row that matches the checkout application's child by name."""
    doc: dict[str, Any] = {
        "academy_id": "acad",
        "student_id": student_id,
        "parent_id": "parent-1",
        "full_name": "Aanya Raghavan",
    }
    doc.update(extra)
    return doc


class _RecordingStripe:
    """Mints one session and records every expiry attempt against it."""

    def __init__(self, checkout_session_id: str = "cs_new") -> None:
        self.checkout_session_id = checkout_session_id
        self.created: list[dict[str, Any]] = []
        self.expired: list[str] = []

    async def create_checkout_session(self, **kwargs: Any) -> tuple[str, str]:
        self.created.append(kwargs)
        return self.checkout_session_id, "https://checkout.stripe.test/new"

    async def expire_checkout_session(self, checkout_session_id: str) -> None:
        self.expired.append(checkout_session_id)


async def test_entry_claim_moves_a_draft_application_to_checkout_pending(
    allow_app_origin,
) -> None:
    """The DRAFT -> CHECKOUT_PENDING claim must actually MOVE the status.

    Driven through the REAL `MongoApplicationRepository`, from DRAFT, because
    that is the only way this assertion means anything: the application-layer
    tests use a fake repo that reimplements the `new_status` branch itself,
    and the one real-adapter assertion of `status == "CHECKOUT_PENDING"` sits
    in a restart test whose application was ALREADY CHECKOUT_PENDING and so
    passes no matter what the adapter writes (issue #590).

    If the claim does not move the status the application stays DRAFT while a
    payable session exists against it — `checkout.session.completed` would then
    drive it CHECKOUT_PENDING -> ... from a status it never legally left.
    """
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["draft-entry-claim"]

    quote_now = _pinned_quote_clock()
    await db["onboarding_applications"].insert_one(
        _checkout_ready_application(datetime.now(UTC), status="DRAFT")
    )
    await db["sessions"].insert_one(_billable_session(quote_now))
    await db["academy_connected_accounts"].insert_one(_connected_account_doc())

    stripe = _RecordingStripe()
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
        clock=lambda: quote_now,
    )

    with tenant_scope("acad"):
        result = await parent.start_checkout_for_application(
            parent_id="parent-1",
            application_id="app-1",
            success_url="https://app.example.com/parent/checkout/return?application_id=app-1",
            cancel_url="https://app.example.com/parent/onboarding",
        )

    app_doc = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    assert app_doc["status"] == "CHECKOUT_PENDING"
    assert app_doc["stripe_checkout_session_id"] == "cs_new"
    assert app_doc["payment_id"] == result.payment_id
    # Nothing was retired: this attempt is the live one.
    assert stripe.expired == []


async def test_a_failed_transition_retires_the_session_it_just_minted(
    allow_app_origin,
) -> None:
    """A raise in the mint-then-transition window must not leave money on the table.

    The Stripe session and its pending Payment exist before the transition
    stamps them onto the application, and `_assert_child_not_enrolled` runs
    ahead of the CAS — so an ambiguous same-name registration raises with a
    payable session that no application references. Paying it would mark the
    payment succeeded and then silently no-op in `execute_for_payment`, which
    resolves by payment_id (issue #590).

    Two same-name rows, one dated and one not, are all the ambiguity guard
    needs; no enrollment is involved.
    """
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["orphaned-checkout"]

    quote_now = _pinned_quote_clock()
    await db["onboarding_applications"].insert_one(
        _checkout_ready_application(datetime.now(UTC), status="DRAFT")
    )
    await db["sessions"].insert_one(_billable_session(quote_now))
    await db["academy_connected_accounts"].insert_one(_connected_account_doc())
    await db["students"].insert_many(
        [
            _registered_student("stu-dated", date_of_birth="2015-04-02"),
            _registered_student("stu-undated"),
        ]
    )

    stripe = _RecordingStripe()
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
        clock=lambda: quote_now,
    )

    with tenant_scope("acad"), pytest.raises(ApplicationNotEditable) as excinfo:
        await parent.start_checkout_for_application(
            parent_id="parent-1",
            application_id="app-1",
            success_url="https://app.example.com/parent/checkout/return?application_id=app-1",
            cancel_url="https://app.example.com/parent/onboarding",
        )

    # The parent still gets the SAME error the wizard renders today; the
    # compensation must not swallow or replace it.
    assert "more than one possible child record" in str(excinfo.value)
    # The session really was minted, and really was retired again.
    assert len(stripe.created) == 1
    assert stripe.expired == ["cs_new"]
    payments = [doc async for doc in db["ledger_payments"].find({})]
    assert len(payments) == 1
    assert payments[0]["status"] == "expired"
    app_doc = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    assert app_doc["status"] == "DRAFT"
    assert app_doc.get("payment_id") is None


async def test_retiring_the_same_checkout_attempt_twice_is_harmless(
    allow_app_origin,
) -> None:
    """The lost-CAS path retires and THEN raises, so the compensation added for
    #590 runs retirement a SECOND time on the same ids. That must be a no-op:
    Stripe refuses to expire an already-expired session (swallowed), and the
    payment is no longer `pending` so it is left exactly as the first run wrote
    it. Pinned directly on the retirement object the composition wires."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    from backend.v2.composition.parent import _StripeCheckoutAttemptRetirement
    from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
        MongoPaymentRepository,
    )

    db = mongomock_motor.AsyncMongoMockClient()["double-retirement"]
    await db["ledger_payments"].insert_one(_pending_ledger_payment("pay-1", "cs_1"))

    class _StripeRefusingSecondExpiry:
        def __init__(self) -> None:
            self.expired: list[str] = []

        async def expire_checkout_session(self, checkout_session_id: str) -> None:
            self.expired.append(checkout_session_id)
            if len(self.expired) > 1:
                raise StripeCheckoutSessionNotExpirable(
                    "You may only expire an open Checkout Session."
                )

    stripe = _StripeRefusingSecondExpiry()
    first_now = datetime(2026, 1, 1, tzinfo=UTC)
    second_now = datetime(2026, 2, 2, tzinfo=UTC)
    clocks = iter((first_now, second_now, second_now))
    retirement = _StripeCheckoutAttemptRetirement(
        stripe=stripe,  # type: ignore[arg-type]
        payments=MongoPaymentRepository(db),  # type: ignore[arg-type]
        clock=lambda: next(clocks),
    )

    with tenant_scope("acad"):
        await retirement.retire_checkout_attempt(checkout_session_id="cs_1", payment_id="pay-1")
        # Second run must neither raise nor rewrite the parked payment.
        await retirement.retire_checkout_attempt(checkout_session_id="cs_1", payment_id="pay-1")

    assert stripe.expired == ["cs_1", "cs_1"]
    payment = await db["ledger_payments"].find_one({"payment_id": "pay-1"})
    assert payment["status"] == "expired"
    # mongomock hands datetimes back naive; only the instant matters here.
    assert payment["updated_at"].replace(tzinfo=UTC) == first_now


async def test_a_retirement_failure_after_the_restamp_commits_stays_recoverable(
    allow_app_origin, monkeypatch
) -> None:
    """The compensation may fire on a transition that DID commit. That is safe.

    `_restamp_checkout` retires the OLD attempt AFTER its CAS has already
    written the new ids, and that retirement is not exception-guarded (only
    the Stripe expire call is swallowed; `_payments.get`/`save` are not). So a
    Mongo error there raises out of `transition.execute` with the re-stamp
    already committed, and the composition's compensation then retires the ids
    the application now points at — expiring the session it just claimed.

    Accepted deliberately, for two reasons this test pins:
      * no money is at risk — `execute` raised, so the caller never receives
        `redirect_url` and the parent is never sent to that session;
      * it self-heals — the application is left CHECKOUT_PENDING, which is in
        `_CHECKOUT_STARTABLE_STATUSES`, so the very next start re-stamps it
        with a fresh session (issue #590).

    The alternative — leaving the compensation off this path — is strictly
    worse: it would have to distinguish "committed" from "did not commit",
    which the composition cannot see, and guessing wrong the other way leaks a
    payable orphan, which is the whole bug.
    """
    mongomock_motor = pytest.importorskip("mongomock_motor")
    from backend.v2.composition.parent import _CHECKOUT_STARTABLE_STATUSES
    from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
        MongoPaymentRepository,
    )

    db = mongomock_motor.AsyncMongoMockClient()["post-commit-retirement-failure"]

    quote_now = _pinned_quote_clock()
    await db["onboarding_applications"].insert_one(
        _checkout_ready_application(
            datetime.now(UTC),
            status="CHECKOUT_PENDING",
            stripe_checkout_session_id="cs_first",
            payment_id="pay-first",
        )
    )
    await db["sessions"].insert_one(_billable_session(quote_now))
    await db["academy_connected_accounts"].insert_one(_connected_account_doc())
    await db["ledger_payments"].insert_one(_pending_ledger_payment("pay-first", "cs_first"))

    # Break the OLD attempt's retirement only, at the exact unguarded call:
    # `_expire_session` swallows Stripe errors, so the reachable raise is the
    # payment read/write that follows it.
    real_get = MongoPaymentRepository.get

    async def _get(self: Any, payment_id: str) -> Any:
        if payment_id == "pay-first":
            raise RuntimeError("mongo unavailable while parking the superseded payment")
        return await real_get(self, payment_id)

    monkeypatch.setattr(MongoPaymentRepository, "get", _get)

    stripe = _RecordingStripe(checkout_session_id="cs_second")
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
        clock=lambda: quote_now,
    )

    with tenant_scope("acad"), pytest.raises(RuntimeError) as excinfo:
        await parent.start_checkout_for_application(
            parent_id="parent-1",
            application_id="app-1",
            success_url="https://app.example.com/parent/checkout/return?application_id=app-1",
            cancel_url="https://app.example.com/parent/onboarding",
        )

    # The original failure is what the caller sees — so no redirect_url, and
    # the parent is never pointed at cs_second.
    assert "mongo unavailable" in str(excinfo.value)

    # The re-stamp really did commit before the failure...
    app_doc = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    assert app_doc["stripe_checkout_session_id"] == "cs_second"
    # ...and the compensation therefore retired the ids the application now
    # holds: cs_second is expired at Stripe and its payment parked.
    assert stripe.expired == ["cs_first", "cs_second"]
    new_payment = await db["ledger_payments"].find_one({"payment_id": app_doc["payment_id"]})
    assert new_payment["status"] == "expired"
    # Nothing was left payable: the old attempt's session was expired too, and
    # its payment is the only pending row (the failure is why it stayed that
    # way — the `checkout.session.expired` webhook still parks it).
    first_payment = await db["ledger_payments"].find_one({"payment_id": "pay-first"})
    assert first_payment["status"] == "pending"

    # Self-healing: a retry is legal from here, and re-stamps.
    assert app_doc["status"] == "CHECKOUT_PENDING"
    assert app_doc["status"] in _CHECKOUT_STARTABLE_STATUSES


async def test_a_failing_compensation_does_not_mask_the_original_error(
    allow_app_origin, monkeypatch, caplog
) -> None:
    """The compensation is best-effort; the wizard's error is not.

    If retirement itself blows up, the parent must still get the actionable
    error that caused the abort — not a Mongo/Stripe error from the cleanup
    that ran afterwards. The failure still has to be logged, because what it
    leaks is a payable session (issue #590).
    """
    mongomock_motor = pytest.importorskip("mongomock_motor")
    from backend.v2.composition.parent import _StripeCheckoutAttemptRetirement

    db = mongomock_motor.AsyncMongoMockClient()["compensation-failure"]

    quote_now = _pinned_quote_clock()
    await db["onboarding_applications"].insert_one(
        _checkout_ready_application(datetime.now(UTC), status="DRAFT")
    )
    await db["sessions"].insert_one(_billable_session(quote_now))
    await db["academy_connected_accounts"].insert_one(_connected_account_doc())
    # Same ambiguity as the orphan test above: it raises AFTER the session is
    # minted and BEFORE the CAS, which is the window the compensation guards.
    await db["students"].insert_many(
        [
            _registered_student("stu-dated", date_of_birth="2015-04-02"),
            _registered_student("stu-undated"),
        ]
    )

    async def _explode(self: Any, **kwargs: Any) -> None:
        raise RuntimeError("stripe down while retiring the orphaned attempt")

    monkeypatch.setattr(_StripeCheckoutAttemptRetirement, "retire_checkout_attempt", _explode)

    stripe = _RecordingStripe()
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
        clock=lambda: quote_now,
    )

    with (
        caplog.at_level(logging.ERROR, logger="backend.v2.composition.parent"),
        tenant_scope("acad"),
        pytest.raises(ApplicationNotEditable) as excinfo,
    ):
        await parent.start_checkout_for_application(
            parent_id="parent-1",
            application_id="app-1",
            success_url="https://app.example.com/parent/checkout/return?application_id=app-1",
            cancel_url="https://app.example.com/parent/onboarding",
        )

    # The ORIGINAL error, not the compensation's RuntimeError.
    assert "more than one possible child record" in str(excinfo.value)
    # Swallowed, but never silent: the leaked session is named in the log.
    assert any(
        "checkout compensation failed" in record.getMessage() and "cs_new" in record.getMessage()
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# Issue #532: fail-closed guard for static-tenant wiring under multi-academy
# ---------------------------------------------------------------------------


def _guard_settings(*, saas_mode: bool, tenancy_mode: str, allow: bool = False):
    from types import SimpleNamespace

    return SimpleNamespace(
        saas_mode=saas_mode,
        tenancy_mode=tenancy_mode,
        allow_static_tenant_parent_wiring=allow,
    )


def test_guard_refuses_saas_multi_academy_by_default() -> None:
    from backend.v2.composition.parent import ensure_multi_academy_composable

    with pytest.raises(RuntimeError, match="boot-frozen academy_id"):
        ensure_multi_academy_composable(
            _guard_settings(saas_mode=True, tenancy_mode="multi_academy")
        )


def test_guard_allows_safe_and_acknowledged_modes() -> None:
    from backend.v2.composition.parent import ensure_multi_academy_composable

    # No saas_mode: every request resolves to default_academy_id — harmless.
    ensure_multi_academy_composable(_guard_settings(saas_mode=False, tenancy_mode="multi_academy"))
    # saas + single_academy: middleware refuses every tenant but primary.
    ensure_multi_academy_composable(_guard_settings(saas_mode=True, tenancy_mode="single_academy"))
    # Explicit operator acknowledgment (documented allowlist escape hatch).
    ensure_multi_academy_composable(
        _guard_settings(saas_mode=True, tenancy_mode="multi_academy", allow=True)
    )


def test_compose_parent_fails_closed_under_saas_multi_academy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The config flip that actually serves multiple tenants cannot silently
    ship with the remaining single-tenant parent wiring (issue #532)."""
    monkeypatch.setenv("V2_SAAS_MODE", "true")
    monkeypatch.delenv("V2_ALLOW_STATIC_TENANT_PARENT_WIRING", raising=False)
    monkeypatch.delenv("APP_TENANCY_MODE", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="boot-frozen academy_id"):
            compose_parent(
                _FakeDb(),
                outbox=object(),  # type: ignore[arg-type]
                idempotency_store=object(),  # type: ignore[arg-type]
                stripe=_PortalStripe(),  # type: ignore[arg-type]
                academy_id="acad",
            )
    finally:
        get_settings.cache_clear()


async def test_paid_checkout_raises_quote_expired_before_stripe_when_consume_refuses(
    allow_app_origin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """consume() returning None (TTL elapsed, or a concurrent request burnt
    the snapshot) must surface as a typed QuoteExpired — and it must do so
    BEFORE the Stripe Checkout Session is minted, or a session with the stale
    amount frozen into it exists with no consumable snapshot behind it
    (issue #530)."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["quote-expired-paid-checkout"]

    quote_now = _pinned_quote_clock()
    await db["onboarding_applications"].insert_one(
        _checkout_ready_application(datetime.now(UTC), status="DRAFT")
    )
    await db["sessions"].insert_one(_billable_session(quote_now))
    await db["academy_connected_accounts"].insert_one(_connected_account_doc())

    from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
        MongoPaymentRepository,
    )

    async def _refuse_consume(self: Any, snapshot_id: str) -> None:
        return None

    monkeypatch.setattr(MongoPaymentRepository, "consume_quote_snapshot", _refuse_consume)

    class _Stripe:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def create_checkout_session(self, **kwargs: Any) -> tuple[str, str]:
            self.calls.append(kwargs)
            return "cs_should_not_exist", "https://checkout.stripe.test/should-not-exist"

    stripe = _Stripe()
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
        clock=lambda: quote_now,
    )

    with tenant_scope("acad"), pytest.raises(QuoteExpired):
        await parent.start_checkout_for_application(
            parent_id="parent-1",
            application_id="app-1",
            success_url="https://app.example.com/parent/checkout/return?application_id=app-1",
            cancel_url="https://app.example.com/parent/onboarding",
        )

    # Consume runs BEFORE the Stripe call: no session may exist.
    assert stripe.calls == []
    app_doc = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    assert app_doc["status"] == "DRAFT"
    # And no pending Payment row was minted either.
    assert await db["ledger_payments"].find_one({}) is None


async def test_zero_amount_checkout_raises_quote_expired_when_consume_refuses(
    allow_app_origin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The $0 path must equally honor a refused consume: the application must
    not sail on to PENDING_APPROVAL against a snapshot the audit trail says is
    EXPIRED (issue #530)."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["quote-expired-zero-checkout"]

    now = datetime.now(UTC)
    from datetime import timedelta

    app_doc_seed = _checkout_ready_application(now, status="DRAFT")
    await db["onboarding_applications"].insert_one(app_doc_seed)
    # Only class starts inside the same-day cutoff → 0 billable classes → $0.
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

    from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
        MongoPaymentRepository,
    )

    async def _refuse_consume(self: Any, snapshot_id: str) -> None:
        return None

    monkeypatch.setattr(MongoPaymentRepository, "consume_quote_snapshot", _refuse_consume)

    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=object(),  # type: ignore[arg-type]
        academy_id="acad",
    )

    with tenant_scope("acad"), pytest.raises(QuoteExpired):
        await parent.start_checkout_for_application(
            parent_id="parent-1",
            application_id="app-1",
            success_url="https://app.example.com/parent/checkout/return?application_id=app-1",
            cancel_url="https://app.example.com/parent/onboarding",
        )

    app_doc = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    assert app_doc["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Issue #731 — the quote the review step displayed is the quote that is charged
# ---------------------------------------------------------------------------


async def test_checkout_charges_the_snapshot_the_review_step_displayed(
    allow_app_origin,
) -> None:
    """The parent pays the figure they read, not a re-quote of it (#731).

    The review step quotes once and shows that snapshot's amount, class count
    and expiry. Checkout used to throw that snapshot away and quote again, so
    anything that legitimately moved the price in between — a class crossing
    the two-hour cutoff, an admin repricing or cancelling a date — charged the
    parent an amount they had never seen, while the displayed snapshot stayed
    OPEN forever because nothing ever consumed it.
    """
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["displayed-quote-checkout"]

    quote_now = _pinned_quote_clock()
    await db["onboarding_applications"].insert_one(
        _checkout_ready_application(datetime.now(UTC), status="DRAFT")
    )
    await db["sessions"].insert_one(_billable_session(quote_now))
    await db["academy_connected_accounts"].insert_one(_connected_account_doc())

    class _Stripe:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def create_checkout_session(self, **kwargs: Any) -> tuple[str, str]:
            self.calls.append(kwargs)
            return "cs_displayed", "https://checkout.stripe.test/displayed"

    stripe = _Stripe()
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
        clock=lambda: quote_now,
    )

    with tenant_scope("acad"):
        displayed = await parent.quote_enrollment(parent_id="parent-1", session_id="sess-1")
        # The price moved while the parent was reading the review step: a
        # fresh quote at checkout time would now be twice the displayed one.
        await db["sessions"].update_one(
            {"session_id": "sess-1"}, {"$set": {"amount_cents": 12_000}}
        )
        result = await parent.start_checkout_for_application(
            parent_id="parent-1",
            application_id="app-1",
            success_url="https://app.example.com/parent/checkout/return?application_id=app-1",
            cancel_url="https://app.example.com/parent/onboarding",
            snapshot_id=displayed.snapshot_id,
        )

    assert displayed.final_amount_cents > 0
    assert len(stripe.calls) == 1
    # The DISPLAYED figure, not what a re-quote would have said.
    assert stripe.calls[0]["amount_cents"] == displayed.final_amount_cents
    assert stripe.calls[0]["metadata"]["calculation_snapshot_id"] == displayed.snapshot_id
    payment = await db["ledger_payments"].find_one({"payment_id": result.payment_id})
    assert payment["amount_cents"] == displayed.final_amount_cents
    # Exactly one snapshot exists — the displayed one — and it is CONSUMED.
    # No second snapshot was minted behind the parent's back, and the one they
    # read is no longer an eternally-OPEN row.
    snapshots = [doc async for doc in db["billing_calculation_snapshots"].find({})]
    assert [(doc["snapshot_id"], doc["status"]) for doc in snapshots] == [
        (displayed.snapshot_id, "CONSUMED")
    ]


async def test_checkout_refuses_a_stale_displayed_snapshot_instead_of_charging_a_fresh_one(
    allow_app_origin,
) -> None:
    """A snapshot that cannot be consumed must stop checkout, not re-quote it.

    Expired, already burnt, or simply not this parent's quote for this session:
    every case has to surface as QuoteExpired so the wizard re-quotes and shows
    the parent the new amount, instead of silently charging a figure the review
    step never rendered (#731).
    """
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["stale-displayed-quote-checkout"]

    quote_now = _pinned_quote_clock()
    await db["onboarding_applications"].insert_one(
        _checkout_ready_application(datetime.now(UTC), status="DRAFT")
    )
    await db["sessions"].insert_one(_billable_session(quote_now))
    await db["academy_connected_accounts"].insert_one(_connected_account_doc())

    class _Stripe:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def create_checkout_session(self, **kwargs: Any) -> tuple[str, str]:
            self.calls.append(kwargs)
            return "cs_should_not_exist", "https://checkout.stripe.test/should-not-exist"

    stripe = _Stripe()
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
        clock=lambda: quote_now,
    )

    with tenant_scope("acad"), pytest.raises(QuoteExpired):
        await parent.start_checkout_for_application(
            parent_id="parent-1",
            application_id="app-1",
            success_url="https://app.example.com/parent/checkout/return?application_id=app-1",
            cancel_url="https://app.example.com/parent/onboarding",
            snapshot_id="snap-burnt-or-never-existed",
        )

    assert stripe.calls == []
    assert await db["ledger_payments"].find_one({}) is None
    app_doc = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    assert app_doc["status"] == "DRAFT"
    # And the refusal did not leave a replacement quote lying around OPEN: the
    # wizard re-quotes for itself, so the snapshot it renders next is the one
    # the next attempt consumes.
    assert await db["billing_calculation_snapshots"].find_one({}) is None


async def test_a_parent_cannot_choose_the_billing_start_that_prices_their_quote(
    allow_app_origin,
) -> None:
    """No client lever on ``billing_start_at`` — checkout charges this quote.

    Since checkout consumes the snapshot the review step minted, anything a
    parent can push ``billing_start_at`` forward with prices their own first
    month: every class before the chosen start is dropped as
    ``BEFORE_BILLING_START``, so a start date late in the month mints a
    near-zero OPEN snapshot for their real session, and checkout would then
    charge that figure while the enrollment went ahead at full value. The
    parent quote path therefore takes no start date at all — it prices from
    the server clock, the same instant checkout falls back to, so a
    review-step quote can never come in under what the server would charge on
    its own.
    """
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-quote-start-date"]

    quote_now = _pinned_quote_clock()
    await db["sessions"].insert_one(_billable_session(quote_now))
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=object(),  # type: ignore[arg-type]
        academy_id="acad",
        clock=lambda: quote_now,
    )

    # The lever does not exist on the use case...
    assert "start_date" not in inspect.signature(parent.quote_enrollment).parameters
    with pytest.raises(TypeError):
        with tenant_scope("acad"):
            await parent.quote_enrollment(
                parent_id="parent-1",
                session_id="sess-1",
                start_date="2999-01-01",  # type: ignore[call-arg]
            )

    # ...nor on the wire: the request model drops the field, so an old bundle
    # that still posts it is quoted from the server clock like everyone else.
    request = EnrollmentQuoteRequest.model_validate(
        {"session_id": "sess-1", "start_date": "2999-01-01"}
    )
    assert not hasattr(request, "start_date")

    with tenant_scope("acad"):
        quote = await parent.quote_enrollment(parent_id="parent-1", session_id="sess-1")

    # Priced for the whole month ahead of the server clock, not for a sliver
    # of it chosen by the caller.
    assert quote.final_amount_cents > 0
    assert "BEFORE_BILLING_START" not in quote.excluded_occurrences.values()


# ---------------------------------------------------------------------------
# Issue #549 — the two residual races left open by #499 / #590
# ---------------------------------------------------------------------------


async def test_a_restamp_keeps_the_superseded_payment_findable_for_a_late_webhook(
    allow_app_origin,
) -> None:
    """A re-stamp must not orphan a paid-but-not-yet-webhooked application.

    The parent completes payment on the FIRST tab; Stripe accepts the charge but
    `checkout.session.completed` has not landed yet. A start from the second tab
    wins the re-stamp CAS and moves `payment_id` to the new attempt.

    `PaymentSucceeded` resolves the application through `get_by_payment_id` and
    nothing else, so before #549 that late webhook found NOTHING: the parent was
    charged and the application sat in CHECKOUT_PENDING forever, with
    `execute_for_payment` returning None and no alert anywhere.

    Driven through the REAL `MongoApplicationRepository`, because the archive is
    an adapter-level guarantee: it has to be written in the SAME atomic update
    as the overwrite it compensates for.
    """
    mongomock_motor = pytest.importorskip("mongomock_motor")
    from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
        TransitionApplication,
    )
    from backend.v2.contexts.onboarding.infrastructure.mongo_application_repo import (
        MongoApplicationRepository,
    )

    db = mongomock_motor.AsyncMongoMockClient()["restamp-late-webhook"]

    quote_now = _pinned_quote_clock()
    await db["onboarding_applications"].insert_one(
        _checkout_ready_application(
            datetime.now(UTC),
            status="CHECKOUT_PENDING",
            stripe_checkout_session_id="cs_first",
            payment_id="pay-first",
        )
    )
    await db["sessions"].insert_one(_billable_session(quote_now))
    await db["academy_connected_accounts"].insert_one(_connected_account_doc())
    await db["ledger_payments"].insert_one(_pending_ledger_payment("pay-first", "cs_first"))

    stripe = _RecordingStripe(checkout_session_id="cs_second")
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
        clock=lambda: quote_now,
    )

    with tenant_scope("acad"):
        result = await parent.start_checkout_for_application(
            parent_id="parent-1",
            application_id="app-1",
            success_url="https://app.example.com/parent/checkout/return?application_id=app-1",
            cancel_url="https://app.example.com/parent/onboarding",
        )

        # The re-stamp happened: the application now points at the second attempt.
        app_doc = await db["onboarding_applications"].find_one({"application_id": "app-1"})
        assert app_doc["payment_id"] == result.payment_id
        assert app_doc["payment_id"] != "pay-first"

        repo = MongoApplicationRepository(db)
        # ...and the id it replaced is still a valid handle back to it — through
        # the ARCHIVE lookup, which only the advance path may use. The live
        # lookup must NOT answer for it, or a stale expiry/capacity event for
        # the replaced attempt would terminate the live one (#549).
        assert await repo.get_by_payment_id("pay-first") is None
        found = await repo.get_by_superseded_payment_id("pay-first")
        assert found is not None
        assert found.application_id == "app-1"
        assert "pay-first" in found.superseded_payment_ids

        # The late `checkout.session.completed` for the FIRST session therefore
        # still advances the registration instead of vanishing.
        updated = await TransitionApplication(apps=repo).execute_for_payment(
            "pay-first", "PENDING_APPROVAL"
        )

    assert updated.status == "PENDING_APPROVAL"
    app_doc = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    assert app_doc["status"] == "PENDING_APPROVAL"


async def test_a_transient_stripe_failure_parks_the_session_for_reconciliation(
    allow_app_origin, caplog
) -> None:
    """A network blip must not leave a superseded session silently payable.

    `expire_checkout_session` used to turn EVERY StripeError into a bare
    ValueError, so `_expire_session` could not tell "already complete or
    expired" (benign — the parent paid on the old tab) from "we never reached
    Stripe" (the session is still open and payable). Both were logged at INFO
    and forgotten (#549).

    Injects a REAL `stripe.APIConnectionError`, not a stand-in ValueError.
    """
    mongomock_motor = pytest.importorskip("mongomock_motor")
    stripe_lib = pytest.importorskip("stripe")
    from backend.v2.composition.parent import _StripeCheckoutAttemptRetirement
    from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
        MongoPaymentRepository,
    )
    from backend.v2.contexts.billing.infrastructure.mongo_unretired_checkout_repo import (
        MongoUnretiredCheckoutSessionRepository,
    )

    db = mongomock_motor.AsyncMongoMockClient()["transient-retirement"]
    await db["ledger_payments"].insert_one(_pending_ledger_payment("pay-1", "cs_1"))

    class _UnreachableStripe:
        async def expire_checkout_session(self, checkout_session_id: str) -> None:
            raise stripe_lib.APIConnectionError(
                "Unexpected error communicating with Stripe: connection reset"
            )

    now = datetime(2026, 3, 4, tzinfo=UTC)
    retirement = _StripeCheckoutAttemptRetirement(
        stripe=_UnreachableStripe(),  # type: ignore[arg-type]
        payments=MongoPaymentRepository(db),  # type: ignore[arg-type]
        clock=lambda: now,
        unretired=MongoUnretiredCheckoutSessionRepository(db),
    )

    with tenant_scope("acad"), caplog.at_level(logging.INFO):
        await retirement.retire_checkout_attempt(checkout_session_id="cs_1", payment_id="pay-1")

    # The un-retired session is on a worklist a reconciliation pass can read.
    parked = await db["unretired_checkout_sessions"].find_one({"checkout_session_id": "cs_1"})
    assert parked is not None
    assert parked["payment_id"] == "pay-1"
    assert parked["reason"] == "APIConnectionError"
    assert parked["attempts"] == 1

    # ...and it is NOT reported as if it were fine.
    retirement_records = [
        record for record in caplog.records if "checkout retirement" in record.getMessage()
    ]
    assert retirement_records, "the failure must be logged"
    assert all(record.levelno >= logging.WARNING for record in retirement_records)


async def test_an_already_terminal_stripe_session_is_not_parked_for_reconciliation(
    allow_app_origin,
) -> None:
    """The legitimate swallow must stay a swallow.

    Stripe refusing to expire an already complete/expired session is the race a
    supersede exists to survive — nothing is left payable, so it must NOT land
    on the reconciliation worklist or the worklist becomes noise nobody reads.
    """
    mongomock_motor = pytest.importorskip("mongomock_motor")
    from backend.v2.composition.parent import _StripeCheckoutAttemptRetirement
    from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
        MongoPaymentRepository,
    )
    from backend.v2.contexts.billing.infrastructure.mongo_unretired_checkout_repo import (
        MongoUnretiredCheckoutSessionRepository,
    )

    db = mongomock_motor.AsyncMongoMockClient()["terminal-retirement"]
    await db["ledger_payments"].insert_one(_pending_ledger_payment("pay-1", "cs_1"))

    class _AlreadyCompleteStripe:
        async def expire_checkout_session(self, checkout_session_id: str) -> None:
            raise StripeCheckoutSessionNotExpirable("You may only expire an open Checkout Session.")

    retirement = _StripeCheckoutAttemptRetirement(
        stripe=_AlreadyCompleteStripe(),  # type: ignore[arg-type]
        payments=MongoPaymentRepository(db),  # type: ignore[arg-type]
        clock=lambda: datetime(2026, 3, 4, tzinfo=UTC),
        unretired=MongoUnretiredCheckoutSessionRepository(db),
    )

    with tenant_scope("acad"):
        await retirement.retire_checkout_attempt(checkout_session_id="cs_1", payment_id="pay-1")

    assert await db["unretired_checkout_sessions"].count_documents({}) == 0


async def test_a_later_successful_retirement_clears_the_worklist_entry(
    allow_app_origin,
) -> None:
    """The worklist is a live list of payable orphans, not an append-only log.

    A session that failed transiently and was retired on the next attempt must
    come off it, or every reconciliation run re-investigates a solved problem.
    """
    mongomock_motor = pytest.importorskip("mongomock_motor")
    stripe_lib = pytest.importorskip("stripe")
    from backend.v2.composition.parent import _StripeCheckoutAttemptRetirement
    from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
        MongoPaymentRepository,
    )
    from backend.v2.contexts.billing.infrastructure.mongo_unretired_checkout_repo import (
        MongoUnretiredCheckoutSessionRepository,
    )

    db = mongomock_motor.AsyncMongoMockClient()["retirement-recovery"]
    await db["ledger_payments"].insert_one(_pending_ledger_payment("pay-1", "cs_1"))

    class _FlakyStripe:
        def __init__(self) -> None:
            self.attempts = 0

        async def expire_checkout_session(self, checkout_session_id: str) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise stripe_lib.APIConnectionError("connection reset")

    retirement = _StripeCheckoutAttemptRetirement(
        stripe=_FlakyStripe(),  # type: ignore[arg-type]
        payments=MongoPaymentRepository(db),  # type: ignore[arg-type]
        clock=lambda: datetime(2026, 3, 4, tzinfo=UTC),
        unretired=MongoUnretiredCheckoutSessionRepository(db),
    )

    with tenant_scope("acad"):
        await retirement.retire_checkout_attempt(checkout_session_id="cs_1", payment_id="pay-1")
        assert await db["unretired_checkout_sessions"].count_documents({}) == 1
        await retirement.retire_checkout_attempt(checkout_session_id="cs_1", payment_id="pay-1")

    assert await db["unretired_checkout_sessions"].count_documents({}) == 0


async def test_a_rotated_api_key_parks_the_session_instead_of_calling_it_terminal(
    allow_app_origin,
) -> None:
    """End-to-end through the REAL gateway: a 401 must not read as "already paid".

    This is the whole worklist claim under the failure ops are most likely to
    cause. Classifying by "is this transient?" and defaulting to terminal wrote
    ZERO rows and logged INFO "already terminal at Stripe" for a session that
    was still wide open and payable — the exact #549 swallow, with the
    monitoring signal reading healthy.
    """
    mongomock_motor = pytest.importorskip("mongomock_motor")
    stripe_lib = pytest.importorskip("stripe")
    from backend.v2.composition.parent import _StripeCheckoutAttemptRetirement
    from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
        MongoPaymentRepository,
    )
    from backend.v2.contexts.billing.infrastructure.mongo_unretired_checkout_repo import (
        MongoUnretiredCheckoutSessionRepository,
    )
    from backend.v2.contexts.billing.infrastructure.stripe_gateway import RealStripeGateway

    db = mongomock_motor.AsyncMongoMockClient()["retirement-401"]
    await db["ledger_payments"].insert_one(_pending_ledger_payment("pay-1", "cs_1"))

    gateway = RealStripeGateway(api_key="sk_test_549", webhook_secret="whsec_549")

    def _expire(_session_id: str, **_kwargs: object) -> None:
        raise stripe_lib.AuthenticationError("Invalid API Key provided", http_status=401)

    gateway._stripe.checkout.Session.expire = _expire  # type: ignore[attr-defined]

    retirement = _StripeCheckoutAttemptRetirement(
        stripe=gateway,
        payments=MongoPaymentRepository(db),  # type: ignore[arg-type]
        clock=lambda: datetime(2026, 3, 4, tzinfo=UTC),
        unretired=MongoUnretiredCheckoutSessionRepository(db),
    )

    with tenant_scope("acad"):
        await retirement.retire_checkout_attempt(checkout_session_id="cs_1", payment_id="pay-1")

    parked = await db["unretired_checkout_sessions"].find_one({"checkout_session_id": "cs_1"})
    assert parked is not None
    assert parked["payment_id"] == "pay-1"


# 8:15pm CDT on Aug 31 2027 — already 00:15 UTC on Sep 1. Deliberately a fixed
# calendar instant rather than one derived from the wall clock: the point of
# the test is the boundary, and it has to be the boundary on every run.
_MONTH_END_EVENING_CHICAGO = datetime(2027, 9, 1, 0, 15, tzinfo=UTC)


def _catalog_session_meeting_soon() -> dict[str, Any]:
    """A one-off session live in the parent catalog's rolling wall-clock window.

    The catalog still filters on `datetime.now(UTC)`, so the session has to
    meet in the next 30 days for real, even though the quote is priced against
    a pinned month-end instant. Its single class is nowhere near the pinned
    period, so the quote has zero eligible classes and takes the $0 branch.
    """
    from datetime import timedelta

    now = datetime.now(UTC)
    return {
        "session_id": "sess-1",
        "academy_id": "acad",
        "status": "scheduled",
        "title": "Beginner",
        "timezone": "America/Chicago",
        "start_at": now + timedelta(hours=3),
        "end_at": now + timedelta(hours=4),
        "capacity": 8,
        "amount_cents": 6_000,
    }


async def test_zero_quote_period_is_stamped_in_the_session_timezone(
    allow_app_origin,
) -> None:
    """The $0 skip period must be the LOCAL month, not the UTC one (#541).

    `zero_quote_period` is the only proration signal admin approval hands the
    monthly generator (it becomes `skip_periods` on the enrollment). It used to
    be re-derived from a fresh `now(UTC)`, so an 8:15pm Chicago checkout on
    Aug 31 stamped "2027-09" while the quote it came from covered local
    August — the generator then compares against its own period label and the
    skip lands on the wrong month, billing full tuition for the skipped one.
    """
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["zero-quote-period-tz"]

    await db["onboarding_applications"].insert_one(
        _checkout_ready_application(datetime.now(UTC), status="DRAFT")
    )
    await db["sessions"].insert_one(_catalog_session_meeting_soon())

    class _RefusingStripe:
        def __init__(self) -> None:
            self.checkout_calls: list[dict[str, Any]] = []

        async def create_checkout_session(self, **kwargs: Any) -> tuple[str, str]:
            self.checkout_calls.append(kwargs)
            return "cs_should_not_exist", "https://checkout.stripe.test/nope"

    stripe = _RefusingStripe()
    parent = compose_parent(
        db,  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        academy_id="acad",
        clock=lambda: _MONTH_END_EVENING_CHICAGO,
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
    app_doc = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    assert app_doc["status"] == "PENDING_APPROVAL"
    assert app_doc["zero_quote_period"] == "2027-08"


# ---------------------------------------------------------------------------
# Progress feed: parents see only notes a coach explicitly shared
# (coach phone slice 3 — note visibility)
# ---------------------------------------------------------------------------


async def test_parent_progress_feed_lists_only_shared_notes() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-progress"]
    await _seed_profile_fixture(db)
    await db["users"].insert_one(
        {"user_id": "coach-1", "academy_id": "acad", "display_name": "Coach One"}
    )
    await db["sessions"].insert_one({"academy_id": "acad", "session_id": "s-1", "title": "Juniors"})
    base = {
        "academy_id": "acad",
        "session_id": "s-1",
        "student_id": "stu-1",
        "coach_id": "coach-1",
    }
    await db["progress_notes"].insert_many(
        [
            {
                **base,
                "note_id": "shared",
                "body": "Shared with mum",
                "created_at": datetime(2026, 9, 3, tzinfo=UTC),
                "visibility": "shared",
            },
            {
                **base,
                "note_id": "private",
                "body": "Coaches only",
                "created_at": datetime(2026, 9, 4, tzinfo=UTC),
                "visibility": "private",
            },
            {
                # Pre-0167 document: no field at all, reads as private.
                **base,
                "note_id": "legacy",
                "body": "Old note",
                "created_at": datetime(2026, 9, 5, tzinfo=UTC),
            },
            {
                # Shared, but another family's child.
                **base,
                "student_id": "stu-other-parent",
                "note_id": "other-family",
                "body": "Not yours",
                "created_at": datetime(2026, 9, 5, tzinfo=UTC),
                "visibility": "shared",
            },
        ]
    )
    # Feedback rows are untouched by the visibility rule.
    await db["session_feedback"].insert_one(
        {
            **base,
            "feedback_id": "fb-1",
            "body": "Great session",
            "rating": 5,
            "created_at": datetime(2026, 9, 1, tzinfo=UTC),
        }
    )
    parent = await _compose_profile_parent(db)

    with tenant_scope("acad"):
        rows, total = await parent.list_progress_for_parent("parent-1")

    assert total == 2
    assert [(r["note_id"], r["note_type"]) for r in rows] == [
        ("shared", "progress_note"),
        ("fb-1", "feedback"),
    ]
    assert rows[0]["coach_name"] == "Coach One"
    assert rows[0]["session_title"] == "Juniors"
    assert "visibility" not in rows[0], "response shape is unchanged"


# --- GET /parent/home aggregator (kid-first Home, slice 4) ---------------------

_HOME_NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
_CHICAGO = ZoneInfo("America/Chicago")


def _home_student(student_id: str, full_name: str, *, legacy_link: bool = False) -> dict[str, Any]:
    """A student linked by ``parent_user_id`` (current) or ``parent_id`` (legacy).

    ``_parent_students`` matches either, so both shapes must reach Home — a
    legacy-shaped row silently dropping out is exactly the regression this
    covers.
    """
    doc: dict[str, Any] = {
        "academy_id": "acad",
        "student_id": student_id,
        "full_name": full_name,
        "status": "active",
    }
    doc["parent_id" if legacy_link else "parent_user_id"] = "parent-1"
    return doc


def _attendance_doc(
    attendance_id: str, student_id: str, status: str, marked_at: datetime
) -> dict[str, Any]:
    return {
        "academy_id": "acad",
        "attendance_id": attendance_id,
        "student_id": student_id,
        "session_id": "sess-1",
        "status": status,
        "marked_at": marked_at,
    }


async def _seed_home_db(db: Any) -> None:
    await db["academies"].insert_one(
        {"academy_id": "acad", "display_name": "BLNO", "timezone": "America/Chicago"}
    )
    await db["students"].insert_many(
        [
            _home_student("st-1", "Asha Rao"),
            # Legacy link shape — parent_id, not parent_user_id.
            _home_student("st-2", "Dev Rao", legacy_link=True),
        ]
    )

    # Attendance: 60 marked rows for st-1 inside the academy-local month (well
    # past list_attendance_for_parent's 50-row page), of which 40 are present.
    rows = [
        _attendance_doc(
            f"att-{i}",
            "st-1",
            "present" if i % 3 else "absent",
            datetime(2026, 9, 2, 15, 0, tzinfo=UTC) + timedelta(hours=i),
        )
        for i in range(60)
    ]
    # The boundary rows are deliberately ASYMMETRIC in count and in status, so
    # a UTC window and the academy window cannot produce the same numbers:
    #   academy (Chicago): 62 total / 41 present
    #   naive UTC:         61 total / 40 present
    #
    # 2026-09-01 00:30 UTC is 2026-08-31 19:30 in Chicago: LAST month on the
    # academy's clock, and this month under UTC. The academy answer wins (#541).
    # `absent` so a UTC window changes the present count too, not just totals.
    rows.append(
        _attendance_doc(
            "att-utc-boundary", "st-1", "absent", datetime(2026, 9, 1, 0, 30, tzinfo=UTC)
        )
    )
    # 2026-10-01 02:00 / 03:00 UTC are 2026-09-30 21:00 / 22:00 in Chicago:
    # still THIS month locally even though UTC has already rolled over. Two
    # rows against the boundary's one is what makes the totals differ.
    rows.append(
        _attendance_doc(
            "att-local-tail", "st-1", "present", datetime(2026, 10, 1, 2, 0, tzinfo=UTC)
        )
    )
    rows.append(
        _attendance_doc(
            "att-local-tail-2", "st-1", "absent", datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
        )
    )
    rows.append(
        _attendance_doc(
            "att-other-child", "st-2", "absent", datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
        )
    )
    await db["attendance"].insert_many(rows)

    await db["progress_notes"].insert_many(
        [
            {
                "academy_id": "acad",
                "note_id": "note-shared",
                "student_id": "st-1",
                "coach_id": "coach-1",
                "visibility": "shared",
                "body": "Great footwork today\nsecond line ignored",
                "created_at": datetime(2026, 9, 5, 15, 0, tzinfo=UTC),
            },
            {
                "academy_id": "acad",
                "note_id": "note-private",
                "student_id": "st-2",
                "coach_id": "coach-1",
                "visibility": "private",
                "body": "Parent must never see this",
                "created_at": datetime(2026, 9, 14, 15, 0, tzinfo=UTC),
            },
        ]
    )

    # st-1 skill update is NEWER than the shared note, so the skill wins.
    await db["skills"].insert_one(
        {
            "academy_id": "acad",
            "skill_id": "skill-1",
            "level_id": "lvl-1",
            "program_id": "prog-1",
            "sequence": 1,
            "name": "Backhand Lift",
            "created_at": _HOME_NOW,
            "updated_at": _HOME_NOW,
            "created_by": "coach-1",
        }
    )
    await db["student_skill_progress"].insert_one(
        {
            "academy_id": "acad",
            "skill_progress_id": "sp-1",
            "student_id": "st-1",
            "skill_id": "skill-1",
            "level_id": "lvl-1",
            "program_id": "prog-1",
            "status": "PASSED",
            "last_updated_at": datetime(2026, 9, 9, 15, 0, tzinfo=UTC),
            "last_updated_by": "coach-1",
        }
    )

    await db["invoices"].insert_many(
        [
            _home_invoice("inv-open", "open", 7_000, date(2026, 9, 20)),
            _home_invoice("inv-partial", "partially_paid", 3_000, date(2026, 9, 12)),
            _home_invoice("inv-paid", "paid", 0, date(2026, 9, 1)),
            _home_invoice("inv-void", "void", 9_900, date(2026, 9, 2)),
        ]
    )


def _home_invoice(
    invoice_id: str, status: str, balance_due_cents: int, due_date: date
) -> dict[str, Any]:
    doc = LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="acad",
        parent_id="parent-1",
        student_id="st-1",
        period="2026-09",
        status=status,  # type: ignore[arg-type]
        subtotal_cents=balance_due_cents,
        discount_cents=0,
        total_cents=balance_due_cents,
        balance_due_cents=balance_due_cents,
        currency="usd",
        due_date=due_date,
        created_at=_HOME_NOW,
        updated_at=_HOME_NOW,
    ).model_dump(mode="python")
    # Mongo has no `date` BSON type: the ledger repo stores due dates as UTC
    # midnight instants, so the fixture must too or the fake is more
    # permissive than the real store.
    doc["due_date"] = datetime.combine(due_date, dt_time.min, tzinfo=UTC)
    return doc


def _compose_home_parent(db: Any, *, now: datetime = _HOME_NOW) -> Any:
    return compose_parent(
        db,
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=_PortalStripe(),  # type: ignore[arg-type]
        academy_id="acad",
        clock=lambda: now,
    )


@pytest.mark.asyncio
async def test_parent_home_buckets_the_month_on_the_academy_clock() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-home-month"]
    await _seed_home_db(db)
    parent = _compose_home_parent(db)

    with tenant_scope("acad"):
        home = await parent.get_parent_home(parent_id="parent-1")

    assert home["timezone"] == "America/Chicago"
    assert home["month_label"] == "September"
    asha = home["children"][0]
    # 60 in-month rows (40 present) + the two Sep-30-local tails (one present);
    # the 19:30-local absent row on Aug 31 is excluded even though UTC calls it
    # September. A naive UTC window would answer 61 total / 40 present instead,
    # so these two numbers are what pins the bucketing to the academy clock.
    assert asha["attendance_this_month"]["total"] == 62
    assert asha["attendance_this_month"]["present"] == 41
    # Never truncated to a 50-row page.
    assert asha["attendance_this_month"]["total"] > 50


@pytest.mark.asyncio
async def test_parent_home_includes_legacy_linked_child_in_stable_order() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-home-children"]
    await _seed_home_db(db)
    parent = _compose_home_parent(db)

    with tenant_scope("acad"):
        home = await parent.get_parent_home(parent_id="parent-1")

    assert [child["student_id"] for child in home["children"]] == ["st-1", "st-2"]
    assert [child["full_name"] for child in home["children"]] == ["Asha Rao", "Dev Rao"]
    # No enrolments seeded, so nothing is upcoming for either child.
    assert all(child["next_session"] is None for child in home["children"])
    assert home["children"][1]["attendance_this_month"] == {"present": 0, "total": 1}


@pytest.mark.asyncio
async def test_parent_home_milestone_prefers_the_later_of_note_and_skill() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-home-milestone"]
    await _seed_home_db(db)
    parent = _compose_home_parent(db)

    with tenant_scope("acad"):
        home = await parent.get_parent_home(parent_id="parent-1")

    asha, dev = home["children"]
    assert asha["latest_milestone"] == {
        "kind": "skill",
        "label": "Backhand Lift",
        "at": datetime(2026, 9, 9, 15, 0, tzinfo=UTC),
    }
    # Dev's only note is private, so he has no milestone at all.
    assert dev["latest_milestone"] is None


@pytest.mark.asyncio
async def test_parent_home_milestone_falls_back_to_the_shared_note() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-home-note-wins"]
    await _seed_home_db(db)
    # Make the skill update OLDER than the shared note.
    await db["student_skill_progress"].update_one(
        {"skill_progress_id": "sp-1"},
        {"$set": {"last_updated_at": datetime(2026, 9, 1, 15, 0, tzinfo=UTC)}},
    )
    parent = _compose_home_parent(db)

    with tenant_scope("acad"):
        home = await parent.get_parent_home(parent_id="parent-1")

    assert home["children"][0]["latest_milestone"] == {
        "kind": "note",
        "label": "Great footwork today",
        "at": datetime(2026, 9, 5, 15, 0, tzinfo=UTC),
    }


@pytest.mark.asyncio
async def test_parent_home_milestone_survives_a_sibling_filling_the_progress_page() -> None:
    """The progress page is sliced across the WHOLE family, so a busy child can
    fill it end to end; the quiet sibling must still get their milestone."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-home-progress-page"]
    await _seed_home_db(db)
    # st-2's shared note is OLDER than every one of st-1's feedback rows.
    await db["progress_notes"].insert_one(
        {
            "academy_id": "acad",
            "note_id": "note-dev-shared",
            "student_id": "st-2",
            "coach_id": "coach-1",
            "visibility": "shared",
            "body": "Nice serve",
            "created_at": datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
        }
    )
    await db["session_feedback"].insert_many(
        [
            {
                "academy_id": "acad",
                "feedback_id": f"fb-{i}",
                "student_id": "st-1",
                "coach_id": "coach-1",
                "body": "Good session",
                "created_at": datetime(2026, 9, 3, 15, 0, tzinfo=UTC) + timedelta(minutes=i),
            }
            for i in range(120)
        ]
    )
    parent = _compose_home_parent(db)

    with tenant_scope("acad"):
        home = await parent.get_parent_home(parent_id="parent-1")

    dev = home["children"][1]
    assert dev["latest_milestone"] is not None
    assert dev["latest_milestone"]["label"] == "Nice serve"


@pytest.mark.asyncio
async def test_parent_home_balance_counts_partially_paid_and_drops_paid_and_void() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-home-balance"]
    await _seed_home_db(db)
    parent = _compose_home_parent(db)

    with tenant_scope("acad"):
        home = await parent.get_parent_home(parent_id="parent-1")

    assert home["balance"] == {
        "amount_due_cents": 10_000,
        "currency": "usd",
        "due_date": date(2026, 9, 12),
        "open_invoice_count": 2,
        "payment_failed": False,
    }


@pytest.mark.asyncio
async def test_parent_home_payment_failed_comes_from_the_autopay_attempt_projection() -> None:
    """A declined autopay attempt that never minted a payment row exists only
    on student_billing_enrollments — the payments heuristic alone would miss
    it (decision 6b)."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-home-failed"]
    await _seed_home_db(db)
    await db["enrollments"].insert_one(_enrollment_doc("enr-1", student_id="st-1"))
    await db["student_billing_enrollments"].insert_one(
        {
            "academy_id": "acad",
            "parent_id": "parent-1",
            "enrollment_id": "enr-1",
            "last_attempt_outcome": "declined",
        }
    )
    parent = _compose_home_parent(db)

    with tenant_scope("acad"):
        home = await parent.get_parent_home(parent_id="parent-1")

    assert home["balance"]["payment_failed"] is True


async def _seed_failed_ledger_payment(db: Any, *, invoice_id: str) -> None:
    """A failed card payment against ``invoice_id``, the way the payments
    history actually stores it: a ledger_payments row plus the allocation that
    links it to the invoice."""
    await db["ledger_payments"].insert_one(
        {
            "academy_id": "acad",
            "payment_id": "pay-failed",
            "parent_id": "parent-1",
            "amount_cents": 7_000,
            "currency": "usd",
            "status": "failed",
            "created_at": datetime(2026, 9, 10, 15, 0, tzinfo=UTC),
        }
    )
    await db["payment_allocations"].insert_one(
        {
            "academy_id": "acad",
            "payment_id": "pay-failed",
            "invoice_id": invoice_id,
            "amount_cents": 7_000,
        }
    )


@pytest.mark.asyncio
async def test_parent_home_payment_failed_comes_from_the_payments_history_too() -> None:
    """A manual/portal card decline mints a payment row but leaves
    ``last_attempt_outcome`` unset, so the autopay projection alone misses it.
    """
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-home-failed-payment"]
    await _seed_home_db(db)
    await db["enrollments"].insert_one(_enrollment_doc("enr-1", student_id="st-1"))
    await _seed_failed_ledger_payment(db, invoice_id="inv-open")
    parent = _compose_home_parent(db)

    with tenant_scope("acad"):
        home = await parent.get_parent_home(parent_id="parent-1")

    assert home["balance"]["payment_failed"] is True


@pytest.mark.asyncio
async def test_parent_home_ignores_a_failed_payment_whose_invoice_is_settled() -> None:
    """The parent already paid another way — the invoice is `paid`, so the old
    failure is history, not something needing attention."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-home-failed-settled"]
    await _seed_home_db(db)
    await db["enrollments"].insert_one(_enrollment_doc("enr-1", student_id="st-1"))
    await _seed_failed_ledger_payment(db, invoice_id="inv-paid")
    parent = _compose_home_parent(db)

    with tenant_scope("acad"):
        home = await parent.get_parent_home(parent_id="parent-1")

    assert home["balance"]["payment_failed"] is False


@pytest.mark.asyncio
async def test_parent_home_ignores_a_failed_payment_without_an_active_enrollment() -> None:
    """Ported gate: a family with nothing active is not chased about a past
    failure (findPaymentNeedingAttention in frontend/lib/parent-home.ts)."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-home-failed-inactive"]
    await _seed_home_db(db)
    await db["enrollments"].insert_one(
        _enrollment_doc("enr-1", status="cancelled", student_id="st-1")
    )
    await _seed_failed_ledger_payment(db, invoice_id="inv-open")
    parent = _compose_home_parent(db)

    with tenant_scope("acad"):
        home = await parent.get_parent_home(parent_id="parent-1")

    assert home["balance"]["payment_failed"] is False


@pytest.mark.asyncio
async def test_parent_home_balance_excludes_draft_invoices() -> None:
    """A draft invoice is not payable by any parent surface, so the banner must
    not offer a Pay button for it."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-home-draft"]
    await _seed_home_db(db)
    await db["invoices"].insert_one(_home_invoice("inv-draft", "draft", 12_000, date(2026, 9, 25)))
    parent = _compose_home_parent(db)

    with tenant_scope("acad"):
        home = await parent.get_parent_home(parent_id="parent-1")

    assert home["balance"]["amount_due_cents"] == 10_000
    assert home["balance"]["open_invoice_count"] == 2


@pytest.mark.asyncio
async def test_parent_home_with_no_children_is_empty_not_an_error() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-home-empty"]
    await db["academies"].insert_one({"academy_id": "acad", "timezone": "America/Chicago"})
    parent = _compose_home_parent(db)

    with tenant_scope("acad"):
        home = await parent.get_parent_home(parent_id="parent-1")

    assert home["children"] == []
    assert home["balance"]["amount_due_cents"] == 0
    assert home["balance"]["open_invoice_count"] == 0
    assert home["balance"]["payment_failed"] is False
    assert home["month_label"] == "September"


@pytest.mark.asyncio
async def test_parent_home_next_session_is_the_next_upcoming_occurrence() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-home-schedule"]
    await _seed_home_db(db)
    now = datetime.now(UTC).replace(microsecond=0)
    await _seed_home_schedule(db, now)
    parent = _compose_home_parent(db, now=now)

    with tenant_scope("acad"):
        home = await parent.get_parent_home(parent_id="parent-1")

    asha = home["children"][0]
    assert asha["next_session"] == {
        "occurrence_id": "occ-next",
        "session_id": "sess-1",
        "session_title": "Junior Badminton",
        "location": "Court 2",
        "start_at": now + timedelta(days=1),
        "end_at": now + timedelta(days=1, hours=1),
        # Always None today (decision 12) — kept for shape parity.
        "coach_name": None,
    }
    # st-2 has no enrollment, so no upcoming session.
    assert home["children"][1]["next_session"] is None


@pytest.mark.asyncio
async def test_parent_home_next_session_skips_a_cancelled_occurrence() -> None:
    """`list_for_session_between` is the one occurrence query that does not
    filter cancelled rows, so Home must skip them itself — otherwise a
    cancelled class is announced as the child's next session."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-home-cancelled"]
    await _seed_home_db(db)
    now = datetime.now(UTC).replace(microsecond=0)
    await _seed_home_schedule(db, now)
    await db["session_occurrences"].insert_one(
        {
            "academy_id": "acad",
            "occurrence_id": "occ-cancelled",
            "session_id": "sess-1",
            # Sooner than occ-next, so a naive "first upcoming" picks this one.
            "start_at": now + timedelta(hours=2),
            "end_at": now + timedelta(hours=3),
            "status": "cancelled",
            "scheduled_coach_id": "coach-1",
        }
    )
    parent = _compose_home_parent(db, now=now)

    with tenant_scope("acad"):
        home = await parent.get_parent_home(parent_id="parent-1")

    assert home["children"][0]["next_session"]["occurrence_id"] == "occ-next"


@pytest.mark.asyncio
async def test_parent_home_degrades_per_child_when_one_schedule_leg_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One child's fan-out leg blowing up must cost that child a next-session
    row, not the whole family a 200 (decision 11)."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-home-isolation"]
    await _seed_home_db(db)
    now = datetime.now(UTC).replace(microsecond=0)
    await _seed_home_schedule(db, now)
    parent = _compose_home_parent(db, now=now)

    original = GetChildSchedule.execute

    async def _flaky(self: Any, parent_id: str, student_id: str, **kwargs: Any) -> Any:
        if student_id == "st-1":
            raise RuntimeError("occurrence store is down")
        return await original(self, parent_id, student_id, **kwargs)

    monkeypatch.setattr(GetChildSchedule, "execute", _flaky)

    with tenant_scope("acad"):
        home = await parent.get_parent_home(parent_id="parent-1")

    assert home["children"][0]["student_id"] == "st-1"
    assert home["children"][0]["next_session"] is None
    # Everything else on the broken child's card is still there...
    assert home["children"][0]["attendance_this_month"]["total"] == 62
    assert home["children"][0]["latest_milestone"]["label"] == "Backhand Lift"
    # ...and the other card and the family balance are untouched.
    assert home["children"][1]["student_id"] == "st-2"
    assert home["children"][1]["next_session"] is None
    assert home["balance"]["amount_due_cents"] == 10_000


async def _seed_home_schedule(db: Any, now: datetime) -> None:
    """One active enrollment for st-1 with a past and a future occurrence."""
    await db["enrollments"].insert_one(
        _enrollment_doc("enr-1", student_id="st-1", session_id="sess-1")
    )
    await db["sessions"].insert_one(
        {
            "academy_id": "acad",
            "session_id": "sess-1",
            "title": "Junior Badminton",
            "location": "Court 2",
            "coach_id": "coach-1",
            "start_at": now,
            "end_at": now + timedelta(hours=1),
            "capacity": 12,
        }
    )
    await db["session_occurrences"].insert_many(
        [
            {
                "academy_id": "acad",
                "occurrence_id": "occ-earlier-today",
                "session_id": "sess-1",
                "start_at": now - timedelta(hours=3),
                "end_at": now - timedelta(hours=2),
                "status": "scheduled",
                "scheduled_coach_id": "coach-1",
            },
            {
                "academy_id": "acad",
                "occurrence_id": "occ-next",
                "session_id": "sess-1",
                "start_at": now + timedelta(days=1),
                "end_at": now + timedelta(days=1, hours=1),
                "status": "scheduled",
                "scheduled_coach_id": "coach-1",
            },
        ]
    )
