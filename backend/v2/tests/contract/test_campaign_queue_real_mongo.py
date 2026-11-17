"""The background campaign queue on a real mongod (L11 item 7): a delivery is
claimed by one worker only, a stale claim is reclaimable, and claims and the
background listing stay inside the request academy."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from backend.v2.contexts.communications.application.ports import ResolvedRecipient
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    Campaign,
    Delivery,
)
from backend.v2.contexts.communications.infrastructure.mongo_campaign_repo import (
    MongoCampaignRepository,
)
from backend.v2.contexts.communications.infrastructure.mongo_delivery_repo import (
    MongoDeliveryRepository,
)
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 11, 17, 12, tzinfo=UTC)


async def _seed(db, academy_id: str, *, background: bool = True) -> None:
    with tenant_scope(academy_id):
        await MongoCampaignRepository(db).save(
            Campaign.new(
                campaign_id=f"c-{academy_id}",
                academy_id=academy_id,
                sender_id="admin",
                audience=AcademyAudience(role="parent"),
                subject="s",
                body="b",
                created_at=NOW,
                idempotency_key=f"k-{academy_id}",
                background=background,
            ).mark_sending()
        )
        await MongoDeliveryRepository(db).save_many(
            [
                Delivery.queued(
                    delivery_id=f"d-{academy_id}-{i}",
                    academy_id=academy_id,
                    campaign_id=f"c-{academy_id}",
                    recipient=ResolvedRecipient(user_id=f"u{i}", email=f"u{i}@example.test"),
                )
                for i in range(3)
            ]
        )


async def test_concurrent_claims_never_share_a_row(real_db) -> None:
    await _seed(real_db, "acad-a")
    repo = MongoDeliveryRepository(real_db)

    async def claim():
        with tenant_scope("acad-a"):
            return await repo.claim_next_queued(
                "c-acad-a", now=NOW, stale_before=NOW - timedelta(minutes=10)
            )

    rows = await asyncio.gather(*(claim() for _ in range(5)))
    claimed = [r.delivery_id for r in rows if r is not None]
    assert sorted(claimed) == ["d-acad-a-0", "d-acad-a-1", "d-acad-a-2"]


async def test_a_stale_claim_is_reclaimable_and_a_fresh_one_is_not(real_db) -> None:
    await _seed(real_db, "acad-a")
    repo = MongoDeliveryRepository(real_db)
    with tenant_scope("acad-a"):
        for _ in range(3):
            await repo.claim_next_queued("c-acad-a", now=NOW, stale_before=NOW)
        fresh = await repo.claim_next_queued(
            "c-acad-a", now=NOW, stale_before=NOW - timedelta(minutes=10)
        )
        later = NOW + timedelta(minutes=11)
        stale = await repo.claim_next_queued(
            "c-acad-a", now=later, stale_before=later - timedelta(minutes=10)
        )
    assert fresh is None
    assert stale is not None


async def test_listing_and_claims_stay_in_the_request_academy(real_db) -> None:
    await _seed(real_db, "acad-a")
    await _seed(real_db, "acad-b")
    await _seed(real_db, "acad-c", background=False)
    with tenant_scope("acad-a"):
        listed = await MongoCampaignRepository(real_db).list_background_sending()
        other = await MongoDeliveryRepository(real_db).claim_next_queued(
            "c-acad-b", now=NOW, stale_before=NOW
        )
    with tenant_scope("acad-c"):
        inline = await MongoCampaignRepository(real_db).list_background_sending()
    assert [c.campaign_id for c in listed] == ["c-acad-a"]
    assert listed[0].background is True
    assert other is None
    assert inline == []
