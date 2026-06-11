"""Mongo-backed campaign repository."""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.communications.application.ports import CampaignRepository
from backend.v2.contexts.communications.domain.models import (
    Campaign,
    CampaignStatus,
    audience_descriptor,
    parse_audience,
)
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoCampaignRepository(TenantScopedRepository, CampaignRepository):
    collection_name = "message_campaigns"

    async def save(self, campaign: Campaign) -> None:
        doc = self._to_doc(campaign)
        await self._update_one(
            {"campaign_id": campaign.campaign_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )

    async def get(self, campaign_id: str) -> Campaign | None:
        doc = await self._find_one({"campaign_id": campaign_id})
        if doc is None:
            return None
        return self._from_doc(doc)

    @staticmethod
    def _to_doc(c: Campaign) -> dict[str, Any]:
        desc = audience_descriptor(c.audience)
        return {
            "campaign_id": c.campaign_id,
            "sender_id": c.sender_id,
            "channel": c.channel,
            "audience_type": desc["type"],
            "audience_filter": desc,
            "subject": c.subject,
            "body": c.body,
            "status": str(c.status),
            "created_at": c.created_at,
            "sent_at": c.sent_at,
        }

    @staticmethod
    def _from_doc(doc: dict[str, Any]) -> Campaign:
        raw_filter = doc.get("audience_filter")
        if raw_filter is None:
            audience_type = doc.get("audience_type", "academy")
            if audience_type == "session":
                raise ValueError(
                    f"campaign {doc.get('campaign_id')}: missing audience_filter for session audience"
                )
            raw_filter = {"type": audience_type}
        return Campaign(
            campaign_id=str(doc["campaign_id"]),
            academy_id=str(doc["academy_id"]),
            sender_id=str(doc["sender_id"]),
            channel=doc.get("channel", "email"),
            audience=parse_audience(raw_filter),
            subject=str(doc.get("subject", "")),
            body=str(doc.get("body", "")),
            status=CampaignStatus(doc.get("status", "draft")),
            created_at=doc["created_at"],
            sent_at=doc.get("sent_at"),
        )
