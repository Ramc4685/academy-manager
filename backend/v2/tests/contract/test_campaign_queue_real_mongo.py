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
    DeliveryStatus,
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
                "c-acad-a",
                now=NOW,
                stale_before=NOW - timedelta(minutes=10),
                token="t",
                max_attempts=5,
            )

    rows = await asyncio.gather(*(claim() for _ in range(5)))
    claimed = [r.delivery_id for r in rows if r is not None]
    assert sorted(claimed) == ["d-acad-a-0", "d-acad-a-1", "d-acad-a-2"]


async def test_a_stale_claim_is_reclaimable_and_a_fresh_one_is_not(real_db) -> None:
    await _seed(real_db, "acad-a")
    repo = MongoDeliveryRepository(real_db)
    with tenant_scope("acad-a"):
        for _ in range(3):
            await repo.claim_next_queued(
                "c-acad-a", now=NOW, stale_before=NOW, token="t", max_attempts=5
            )
        fresh = await repo.claim_next_queued(
            "c-acad-a", now=NOW, stale_before=NOW - timedelta(minutes=10), token="t", max_attempts=5
        )
        later = NOW + timedelta(minutes=11)
        stale = await repo.claim_next_queued(
            "c-acad-a",
            now=later,
            stale_before=later - timedelta(minutes=10),
            token="t2",
            max_attempts=5,
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
            "c-acad-b", now=NOW, stale_before=NOW, token="t", max_attempts=5
        )
    with tenant_scope("acad-c"):
        inline = await MongoCampaignRepository(real_db).list_background_sending()
    assert [c.campaign_id for c in listed] == ["c-acad-a"]
    assert listed[0].background is True
    assert other is None
    assert inline == []


async def test_only_the_current_claim_holder_can_finish_and_exhausted_rows_fail(real_db) -> None:
    await _seed(real_db, "acad-a")
    repo = MongoDeliveryRepository(real_db)
    later = NOW + timedelta(minutes=11)
    with tenant_scope("acad-a"):
        old = await repo.claim_next_queued(
            "c-acad-a", now=NOW, stale_before=NOW, token="old", max_attempts=2
        )
        assert old is not None
        new = await repo.claim_next_queued(
            "c-acad-a",
            now=later,
            stale_before=NOW + timedelta(minutes=1),
            token="new",
            max_attempts=2,
        )
        assert new is not None and new.delivery_id == old.delivery_id
        sent = new.mark_sent(provider_message_id="pm", sent_at=later)
        assert not await repo.finish_claimed(old.mark_failed(reason="late"), token="old")
        assert await repo.finish_claimed(sent, token="new")
        # A second holder can no longer overwrite a finished row either.
        assert not await repo.finish_claimed(old.mark_failed(reason="late"), token="new")

        # The other two rows reach a cap of 1: never claimable again, then given up.
        much_later = later + timedelta(minutes=30)
        claims = [
            await repo.claim_next_queued(
                "c-acad-a", now=much_later, stale_before=much_later, token=t, max_attempts=1
            )
            for t in ("a", "b", "c")
        ]
        assert [c is not None for c in claims] == [True, True, False]
        assert (
            await repo.claim_next_queued(
                "c-acad-a",
                now=much_later + timedelta(hours=1),
                stale_before=much_later + timedelta(minutes=50),
                token="d",
                max_attempts=1,
            )
            is None
        )
        failed = await repo.fail_exhausted(
            "c-acad-a", max_attempts=1, stale_before=much_later + timedelta(minutes=1)
        )
        rows = {d.delivery_id: d for d in await repo.list_for_campaign("c-acad-a")}
    assert rows[old.delivery_id].status == DeliveryStatus.SENT
    assert failed == 2
    gave_up = [d for d in rows.values() if d.failed_reason == "send_gave_up"]
    assert len(gave_up) == 2
