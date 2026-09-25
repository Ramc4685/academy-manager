"""E-mail the academy owner when a parent disputes a payment (direct charges).

Bridges billing's ``DisputeNoticePort`` onto communications' ``EmailSendPort``.
Lives in ``composition`` because it reads identity (the owner membership and
user) and sends through communications, which a context may not import.

The notice tells the owner what happened and that the dispute is answered in
THEIR Stripe dashboard: on a direct charge the funds and the dispute sit on
the academy's own account, and the platform takes no action on it.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import Any

from backend.v2.composition.trial_follow_ups import MembershipOwnerLookup
from backend.v2.contexts.billing.domain.events import PaymentDisputeNoticePayload
from backend.v2.contexts.communications.application.ports import (
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.shared.comms.email_theme import EmailBrand, format_money, shell
from backend.v2.shared.tenancy import current_academy_id

log = logging.getLogger(__name__)

_OUTCOME_COPY = {
    "won": "was decided in the academy's favour; Stripe returns the disputed funds.",
    "lost": "was decided in the cardholder's favour; the disputed amount stays deducted.",
    "warning_closed": "was closed as an inquiry without becoming a chargeback.",
}


class DisputeNoticeEmailAdapter:
    def __init__(self, *, db: Any, users: Any, academies: Any, sender: EmailSendPort) -> None:
        self._owners = MembershipOwnerLookup(db)
        self._users = users
        self._academies = academies
        self._sender = sender

    async def send_dispute_notice(self, *, payload: PaymentDisputeNoticePayload) -> None:
        academy_id = current_academy_id()
        owner_id = await self._owners.owner_user_id(academy_id)
        if not owner_id:
            raise ValueError("academy has no active owner to notify of a dispute")
        user = await self._users.get_by_id(owner_id)
        email = str(user.email if user else "").strip()
        if not email:
            raise ValueError("academy owner has no e-mail address for the dispute notice")
        academy_name = await self._academies.get_academy_name(academy_id) or "Your academy"
        subject, inner = render_dispute_notice(payload)
        outcome = await self._sender.send(
            recipient=ResolvedRecipient(
                user_id=owner_id,
                email=email,
                display_name=str(getattr(user, "display_name", "") or "") or None,
            ),
            subject=subject,
            body=shell(brand=EmailBrand(academy_name=academy_name), inner_html=inner),
        )
        if not outcome.ok:
            raise ValueError(outcome.failed_reason or "dispute notice delivery failed")


def render_dispute_notice(payload: PaymentDisputeNoticePayload) -> tuple[str, str]:
    """(subject, inner HTML). Every interpolated value is escaped."""
    amount = html.escape(format_money(payload.amount_cents, payload.currency))
    reason = html.escape(payload.reason.replace("_", " "))
    ref = html.escape(payload.dispute_id)
    if payload.kind == "opened":
        subject = (
            f"A payment of {format_money(payload.amount_cents, payload.currency)} was disputed"
        )
        due = _due_line(payload.evidence_due_by)
        inner = (
            "<h2 style='font-size: 20px; margin: 0 0 12px;'>A payment was disputed</h2>"
            f"<p>A cardholder disputed a payment of <strong>{amount}</strong> "
            f"(reason: {reason}). Stripe has taken the disputed amount and its "
            "dispute fee from your Stripe balance while the dispute is open.</p>"
            f"{due}"
            "<p>Respond with evidence from the Disputes page of your Stripe "
            "dashboard. CourtMastr does not respond on your behalf.</p>"
            f"<p style='font-size: 12px;'>Stripe dispute reference: {ref}</p>"
        )
        return subject, inner
    verdict = _OUTCOME_COPY.get(str(payload.outcome or ""), "has closed.")
    subject = f"Dispute closed: {payload.outcome or 'closed'}"
    inner = (
        "<h2 style='font-size: 20px; margin: 0 0 12px;'>A dispute has closed</h2>"
        f"<p>The dispute over a payment of <strong>{amount}</strong> "
        f"{html.escape(verdict)}</p>"
        f"<p style='font-size: 12px;'>Stripe dispute reference: {ref}</p>"
    )
    return subject, inner


def _due_line(due_by: datetime | None) -> str:
    if due_by is None:
        return ""
    return (
        "<p>Evidence is due by "
        f"<strong>{html.escape(f'{due_by:%B} {due_by.day}, {due_by.year}')}</strong>.</p>"
    )


def build_dispute_notifier(
    db: Any, *, sender: Any, users: Any, academies: Any, enabled: bool
) -> DisputeNoticeEmailAdapter | None:
    """``None`` when e-mail delivery is off: the handler then logs and skips."""
    if not enabled:
        return None
    return DisputeNoticeEmailAdapter(db=db, users=users, academies=academies, sender=sender)
