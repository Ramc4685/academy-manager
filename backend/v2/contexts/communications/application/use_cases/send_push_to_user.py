"""SendPushToUser — best-effort push to every device a user holds (mobile M3).

Email stays the channel of record: push is an extra nudge, so this never
raises into its caller. Tokens FCM reports dead are pruned here.

Callers (built by ``composition.push.compose_send_push_to_user``) send after
their email, so a push failure can never fail or retry the email: class date
cancelled and waitlist offer (``RosterAlertAdapter``), urgent announcements
(``SessionAnnouncementService``) and dues reminders (``compose_dues_reminders``).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from backend.v2.contexts.communications.application.ports import (
    PushDeviceRepository,
    PushSendPort,
)
from backend.v2.contexts.communications.domain.push_device import PushSendResult
from backend.v2.contexts.communications.domain.push_events import ALWAYS_ON, PushEvent

log = logging.getLogger(__name__)


@dataclass
class SendPushToUser:
    devices: PushDeviceRepository
    sender: PushSendPort
    #: The push event catalogue (L11 item 5); see ``domain.push_events``.
    enabled_events: frozenset[PushEvent] = ALWAYS_ON

    def allows(self, event: PushEvent) -> bool:
        return event in self.enabled_events

    async def execute(
        self,
        *,
        academy_id: str,
        user_id: str,
        title: str,
        body: str,
        data: Mapping[str, str] | None = None,
        event: PushEvent | None = None,
    ) -> PushSendResult:
        if event is not None and not self.allows(event):
            return PushSendResult()
        try:
            tokens = await self.devices.tokens_for_user(academy_id, user_id)
            if not tokens:
                return PushSendResult()
            result = await self.sender.send(
                tokens=tokens, title=title, body=body, data=dict(data or {})
            )
            if result.dead_tokens:
                await self.devices.delete_tokens(academy_id, result.dead_tokens)
            return result
        except Exception:
            log.warning(
                "push send failed; email remains the channel of record",
                extra={"academy_id": academy_id, "user_id": user_id},
                exc_info=True,
            )
            return PushSendResult()
