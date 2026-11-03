"""RegisterPushDevice — the signed-in user claims an FCM token (mobile M2).

Idempotent: the app re-registers on every launch, which just refreshes
``last_seen_at``. The user always comes from the verified claims, never the body.

A token that moves from another user or academy is written to ``audit_logs``
(fingerprint only). The move itself stays allowed, since a shared family phone
does exactly this; the audit row is what makes a stolen-token takeover visible.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.v2.contexts.communications.application.ports import (
    PushDeviceRepository,
    PushTokenAudit,
)
from backend.v2.contexts.communications.domain.push_device import (
    MAX_APP_VERSION_LENGTH,
    MAX_TOKEN_LENGTH,
    PushDevice,
    PushPlatform,
)

log = logging.getLogger(__name__)

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
    audit: PushTokenAudit
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    async def execute(self, command: RegisterPushDeviceCommand) -> PushDevice:
        now = self.now()
        device, move = await self.devices.register(
            PushDevice(
                user_id=command.user_id,
                token=command.token,
                platform=command.platform,
                app_version=command.app_version,
                created_at=now,
                last_seen_at=now,
            )
        )
        if move is not None:
            try:
                await self.audit.record_token_moved(move)
            except Exception:
                # The move is already committed, and a retry would be a no-op
                # re-registration, so fail loud in the logs rather than 500.
                log.exception(
                    "push token moved but the audit write failed",
                    extra={
                        "token_fingerprint": move.token_fingerprint,
                        "from_user_id": move.from_user_id,
                        "from_academy_id": move.from_academy_id,
                        "to_user_id": move.to_user_id,
                        "to_academy_id": move.to_academy_id,
                    },
                )
        return device
