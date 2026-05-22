"""Mongo-backed WaiverSignature repository.

Signatures are tenant-scoped and per student. Each row pins to an immutable
``waiver_template_id`` and captures the ``content_hash`` at sign-time. The
``artifact_id`` points to the rendered signed document in artifact storage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.onboarding.domain.models import WaiverSignature
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoWaiverSignatureRepository(TenantScopedRepository):
    collection_name = "waiver_signatures"

    # ---- (de)serialisation ------------------------------------------------

    @staticmethod
    def _as_datetime(value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                return None
        return None

    @classmethod
    def _to_domain(cls, doc: dict[str, Any]) -> WaiverSignature:
        signed_at = cls._as_datetime(doc.get("signed_at"))
        if signed_at is None:
            raise ValueError(
                f"waiver_signatures row {doc.get('waiver_signature_id')!r} is missing signed_at"
            )
        return WaiverSignature(
            waiver_signature_id=str(doc["waiver_signature_id"]),
            academy_id=str(doc["academy_id"]),
            waiver_template_id=str(doc["waiver_template_id"]),
            student_id=str(doc["student_id"]),
            parent_user_id=str(doc.get("parent_user_id") or ""),
            signed_at=signed_at,
            signer_name=str(doc.get("signer_name") or ""),
            signer_email=str(doc.get("signer_email") or ""),
            content_hash=str(doc.get("content_hash") or ""),
            ip_address=(str(doc["ip_address"]) if doc.get("ip_address") else None),
            user_agent=(str(doc["user_agent"]) if doc.get("user_agent") else None),
            artifact_id=(str(doc["artifact_id"]) if doc.get("artifact_id") else None),
            expires_at=cls._as_datetime(doc.get("expires_at")),
        )

    @staticmethod
    def _to_document(signature: WaiverSignature) -> dict[str, Any]:
        return {
            "waiver_signature_id": signature.waiver_signature_id,
            "waiver_template_id": signature.waiver_template_id,
            "student_id": signature.student_id,
            "parent_user_id": signature.parent_user_id,
            "signed_at": signature.signed_at,
            "signer_name": signature.signer_name,
            "signer_email": signature.signer_email,
            "content_hash": signature.content_hash,
            "ip_address": signature.ip_address,
            "user_agent": signature.user_agent,
            "artifact_id": signature.artifact_id,
            "expires_at": signature.expires_at,
        }

    # ---- ops --------------------------------------------------------------

    async def save(self, signature: WaiverSignature) -> None:
        """Upsert by ``waiver_signature_id``. Tenant scope is enforced by the
        base class via ``academy_id``."""
        await self._update_one(
            {"waiver_signature_id": signature.waiver_signature_id},
            {"$set": self._to_document(signature)},
            upsert=True,
        )

    async def get(self, waiver_signature_id: str) -> WaiverSignature | None:
        doc = await self._find_one({"waiver_signature_id": waiver_signature_id})
        return self._to_domain(doc) if doc else None

    async def latest_for_student(self, student_id: str) -> WaiverSignature | None:
        cursor = self._find_many(
            {"student_id": student_id},
            sort=[("signed_at", -1)],
            limit=1,
        )
        async for doc in cursor:
            return self._to_domain(doc)
        return None

    async def list_for_student(self, student_id: str) -> list[WaiverSignature]:
        cursor = self._find_many(
            {"student_id": student_id},
            sort=[("signed_at", -1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
