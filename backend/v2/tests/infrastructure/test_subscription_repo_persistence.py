"""MongoSubscriptionRepository persistence shape.

Regression: pending subscriptions (created at checkout-start, before Stripe
assigns a subscription id) were saved with stripe_subscription_id="". The
stripe_sub_unique partial index covers every string value including "", so
the second pending row in the collection raised DuplicateKeyError and every
"Start autopay" click 500'd in production.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from backend.v2.contexts.billing.domain.models import Subscription
from backend.v2.contexts.billing.infrastructure.mongo_subscription_repo import (
    MongoSubscriptionRepository,
)
from backend.v2.shared.tenancy import tenant_scope


class _FakeCollection:
    def __init__(self) -> None:
        self.update_calls: list[dict[str, Any]] = []

    async def update_one(self, filter_, update, upsert=False, session=None):
        self.update_calls.append({"filter": filter_, "update": update, "upsert": upsert})


class _FakeDb:
    def __init__(self) -> None:
        self.collections: dict[str, _FakeCollection] = {}

    def __getitem__(self, name: str) -> _FakeCollection:
        return self.collections.setdefault(name, _FakeCollection())


def _subscription(stripe_subscription_id: str) -> Subscription:
    now = datetime.now(UTC)
    return Subscription(
        subscription_id="sub-1",
        academy_id="acad",
        parent_id="p1",
        enrollment_id="enr-1",
        session_id="s1",
        stripe_subscription_id=stripe_subscription_id,
        status="incomplete",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_save_never_persists_empty_stripe_subscription_id() -> None:
    db = _FakeDb()
    repo = MongoSubscriptionRepository(db)  # type: ignore[arg-type]
    with tenant_scope("acad"):
        await repo.save(_subscription(""))

    call = db["subscriptions"].update_calls[0]
    set_doc = call["update"]["$set"]
    assert "stripe_subscription_id" not in set_doc
    assert call["update"].get("$unset") == {"stripe_subscription_id": ""}
    assert call["upsert"] is True


@pytest.mark.asyncio
async def test_save_persists_real_stripe_subscription_id() -> None:
    db = _FakeDb()
    repo = MongoSubscriptionRepository(db)  # type: ignore[arg-type]
    with tenant_scope("acad"):
        await repo.save(_subscription("sub_live_1"))

    call = db["subscriptions"].update_calls[0]
    assert call["update"]["$set"]["stripe_subscription_id"] == "sub_live_1"
    assert "$unset" not in call["update"]


def test_to_domain_tolerates_missing_stripe_subscription_id() -> None:
    now = datetime.now(UTC)
    doc = {
        "subscription_id": "sub-1",
        "academy_id": "acad",
        "parent_id": "p1",
        "created_at": now,
        "updated_at": now,
    }
    subscription = MongoSubscriptionRepository._to_domain(doc)
    assert subscription.stripe_subscription_id == ""
