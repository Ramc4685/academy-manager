"""GetDigestDeliveryLog use case.

Thin read over the ``DigestSendRepository`` for the admin Notifications tab:
the most recent coach-digest sends for an academy (daily + test), newest first.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.v2.contexts.communications.application.ports import DigestSendRepository
from backend.v2.contexts.communications.domain.models import DigestSend


@dataclass
class GetDigestDeliveryLog:
    digests: DigestSendRepository

    async def execute(self, academy_id: str, *, limit: int = 20) -> list[DigestSend]:
        return await self.digests.list_recent(academy_id, limit)
