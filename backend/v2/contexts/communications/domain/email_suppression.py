"""Email suppression list — the deliverability half of the send-time gate.

A suppression is a *provider-observed fact about a mailbox*, not a recipient
preference. That difference drives every rule below.

Reason-aware blocking (issue #556):

- ``hard_bounce`` blocks **every** category, transactional included. The
  mailbox does not exist; sending is not "delivering an invoice", it is
  burning the shared sender domain's reputation for every tenant. The invoice
  is still in the parent portal, and the admin sees the suppression in the
  delivery log.
- ``complaint`` (spam report) blocks ``DIGEST`` and ``CAMPAIGN`` but allows
  ``TRANSACTIONAL``. A complaint is a marketing signal, not proof the address
  is dead.
- ``manual`` (admin-added) is treated the same as ``complaint``.
- Soft/transient bounces and delivery delays never produce a suppression at
  all. They are recorded as provider events and nothing more — a full mailbox
  is not a dead address.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from backend.v2.contexts.communications.domain.email_category import (
    UNSUBSCRIBABLE_CATEGORIES,
    EmailCategory,
)


class SuppressionReason(StrEnum):
    HARD_BOUNCE = "hard_bounce"
    COMPLAINT = "complaint"
    MANUAL = "manual"


#: How "severe" each reason is. A repeat event may escalate a suppression
#: (complaint → hard_bounce) but must never downgrade one: a mailbox that has
#: already proven it does not exist does not become deliverable because a
#: later complaint event arrives for the same address.
_SEVERITY: dict[SuppressionReason, int] = {
    SuppressionReason.MANUAL: 1,
    SuppressionReason.COMPLAINT: 1,
    SuppressionReason.HARD_BOUNCE: 2,
}


def normalize_email(email: str) -> str:
    """The identity key for a suppression. Addresses are matched case-blind."""
    return email.strip().lower()


def escalates(current: SuppressionReason, incoming: SuppressionReason) -> bool:
    """True when ``incoming`` is strictly more severe than ``current``."""
    return _SEVERITY[incoming] > _SEVERITY[current]


def blocks(reason: SuppressionReason, category: EmailCategory) -> bool:
    """Whether a suppression for ``reason`` stops an email of ``category``."""
    if reason is SuppressionReason.HARD_BOUNCE:
        return True
    return category in UNSUBSCRIBABLE_CATEGORIES


@dataclass(frozen=True, slots=True)
class EmailSuppression:
    """One suppressed address.

    Deliberately carries no ``academy_id`` in its identity: the Resend sender
    domain is shared by every academy, so a hard bounce observed under academy
    A must stop academy B from mailing the same address.
    """

    email: str
    reason: SuppressionReason
    first_seen_at: datetime
    last_seen_at: datetime
    active: bool = True
    bounce_subtype: str | None = None
    provider: str = "resend"
    provider_event_id: str | None = None
    #: Best-effort audit attribution only — NEVER a query filter.
    first_seen_academy_id: str | None = None
    released_at: datetime | None = None
    released_by: str | None = None

    def blocks(self, category: EmailCategory) -> bool:
        return self.active and blocks(self.reason, category)

    @property
    def gate_reason(self) -> str:
        return f"suppressed:{self.reason.value}"


# --- Resend event classification -------------------------------------------

RESEND_BOUNCED = "email.bounced"
RESEND_COMPLAINED = "email.complained"
RESEND_DELIVERY_DELAYED = "email.delivery_delayed"

#: Event types we understand. Anything else is stored ``ignored`` and 200'd —
#: Resend adds event types without asking us, and a 500 would make it retry a
#: message we will never care about.
KNOWN_EVENT_TYPES = frozenset({RESEND_BOUNCED, RESEND_COMPLAINED, RESEND_DELIVERY_DELAYED})

#: Bounce classifications that are explicitly NOT permanent. A mailbox that is
#: full or a server that deferred us is not a dead address, so these are
#: recorded and dropped rather than suppressed.
_TRANSIENT_BOUNCE_TYPES = frozenset({"transient", "undetermined", "soft", "delayed"})


@dataclass(frozen=True, slots=True)
class ClassifiedEvent:
    """What one provider event means for the suppression list."""

    email: str | None
    reason: SuppressionReason | None
    bounce_subtype: str | None

    @property
    def suppresses(self) -> bool:
        return self.reason is not None and self.email is not None


def classify_resend_event(event_type: str, data: dict[str, object]) -> ClassifiedEvent:
    """Map one Resend webhook event onto a suppression decision.

    ``reason is None`` means "record the event, suppress nothing" — which is
    the answer for every soft bounce and delivery delay.
    """
    email = _first_recipient(data)
    bounce = data.get("bounce")
    bounce_info: dict[str, object] = bounce if isinstance(bounce, dict) else {}
    subtype = _as_str(bounce_info.get("subType")) or _as_str(bounce_info.get("sub_type"))
    bounce_type = (_as_str(bounce_info.get("type")) or "").strip().lower()

    if event_type == RESEND_COMPLAINED:
        return ClassifiedEvent(email=email, reason=SuppressionReason.COMPLAINT, bounce_subtype=None)
    if event_type == RESEND_DELIVERY_DELAYED:
        return ClassifiedEvent(email=email, reason=None, bounce_subtype=subtype)
    if event_type == RESEND_BOUNCED:
        if bounce_type in _TRANSIENT_BOUNCE_TYPES:
            return ClassifiedEvent(email=email, reason=None, bounce_subtype=subtype)
        return ClassifiedEvent(
            email=email, reason=SuppressionReason.HARD_BOUNCE, bounce_subtype=subtype
        )
    return ClassifiedEvent(email=email, reason=None, bounce_subtype=subtype)


def _first_recipient(data: dict[str, object]) -> str | None:
    to = data.get("to")
    if isinstance(to, str) and to.strip():
        return normalize_email(to)
    if isinstance(to, list):
        for entry in to:
            if isinstance(entry, str) and entry.strip():
                return normalize_email(entry)
    email = data.get("email")
    if isinstance(email, str) and email.strip():
        return normalize_email(email)
    return None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
