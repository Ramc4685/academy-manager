"""UnregisterPushDevice — drop the caller's FCM token on logout (mobile M2).

Only the holder can remove a token; a missing or someone else's token is a
no-op, so logout never fails and never reveals whether a token exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backend.v2.contexts.communications.application.ports import PushDeviceRepository


@dataclass
class UnregisterPushDevice:
    devices: PushDeviceRepository

    async def execute(self, *, user_id: str, token: str) -> None:
        await self.devices.delete(user_id=user_id, token=token)


@dataclass
class ForgetPushDevices:
    """Drop every token a deleted account holds, in each academy it belonged to."""

    devices: PushDeviceRepository

    async def execute(self, *, user_ids: Sequence[str], academy_ids: Sequence[str]) -> None:
        for academy_id in academy_ids:
            for user_id in user_ids:
                tokens = await self.devices.tokens_for_user(academy_id, user_id)
                await self.devices.delete_tokens(academy_id, tokens)
