"""Parent composition launch-hardening checks."""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.composition.parent import compose_parent, compose_parent_webhook_handler
from backend.v2.contexts.billing.domain.errors import CheckoutCreationFailed
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

        with pytest.raises(CheckoutCreationFailed, match="missing stored stripe customer"):
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
