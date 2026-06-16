"""Parent composition launch-hardening checks."""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.composition.parent import compose_parent, compose_parent_webhook_handler
from backend.v2.contexts.billing.domain.errors import CheckoutCreationFailed


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []
        self.updates: list[dict[str, Any]] = []

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if _matches(doc, query):
                return doc
        return None

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> None:
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
        self.email_lookup_calls: list[str] = []
        self.portal_calls: list[dict[str, Any]] = []

    async def find_customer_id_by_email(self, email: str) -> str | None:
        self.email_lookup_calls.append(email)
        raise AssertionError("portal lookup must not search Stripe customers globally by email")

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
async def test_billing_portal_does_not_fall_back_to_global_email_customer_lookup() -> None:
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

    assert stripe.email_lookup_calls == []
    assert stripe.portal_calls == [
        {
            "parent_id": "parent-1",
            "return_url": "https://app.example.com/parent/payments",
            "stripe_customer_id": None,
        }
    ]
