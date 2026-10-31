"""PaymentDispute — a chargeback a parent's bank opened against one charge.

Direct charges settle on the academy's own connected Stripe account, so a
dispute is the ACADEMY's: Stripe debits the disputed amount (and its dispute
fee) from that account, and the academy answers it in its own Stripe
dashboard. The app only records what happened, surfaces it on Billing Health
and tells the academy owner. It never creates a platform-side adjustment and
never moves money in the ledger: a won dispute returns the funds, a lost one
is the academy's loss, and neither is the platform's.

The house academy's disputes land on the platform account (its charges do)
and are recorded the same way.

Pure domain: parsing Stripe's dispute object and the "a late event never
reopens a closed dispute" merge rule live here so every caller agrees.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Stripe dispute statuses after which nothing more happens. ``warning_closed``
#: is an inquiry that closed without becoming a chargeback.
CLOSED_DISPUTE_STATUSES: frozenset[str] = frozenset({"won", "lost", "warning_closed"})

DisputeNoticeKind = Literal["opened", "closed"]


class PaymentDispute(BaseModel):
    """One Stripe dispute as the academy's books see it."""

    model_config = ConfigDict(frozen=True)

    dispute_id: str
    academy_id: str
    #: The app's payment row the disputed charge settled, when one matched.
    payment_id: str | None = None
    stripe_payment_intent_id: str | None = None
    stripe_charge_id: str | None = None
    #: The connected account the disputed charge lives on; None = platform.
    stripe_account_id: str | None = None
    amount_cents: int = Field(default=0, ge=0)
    currency: str = "usd"
    reason: str = "general"
    #: Stripe's raw dispute status (``needs_response``, ``won``, ...).
    status: str = "needs_response"
    #: Set once the dispute closes: ``won``, ``lost`` or ``warning_closed``.
    outcome: str | None = None
    evidence_due_by: datetime | None = None
    opened_at: datetime
    closed_at: datetime | None = None
    updated_at: datetime

    @property
    def is_open(self) -> bool:
        return self.outcome is None


def dispute_from_stripe(
    obj: dict[str, Any],
    *,
    academy_id: str,
    stripe_account_id: str | None,
    payment_id: str | None,
    now: datetime,
) -> PaymentDispute:
    """Build a :class:`PaymentDispute` from Stripe's dispute object."""
    status = str(obj.get("status") or "needs_response")
    closed = status in CLOSED_DISPUTE_STATUSES
    evidence = obj.get("evidence_details")
    due_by = evidence.get("due_by") if isinstance(evidence, dict) else None
    return PaymentDispute(
        dispute_id=str(obj["id"]),
        academy_id=academy_id,
        payment_id=payment_id,
        stripe_payment_intent_id=_opt_id(obj.get("payment_intent")),
        stripe_charge_id=_opt_id(obj.get("charge")),
        stripe_account_id=stripe_account_id,
        amount_cents=max(0, int(obj.get("amount") or 0)),
        currency=str(obj.get("currency") or "usd").lower(),
        reason=str(obj.get("reason") or "general"),
        status=status,
        outcome=status if closed else None,
        evidence_due_by=_from_epoch(due_by),
        opened_at=_from_epoch(obj.get("created")) or now,
        closed_at=now if closed else None,
        updated_at=now,
    )


def merge_dispute(existing: PaymentDispute | None, incoming: PaymentDispute) -> PaymentDispute:
    """The record to store when ``incoming`` arrives on top of ``existing``.

    Stripe does not promise event order, so a ``charge.dispute.created``
    delivered after the ``closed`` one must not reopen the dispute, and the
    first-seen facts (``opened_at``, the matched payment) are kept.
    """
    if existing is None:
        return incoming
    if not existing.is_open and incoming.is_open:
        return existing
    return incoming.model_copy(
        update={
            "opened_at": existing.opened_at,
            "payment_id": incoming.payment_id or existing.payment_id,
            "stripe_account_id": incoming.stripe_account_id or existing.stripe_account_id,
            "closed_at": existing.closed_at or incoming.closed_at,
        }
    )


def _opt_id(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("id")
    return str(value) if value else None


def _from_epoch(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None
