"""Mongo ``push_devices``: FCM registration tokens (mobile M2).

Unique on ``token`` across ALL academies (migration 0215), on purpose: a token
is one app install on one phone. If it stayed registered to the previous user
or academy, that user's pushes would reach whoever holds the phone now. So
``register`` matches on the token alone and re-stamps ``user_id`` and
``academy_id`` from the request (the tenant in scope), which moves the row.
That is the one write here not filtered by academy; it can only ever pull a
row INTO the caller's tenant and identity, and only for a token the caller
presents. Deletes are fully scoped: user + token + the tenant in scope.
"""

from __future__ import annotations

from typing import Any

from pymongo import ReturnDocument

from backend.v2.contexts.communications.application.ports import PushDeviceRepository
from backend.v2.contexts.communications.domain.push_device import PushDevice
from backend.v2.shared.tenancy.context import current_academy_id
from backend.v2.shared.tenancy.repository import TenantScopedRepository


def _to_device(doc: dict[str, Any]) -> PushDevice:
    return PushDevice(
        user_id=doc["user_id"],
        token=doc["token"],
        platform=doc["platform"],
        app_version=doc.get("app_version"),
        created_at=doc["created_at"],
        last_seen_at=doc["last_seen_at"],
    )


class MongoPushDeviceRepository(TenantScopedRepository, PushDeviceRepository):
    collection_name = "push_devices"

    async def register(self, device: PushDevice) -> PushDevice:
        doc = await self.collection.find_one_and_update(
            {"token": device.token},
            {
                "$set": {
                    "user_id": device.user_id,
                    "academy_id": current_academy_id(),
                    "platform": device.platform,
                    "app_version": device.app_version,
                    "last_seen_at": device.last_seen_at,
                },
                "$setOnInsert": {"created_at": device.created_at},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return _to_device(doc)

    async def delete(self, *, user_id: str, token: str) -> None:
        await self._delete_one({"token": token, "user_id": user_id})
