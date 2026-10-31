"""Record a Stripe dispute (``charge.dispute.created`` / ``charge.dispute.closed``).

A direct charge lives on the academy's own connected account, so its dispute
is the academy's: Stripe takes the disputed amount and fee from that account
and the academy responds in its own dashboard. This use case therefore only
keeps the books honest and tells the owner:

1. store the dispute (``payment_disputes``), never reopening a closed one;
2. mirror its state onto the disputed payment row (dispute id, status,
   reason, amount, outcome) without touching any money field;
3. ask for exactly one owner e-mail per (dispute, opened|closed) through the
   outbox, whose unique ``event_id`` makes redelivery and replay harmless.

It creates no refund, credit, write-off or any other platform-side adjustment.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.application.ports import (
    LedgerRepository,
    PaymentDisputeRepository,
    PaymentRepository,
)
from backend.v2.contexts.billing.domain.errors import StripeAccountMismatch
from backend.v2.contexts.billing.domain.events import (
    PaymentDisputeNoticePayload,
    PaymentDisputeNoticeRequested,
)
from backend.v2.contexts.billing.domain.payment_dispute import (
    PaymentDispute,
    dispute_from_stripe,
    merge_dispute,
)
from backend.v2.shared.events import Outbox


def dispute_notice_event_id(*, academy_id: str, dispute_id: str, kind: str) -> str:
    """Deterministic outbox id: one notice per (academy, dispute, kind)."""
    return f"dispute-notice:{academy_id}:{dispute_id}:{kind}"


class RecordPaymentDispute:
    def __init__(
        self,
        *,
        disputes: PaymentDisputeRepository,
        payments: PaymentRepository,
        ledger: LedgerRepository | None,
        outbox: Outbox,
        academy_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._disputes = disputes
        self._payments = payments
        self._ledger = ledger
        self._outbox = outbox
        self._academy_id = academy_id
        self._now = clock

    async def execute(
        self, dispute_obj: dict[str, Any], *, stripe_account_id: str | None
    ) -> PaymentDispute:
        dispute_id = str(dispute_obj.get("id") or "")
        if not dispute_id:
            raise ValueError("dispute event carries no dispute id")
        payment_id, payment_account = await self._match_payment(dispute_obj)
        if payment_account and stripe_account_id and payment_account != stripe_account_id:
            raise StripeAccountMismatch(
                f"dispute {dispute_id} arrived for account {stripe_account_id} but "
                f"payment {payment_id} lives on {payment_account}"
            )
        incoming = dispute_from_stripe(
            dispute_obj,
            academy_id=self._academy_id,
            stripe_account_id=stripe_account_id or payment_account,
            payment_id=payment_id,
            now=self._now(),
        )
        existing = await self._disputes.get(dispute_id)
        merged = merge_dispute(existing, incoming)
        await self._disputes.save(merged)
        await self._disputes.stamp_payment(merged)
        await self._request_notice(merged)
        return merged

    async def _match_payment(self, dispute_obj: dict[str, Any]) -> tuple[str | None, str | None]:
        pi = dispute_obj.get("payment_intent")
        pi_id = str(pi.get("id") if isinstance(pi, dict) else pi or "")
        if not pi_id:
            return None, None
        payment = await self._payments.get_by_stripe_pi(pi_id)
        if payment is not None:
            return payment.payment_id, payment.stripe_account_id
        if self._ledger is not None:
            ledger_payment = await self._ledger.get_payment_by_stripe_payment_intent_id(pi_id)
            if ledger_payment is not None:
                return ledger_payment.payment_id, ledger_payment.stripe_account_id
        return None, None

    async def _request_notice(self, dispute: PaymentDispute) -> None:
        kind = "opened" if dispute.is_open else "closed"
        event = PaymentDisputeNoticeRequested(
            event_id=dispute_notice_event_id(
                academy_id=dispute.academy_id, dispute_id=dispute.dispute_id, kind=kind
            ),
            aggregate_id=dispute.dispute_id,
            academy_id=dispute.academy_id,
            payload=PaymentDisputeNoticePayload(
                dispute_id=dispute.dispute_id,
                kind=kind,
                payment_id=dispute.payment_id,
                amount_cents=dispute.amount_cents,
                currency=dispute.currency,
                reason=dispute.reason,
                status=dispute.status,
                outcome=dispute.outcome,
                evidence_due_by=dispute.evidence_due_by,
            ),
        )
        try:
            await self._outbox.append(event)
        except DuplicateKeyError:
            # Already requested for this (dispute, kind): exactly-once.
            return
