"""Mongo repository for append-only autopay consent capture."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.billing.domain.models import AutopayConsent
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoAutopayConsentRepository(TenantScopedRepository):
    collection_name = "autopay_consents"

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> AutopayConsent:
        captured_at = doc.get("captured_at") or doc.get("at")
        return AutopayConsent(
            consent_id=str(doc["consent_id"]),
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc["parent_id"]),
            enrollment_id=str(doc["enrollment_id"]),
            setup_intent_id=str(doc["setup_intent_id"]),
            checkout_session_id=doc.get("checkout_session_id"),
            stripe_payment_method_id=str(doc["stripe_payment_method_id"]),
            method_type=str(doc["method_type"]),
            consent_text_version=str(doc["consent_text_version"]),
            ach_mandate_version=doc.get("ach_mandate_version"),
            card_disclosure_version=doc.get("card_disclosure_version"),
            source=doc.get("source", "unknown"),
            actor_id=doc.get("actor_id"),
            ip=doc.get("ip"),
            user_agent=doc.get("user_agent"),
            captured_at=captured_at,
            created_at=doc.get("created_at") or captured_at or datetime.now(UTC),
        )

    async def append(self, consent: AutopayConsent) -> AutopayConsent:
        doc = consent.model_dump(mode="python")
        doc["at"] = consent.captured_at
        doc.pop("academy_id", None)
        await self._insert_one(doc)
        return consent

    async def list_for_parent(self, *, parent_id: str) -> list[AutopayConsent]:
        cursor = self._find_many(
            {"parent_id": parent_id},
            sort=[("captured_at", 1), ("created_at", 1), ("consent_id", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
