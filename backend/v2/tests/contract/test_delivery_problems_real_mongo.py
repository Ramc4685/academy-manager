"""Delivery-problems reads on a real mongod (L11 item 3): failed sends stay in
the request academy, and the suppression lookup returns only the addresses
asked for, never the rest of the global list."""

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


async def test_failed_deliveries_stay_in_the_request_academy(real_db) -> None:
    repo = MongoDeliveryRepository(real_db)
    for academy in ("acad-a", "acad-b"):
        with tenant_scope(academy):
            queued = Delivery.queued(
                delivery_id=f"d-{academy}",
                academy_id=academy,
                campaign_id="c",
                recipient=ResolvedRecipient(user_id="u", email="u@example.test"),
            )
            await repo.save_many([queued.mark_failed(reason="provider 422")])
    with tenant_scope("acad-a"):
        failed = await repo.list_failed(limit=10)
    assert [d.delivery_id for d in failed] == ["d-acad-a"]


async def test_suppression_lookup_returns_only_the_addresses_asked_for(real_db) -> None:
    repo = MongoSuppressionRepository(real_db)
    await repo.record(email="mine@example.test", reason=SuppressionReason.HARD_BOUNCE)
    await repo.record(email="theirs@example.test", reason=SuppressionReason.COMPLAINT)
    rows = await repo.list_active_for(["MINE@example.test", "absent@example.test"])
    assert [r.email for r in rows] == ["mine@example.test"]
    assert await repo.list_active_for([]) == []
