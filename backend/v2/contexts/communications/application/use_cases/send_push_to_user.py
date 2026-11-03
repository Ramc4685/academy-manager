"""SendPushToUser — best-effort push to every device a user holds (mobile M3).

Email stays the channel of record: push is an extra nudge, so this never
raises into its caller. Tokens FCM reports dead are pruned here.

Hook-up point: there is no ``ParentNotifier`` in main yet (it is proposed in
``docs/design/whatsapp-channel/design.md`` §5). When it lands it should call
``app.state.send_push_to_user`` after the email send, exactly as it would
WhatsApp, so a push failure can never fail or retry the email.
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

log = logging.getLogger(__name__)


@dataclass
class SendPushToUser:
    devices: PushDeviceRepository
    sender: PushSendPort

    async def execute(
        self,
        *,
        academy_id: str,
        user_id: str,
        title: str,
        body: str,
        data: Mapping[str, str] | None = None,
    ) -> PushSendResult:
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
