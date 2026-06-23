"""Mongo WaiverRepository for the parent registration stepper.

Resolves the waiver template that is active AND assigned to registration
by an admin (assigned_to_registration == True). Returns None when no such
template exists — PatchApplication raises NoActiveWaiver in that case.

Maps WaiverTemplate fields → legacy Waiver domain shape so PatchApplication
needs no change. The waiver_id on the returned Waiver equals the source
waiver_template_id, allowing WaiverAcceptance to pin the audit link.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from backend.v2.contexts.onboarding.domain.models import Waiver
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoRegistrationWaiverRepository(TenantScopedRepository):
    collection_name = "waiver_templates"

    @staticmethod
    def _as_datetime(value: object) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        raise ValueError(f"Cannot parse datetime from {value!r}")

    @classmethod
    def _to_domain(cls, doc: dict[str, Any]) -> Waiver:
        text = str(doc.get("body") or doc.get("text") or doc.get("waiver_text") or "")
        content_hash = doc.get("content_hash") or sha256(text.encode("utf-8")).hexdigest()
        effective_from = (
            doc.get("effective_from")
            or doc.get("published_at")
            or doc.get("assigned_at")
            or doc.get("updated_at")
        )
        return Waiver(
            waiver_id=str(doc.get("waiver_template_id") or doc.get("waiver_id") or doc["_id"]),
            academy_id=str(doc["academy_id"]),
            version=str(doc["version"]),
            text=text,
            content_hash=str(content_hash),
            effective_from=cls._as_datetime(effective_from),
        )

    async def get_active(self) -> Waiver | None:
        cursor = self._find_many(
            {"status": "active", "assigned_to_registration": True},
            sort=[("assigned_at", -1), ("effective_from", -1)],
            limit=1,
        )
        async for doc in cursor:
            return self._to_domain(doc)

        cursor = self._find_many(
            {
                "status": "published",
                "body": {"$type": "string", "$ne": ""},
                "assigned_to_registration": {"$exists": False},
            },
            sort=[("published_at", -1), ("effective_from", -1), ("updated_at", -1)],
            limit=1,
        )
        async for doc in cursor:
            return self._to_domain(doc)
        return None
