"""RegisterPushDevice — the signed-in user claims an FCM token (mobile M2).

Idempotent: the app re-registers on every launch, which just refreshes
``last_seen_at``. The user always comes from the verified claims, never the body.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.v2.contexts.communications.application.ports import PushDeviceRepository
from backend.v2.contexts.communications.domain.push_device import (
    MAX_APP_VERSION_LENGTH,
    MAX_TOKEN_LENGTH,
    PushDevice,
    PushPlatform,
)

# Re-exported so the HTTP layer can validate without importing the domain.
__all__ = [
    "MAX_APP_VERSION_LENGTH",
    "MAX_TOKEN_LENGTH",
    "PushPlatform",
    "RegisterPushDevice",
    "RegisterPushDeviceCommand",
]


@dataclass(frozen=True, slots=True)
class RegisterPushDeviceCommand:
    user_id: str
    token: str
    platform: PushPlatform
    app_version: str | None = None


@dataclass
class RegisterPushDevice:
    devices: PushDeviceRepository
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    async def execute(self, command: RegisterPushDeviceCommand) -> PushDevice:
        now = self.now()
        return await self.devices.register(
            PushDevice(
                user_id=command.user_id,
                token=command.token,
                platform=command.platform,
                app_version=command.app_version,
                created_at=now,
                last_seen_at=now,
            )
        )
