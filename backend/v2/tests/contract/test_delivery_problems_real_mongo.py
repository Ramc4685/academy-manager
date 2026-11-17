"""Delivery-problems reads on a real mongod (L11 item 3): failed sends stay in
the request academy and exclude send-time gate refusals, and the suppression
lookup returns only the addresses asked for, never the rest of the global list."""

from __future__ import annotations

from backend.v2.contexts.communications.application.ports import ResolvedRecipient
from backend.v2.contexts.communications.domain.email_suppression import SuppressionReason
from backend.v2.contexts.communications.domain.models import Delivery
from backend.v2.contexts.communications.infrastructure.mongo_delivery_repo import (
    MongoDeliveryRepository,
)
from backend.v2.contexts.communications.infrastructure.mongo_suppression_repo import (
    MongoSuppressionRepository,
)
from backend.v2.shared.tenancy import tenant_scope


def _failed(academy: str, delivery_id: str, reason: str) -> Delivery:
    return Delivery.queued(
        delivery_id=delivery_id,
        academy_id=academy,
        campaign_id="c",
        recipient=ResolvedRecipient(user_id="u", email="u@example.test"),
    ).mark_failed(reason=reason)


async def test_failed_deliveries_stay_in_the_academy_and_skip_suppressions(real_db) -> None:
    repo = MongoDeliveryRepository(real_db)
    with tenant_scope("acad-a"):
        await repo.save_many(
            [
                _failed("acad-a", "d-a", "provider 422"),
                _failed("acad-a", "d-gate", "suppressed:complaint"),
                _failed("acad-a", "d-unsub", "unsubscribed:campaigns"),
            ]
        )
    with tenant_scope("acad-b"):
        await repo.save_many([_failed("acad-b", "d-b", "provider 422")])
    with tenant_scope("acad-a"):
        failed = await repo.list_failed(limit=10)
    # Suppression refusals are the shared list's; an unsubscribe is the academy's own.
    assert sorted(d.delivery_id for d in failed) == ["d-a", "d-unsub"]


async def test_suppression_lookup_returns_only_the_addresses_asked_for(real_db) -> None:
    repo = MongoSuppressionRepository(real_db)
    await repo.record(email="mine@example.test", reason=SuppressionReason.HARD_BOUNCE)
    await repo.record(email="theirs@example.test", reason=SuppressionReason.COMPLAINT)
    rows = await repo.list_active_for(["MINE@example.test", "absent@example.test"])
    assert [r.email for r in rows] == ["mine@example.test"]
    assert await repo.list_active_for([]) == []
