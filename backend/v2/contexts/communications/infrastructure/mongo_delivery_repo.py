"""Mongo-backed delivery repository."""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.communications.application.ports import DeliveryRepository
from backend.v2.contexts.communications.domain.models import Delivery, DeliveryStatus
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoDeliveryRepository(TenantScopedRepository, DeliveryRepository):
    collection_name = "message_deliveries"

    async def save_many(self, deliveries: list[Delivery]) -> None:
        if not deliveries:
            return
        docs = [self._to_doc(d) for d in deliveries]
        await self.collection.insert_many(docs)

    async def list_for_campaign(self, campaign_id: str) -> list[Delivery]:
        cursor = self._find_many({"campaign_id": campaign_id})
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
