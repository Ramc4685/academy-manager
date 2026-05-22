"""Mongo-backed WaiverTemplate repository.

Templates are immutable once active. This repo only supports ``get`` (by id)
and ``get_active`` (most-recent active template, if any). Publishing /
superseding flows belong in a dedicated admin use case which is not part of
this Wave 4 prep slice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.onboarding.domain.models import WaiverTemplate
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoWaiverTemplateRepository(TenantScopedRepository):
    collection_name = "waiver_templates"

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
    def _to_domain(cls, doc: dict[str, Any]) -> WaiverTemplate:
        effective_from = cls._as_datetime(doc.get("effective_from"))
        if effective_from is None:
            raise ValueError(
                f"waiver_templates row {doc.get('waiver_template_id')!r} "
                "is missing effective_from"
            )
        return WaiverTemplate(
            waiver_template_id=str(doc["waiver_template_id"]),
            academy_id=str(doc["academy_id"]),
            name=str(doc.get("name") or ""),
            version=str(doc["version"]),
            content_hash=str(doc["content_hash"]),
            body=str(doc.get("body") or ""),
            effective_from=effective_from,
            expires_at=cls._as_datetime(doc.get("expires_at")),
            status=str(doc.get("status") or "active"),  # type: ignore[arg-type]
        )

    async def get(self, waiver_template_id: str) -> WaiverTemplate | None:
        doc = await self._find_one({"waiver_template_id": waiver_template_id})
        return self._to_domain(doc) if doc else None

    async def get_active(self) -> WaiverTemplate | None:
        cursor = self._find_many(
            {"status": "active"},
            sort=[("effective_from", -1)],
            limit=1,
        )
        async for doc in cursor:
            return self._to_domain(doc)
        return None
