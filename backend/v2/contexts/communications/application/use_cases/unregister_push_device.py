"""UnregisterPushDevice — drop the caller's FCM token on logout (mobile M2).

Only the holder can remove a token; a missing or someone else's token is a
no-op, so logout never fails and never reveals whether a token exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.v2.contexts.communications.application.ports import PushDeviceRepository


@dataclass
class UnregisterPushDevice:
    devices: PushDeviceRepository

    async def execute(self, *, user_id: str, token: str) -> None:
        await self.devices.delete(user_id=user_id, token=token)
