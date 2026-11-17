"""Mongo-backed delivery repository."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.v2.contexts.communications.application.ports import DeliveryRepository
from backend.v2.contexts.communications.domain.models import Delivery, DeliveryStatus
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoDeliveryRepository(TenantScopedRepository, DeliveryRepository):
    collection_name = "message_deliveries"

    async def save_many(self, deliveries: list[Delivery]) -> None:
        """Upsert delivery rows keyed by delivery_id.

        SendCampaign persists the QUEUED batch before the send loop and the
        final per-recipient states after it; the second write must overwrite
        the queued rows rather than raise on the unique delivery_id index.
        """
        for d in deliveries:
            doc = self._to_doc(d)
            await self._update_one(
                {"delivery_id": d.delivery_id},
                {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
                upsert=True,
            )

    async def list_for_campaign(self, campaign_id: str) -> list[Delivery]:
        cursor = self._find_many({"campaign_id": campaign_id})
        return [self._from_doc(d) async for d in cursor]

    async def claim_next_queued(
        self,
        campaign_id: str,
        *,
        now: datetime,
        stale_before: datetime,
        token: str,
        max_attempts: int,
    ) -> Delivery | None:
        doc = await self._find_one_and_update(
            {
                "campaign_id": campaign_id,
                "status": str(DeliveryStatus.QUEUED),
                "$and": [
                    {
                        "$or": [
                            {"claimed_at": {"$exists": False}},
                            {"claimed_at": None},
                            {"claimed_at": {"$lt": stale_before}},
                        ]
                    },
                    {
                        "$or": [
                            {"claim_attempts": {"$exists": False}},
                            {"claim_attempts": {"$lt": max_attempts}},
                        ]
                    },
                ],
            },
            {"$set": {"claimed_at": now, "claim_token": token}, "$inc": {"claim_attempts": 1}},
        )
        return self._from_doc(doc) if doc else None

    async def finish_claimed(self, delivery: Delivery, *, token: str) -> bool:
        doc = self._to_doc(delivery)
        result = await self._update_one(
            {
                "delivery_id": delivery.delivery_id,
                "status": str(DeliveryStatus.QUEUED),
                "claim_token": token,
            },
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
        )
        return bool(result.modified_count)

    async def fail_exhausted(
        self, campaign_id: str, *, max_attempts: int, stale_before: datetime
    ) -> int:
        result = await self.collection.update_many(
            self._scoped(
                {
                    "campaign_id": campaign_id,
                    "status": str(DeliveryStatus.QUEUED),
                    "claim_attempts": {"$gte": max_attempts},
                    "claimed_at": {"$lt": stale_before},
                }
            ),
            {"$set": {"status": str(DeliveryStatus.FAILED), "failed_reason": "send_gave_up"}},
        )
        return int(result.modified_count)

    async def list_failed(self, *, limit: int) -> list[Delivery]:
        # Gate refusals carry a shared-suppression reason; never list them.
        cursor = self._find_many(
            {
                "status": str(DeliveryStatus.FAILED),
                "failed_reason": {"$not": {"$regex": "^(suppressed|unsubscribed):"}},
            },
            sort=[("_id", -1)],
            limit=limit,
        )
        return [self._from_doc(d) async for d in cursor]

    @staticmethod
    def _to_doc(d: Delivery) -> dict[str, Any]:
        from backend.v2.shared.tenancy.context import current_academy_id

        return {
            "delivery_id": d.delivery_id,
            "academy_id": current_academy_id(),
            "campaign_id": d.campaign_id,
            "recipient_user_id": d.recipient_user_id,
            "recipient_email": d.recipient_email,
            "status": str(d.status),
            "provider_message_id": d.provider_message_id,
            "sent_at": d.sent_at,
            "opened_at": d.opened_at,
            "failed_reason": d.failed_reason,
        }

    @staticmethod
    def _from_doc(doc: dict[str, Any]) -> Delivery:
        return Delivery(
            delivery_id=str(doc["delivery_id"]),
            academy_id=str(doc["academy_id"]),
            campaign_id=str(doc["campaign_id"]),
            recipient_user_id=str(doc["recipient_user_id"]),
            recipient_email=doc.get("recipient_email"),
            status=DeliveryStatus(doc.get("status", "queued")),
            provider_message_id=doc.get("provider_message_id"),
            sent_at=doc.get("sent_at"),
            opened_at=doc.get("opened_at"),
            failed_reason=doc.get("failed_reason"),
        )
