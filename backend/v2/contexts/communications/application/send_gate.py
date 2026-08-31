"""Send-time recipient gates — the shared veto seam.

A *gate* answers one question for one message: may this recipient receive this
category right now? Two independent gates plug in here — the recipient's own
unsubscribe preferences (#555) and the provider suppression list (#556) — and
they are applied in exactly one place,
:class:`~backend.v2.contexts.communications.infrastructure.gated_send_port.GatedEmailSendPort`,
so no send loop has to remember to check anything.

Application layer: pure protocol + value object, no Mongo, no provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.v2.contexts.communications.domain.email_category import EmailCategory


@dataclass(frozen=True, slots=True)
class GateVerdict:
    """A gate's answer for one ``(recipient, category)`` pair."""

    allowed: bool
    reason: str | None = None  # e.g. "suppressed:hard_bounce", "unsubscribed:campaign"


#: The only verdict that lets a message through.
ALLOW = GateVerdict(allowed=True)


class RecipientGate(Protocol):
    """A send-time veto consulted once per recipient, inside the send port.

    Implementations MUST NOT raise: a gate that cannot answer returns
    :data:`ALLOW`. A preference-store outage must not silently stop all mail
    (the #435 lesson — email that fails quietly stays broken for weeks), but it
    must be logged.
    """

    async def check(
        self, *, recipient_user_id: str, email: str, category: EmailCategory
    ) -> GateVerdict: ...
