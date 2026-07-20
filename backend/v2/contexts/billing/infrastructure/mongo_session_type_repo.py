"""Mongo SessionTypeRepository."""

from __future__ import annotations

from backend.v2.contexts.billing.domain.session_type import SessionType
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoSessionTypeRepository(TenantScopedRepository):
    collection_name = "session_types"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> SessionType:
        return SessionType(
            session_type_id=str(doc["session_type_id"]),
            academy_id=str(doc["academy_id"]),
            name=str(doc["name"]),
            description=doc.get("description"),
            price_cents=int(doc["price_cents"]),
            billing_period=doc.get("billing_period", "monthly"),
            overage_rate_cents=doc.get("overage_rate_cents"),
            is_active=bool(doc.get("is_active", True)),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

    async def save(self, session_type: SessionType) -> None:
        doc = session_type.model_dump(mode="python")
        await self._update_one(
            {"session_type_id": session_type.session_type_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )

    async def get(self, session_type_id: str) -> SessionType | None:
        doc = await self._find_one({"session_type_id": session_type_id})
        return self._to_domain(doc) if doc else None

    async def list_active(self) -> list[SessionType]:
        cursor = self._find_many({"is_active": True}, sort=[("name", 1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def soft_delete(self, session_type_id: str) -> None:
        await self._update_one(
            {"session_type_id": session_type_id},
            {"$set": {"is_active": False}},
            upsert=False,
        )
