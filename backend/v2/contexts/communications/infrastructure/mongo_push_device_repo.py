"""Mongo ``push_devices``: FCM registration tokens (mobile M2).

Unique on ``token`` across ALL academies (migration 0215), on purpose: a token
is one app install on one phone. If it stayed registered to the previous user
or academy, that user's pushes would reach whoever holds the phone now. So
``register`` matches on the token alone and re-stamps ``user_id`` and
``academy_id`` from the request (the tenant in scope), which moves the row.
That is the one write here not filtered by academy; it can only ever pull a
row INTO the caller's tenant and identity, and only for a token the caller
presents, and it reports every such move so the caller can audit it.
Deletes are fully scoped: user + token + the tenant in scope.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from pymongo import ReturnDocument

from backend.v2.contexts.communications.application.ports import PushDeviceRepository
from backend.v2.contexts.communications.domain.push_device import (
    PushDevice,
    PushTokenMove,
    token_fingerprint,
)
from backend.v2.shared.tenancy.context import current_academy_id
from backend.v2.shared.tenancy.repository import TenantScopedRepository


class MongoPushDeviceRepository(TenantScopedRepository, PushDeviceRepository):
    collection_name = "push_devices"

    async def register(self, device: PushDevice) -> tuple[PushDevice, PushTokenMove | None]:
        academy_id = current_academy_id()
        # BEFORE, not AFTER: the previous holder is what makes a move auditable,
        # and the atomic swap means concurrent registrations each see their own.
        before = await self.collection.find_one_and_update(
            {"token": device.token},
            {
                "$set": {
                    "user_id": device.user_id,
                    "academy_id": academy_id,
                    "platform": device.platform,
                    "app_version": device.app_version,
                    "last_seen_at": device.last_seen_at,
                },
                "$setOnInsert": {"created_at": device.created_at},
            },
            upsert=True,
            return_document=ReturnDocument.BEFORE,
        )
        if before is None:
            return device, None
        stored = replace(device, created_at=before["created_at"])
        if (before["user_id"], before["academy_id"]) == (device.user_id, academy_id):
            return stored, None
        return stored, PushTokenMove(
            token_fingerprint=token_fingerprint(device.token),
            from_user_id=before["user_id"],
            from_academy_id=before["academy_id"],
            to_user_id=device.user_id,
            to_academy_id=academy_id,
        )

    async def delete(self, *, user_id: str, token: str) -> None:
        await self._delete_one({"token": token, "user_id": user_id})

    async def tokens_for_user(self, academy_id: str, user_id: str) -> list[str]:
        cursor = self.collection.find(
            {"academy_id": academy_id, "user_id": user_id}, {"token": 1, "_id": 0}
        )
        return [doc["token"] async for doc in cursor]

    async def delete_tokens(self, academy_id: str, tokens: Sequence[str]) -> None:
        if tokens:
            await self.collection.delete_many(
                {"academy_id": academy_id, "token": {"$in": list(tokens)}}
            )
