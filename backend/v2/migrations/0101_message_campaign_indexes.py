"""Message campaigns and deliveries indexes (Wave 4 messaging slice).

Collections:

    message_campaigns
      - unique(campaign_id)
      - (academy_id, created_at desc) — admin listing
      - (academy_id, status, created_at desc) — filter by send state

    message_deliveries
      - unique(delivery_id)
      - (academy_id, campaign_id) — per-campaign roster
      - (academy_id, recipient_user_id, sent_at desc) — per-user history
      - (academy_id, status, campaign_id) — bounce/failure triage
      - unique partial(provider_message_id) where set — webhook lookup
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0101_message_campaign_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:
    campaigns = db["message_campaigns"]
    await campaigns.create_index(
        "campaign_id",
        unique=True,
        name="message_campaigns_campaign_id_unique",
    )
    await campaigns.create_index(
        [("academy_id", 1), ("created_at", -1)],
        name="message_campaigns_academy_created",
    )
    await campaigns.create_index(
        [("academy_id", 1), ("status", 1), ("created_at", -1)],
        name="message_campaigns_academy_status_created",
    )

    deliveries = db["message_deliveries"]
    await deliveries.create_index(
        "delivery_id",
        unique=True,
        name="message_deliveries_delivery_id_unique",
    )
    await deliveries.create_index(
        [("academy_id", 1), ("campaign_id", 1)],
        name="message_deliveries_academy_campaign",
    )
    await deliveries.create_index(
        [("academy_id", 1), ("recipient_user_id", 1), ("sent_at", -1)],
        name="message_deliveries_academy_recipient_sent",
    )
    await deliveries.create_index(
        [("academy_id", 1), ("status", 1), ("campaign_id", 1)],
        name="message_deliveries_academy_status_campaign",
    )
    await deliveries.create_index(
        "provider_message_id",
        unique=True,
        sparse=True,
        partialFilterExpression={"provider_message_id": {"$type": "string"}},
        name="message_deliveries_provider_message_id_unique",
    )
