"""End-to-end test of the campaign idempotency claim against mongomock.

Exercises the real TenantScopedRepository-backed repos, the 0101/0155 indexes,
and the insert-first claim guard through an actual (mock) Mongo driver
(issue #512).
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest
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
from backend.v2.shared.tenancy.context import tenant_scope
from mongomock_motor import AsyncMongoMockClient

ACADEMY_ID = "acad-campaign-test"

_indexes_0101 = importlib.import_module("backend.v2.migrations.0101_message_campaign_indexes")
_indexes_0155 = importlib.import_module("backend.v2.migrations.0155_campaign_idempotency_key_index")


def _campaign(campaign_id: str, key: str) -> Campaign:
    return Campaign.new(
        campaign_id=campaign_id,
        academy_id=ACADEMY_ID,
        sender_id="u-admin",
        audience=AcademyAudience(role="parent"),
        subject="Hi",
        body="Body",
        created_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
        idempotency_key=key,
    ).mark_sending()


async def _db():
    db = AsyncMongoMockClient()["campaign_test"]
    await _indexes_0101.up(db)
    await _indexes_0155.up(db)
    return db


@pytest.mark.asyncio
async def test_try_claim_wins_once_then_refuses() -> None:
    db = await _db()
    with tenant_scope(ACADEMY_ID):
        repo = MongoCampaignRepository(db)

        assert await repo.try_claim(_campaign("c-1", "key-1")) is True
        # Same key, different campaign_id: claim refused.
        assert await repo.try_claim(_campaign("c-2", "key-1")) is False
        # Different key still claims.
        assert await repo.try_claim(_campaign("c-3", "key-2")) is True

        count = await db["message_campaigns"].count_documents({})
        assert count == 2

        existing = await repo.get_by_idempotency_key("key-1")
        assert existing is not None
        assert existing.campaign_id == "c-1"


@pytest.mark.asyncio
async def test_try_claim_requires_key() -> None:
    db = await _db()
    with tenant_scope(ACADEMY_ID):
        repo = MongoCampaignRepository(db)
        campaign = _campaign("c-1", "key-1")
        campaign = Campaign(
            **{
                **{
                    f: getattr(campaign, f)
                    for f in (
                        "campaign_id",
                        "academy_id",
                        "sender_id",
                        "channel",
                        "audience",
                        "subject",
                        "body",
                        "status",
                        "created_at",
                        "sent_at",
                    )
                },
                "idempotency_key": None,
            }
        )
        with pytest.raises(ValueError):
            await repo.try_claim(campaign)


@pytest.mark.asyncio
async def test_delivery_save_many_upserts_by_delivery_id() -> None:
    db = await _db()
    with tenant_scope(ACADEMY_ID):
        repo = MongoDeliveryRepository(db)
        recipient = ResolvedRecipient(user_id="p-1", email="p1@example.test")

        queued = Delivery.queued(
            delivery_id="d-1",
            academy_id=ACADEMY_ID,
            campaign_id="c-1",
            recipient=recipient,
        )
        await repo.save_many([queued])

        rows = await repo.list_for_campaign("c-1")
        assert len(rows) == 1
        assert rows[0].status == DeliveryStatus.QUEUED

        # Second write for the same delivery_id overwrites instead of raising
        # on the unique index — the post-loop state replaces the queued row.
        sent = queued.mark_sent(
            provider_message_id="prov-1",
            sent_at=datetime(2026, 8, 29, 12, 5, tzinfo=UTC),
        )
        await repo.save_many([sent])

        rows = await repo.list_for_campaign("c-1")
        assert len(rows) == 1
        assert rows[0].status == DeliveryStatus.SENT
        assert rows[0].provider_message_id == "prov-1"
