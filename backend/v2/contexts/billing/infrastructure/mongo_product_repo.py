"""Mongo product catalog repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.billing.domain.product import Product
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoProductRepository(TenantScopedRepository):
    collection_name = "billing_products"

    def __init__(self, db: Any, *, clock=lambda: datetime.now(UTC)) -> None:
        super().__init__(db)
        self._clock = clock

    @staticmethod
    def _product_from_doc(doc: dict[str, object]) -> Product:
        return Product(**{k: v for k, v in doc.items() if k not in ("_id", "idempotency_key")})

    async def create_product(self, product: Product) -> Product:
        doc = _mongo_doc(product)
        await self._insert_one({k: v for k, v in doc.items() if k != "academy_id"})
        stored = await self.get_product(product.product_id)
        if stored is None:
            raise ValueError("product insert failed")
        return stored

    async def get_product(self, product_id: str) -> Product | None:
        doc = await self._find_one({"product_id": product_id})
        return self._product_from_doc(doc) if doc else None

    async def list_products(self, *, active_only: bool = True) -> list[Product]:
        filter_: dict[str, object] = {}
        if active_only:
            filter_["active"] = True
        cursor = self._find_many(filter_, sort=[("name", 1)])
        return [self._product_from_doc(doc) async for doc in cursor]

    async def update_product(self, product_id: str, **updates: object) -> Product:
        academy_id = current_academy_id()
        updates["updated_at"] = self._clock()
        await self.collection.update_one(
            {"academy_id": academy_id, "product_id": product_id},
            {"$set": updates},
        )
        stored = await self.get_product(product_id)
        if stored is None:
            raise ValueError(f"product {product_id} not found")
        return stored

    async def deactivate_product(self, product_id: str) -> Product:
        return await self.update_product(product_id, active=False)


def _mongo_doc(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="python")
