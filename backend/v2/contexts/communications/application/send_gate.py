"""Send-time gates: the veto consulted once per recipient inside the send port.

Application layer, so it may be implemented by Mongo-backed adapters
(suppression list, recipient preferences) without either the use cases or the
send loops learning about them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.v2.contexts.communications.domain.email_category import EmailCategory


@dataclass(frozen=True, slots=True)
class GateVerdict:
    """A gate's answer for one (recipient, category) pair."""

    allowed: bool
    reason: str | None = None  # e.g. "suppressed:hard_bounce", "unsubscribed:campaign"


ALLOW = GateVerdict(allowed=True)


class RecipientGate(Protocol):
    """A send-time veto consulted once per recipient, inside the send port.

    Implementations MUST NOT raise: a gate that cannot answer returns ALLOW.
    A store outage must not silently stop all mail (the #435 lesson), but it
    must be logged.
    """

    async def check(
        self, *, recipient_user_id: str, email: str, category: EmailCategory
    ) -> GateVerdict: ...
