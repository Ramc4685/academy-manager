"""PaymentDispute: parsing Stripe's dispute object and the merge rule that a
late event never reopens a closed dispute."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.billing.domain.payment_dispute import (
    dispute_from_stripe,
    merge_dispute,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def _obj(status: str) -> dict:
    return {
        "id": "dp_1",
        "amount": 12_500,
        "currency": "USD",
        "charge": "ch_1",
        "payment_intent": {"id": "pi_1"},
        "reason": "product_not_received",
        "status": status,
        "created": 1_790_000_000,
        "evidence_details": {"due_by": 1_790_900_000},
    }


def _parse(status: str, *, now: datetime = NOW, payment_id: str | None = "pay-1"):
    return dispute_from_stripe(
        _obj(status), academy_id="acad", stripe_account_id="acct_1", payment_id=payment_id, now=now
    )


def test_parses_an_open_dispute() -> None:
    dispute = _parse("needs_response")
    assert dispute.is_open and dispute.outcome is None and dispute.closed_at is None
    assert dispute.stripe_payment_intent_id == "pi_1"
    assert dispute.stripe_charge_id == "ch_1"
    assert dispute.amount_cents == 12_500
    assert dispute.currency == "usd"
    assert dispute.opened_at == datetime.fromtimestamp(1_790_000_000, tz=UTC)
    assert dispute.evidence_due_by == datetime.fromtimestamp(1_790_900_000, tz=UTC)


def test_closed_statuses_set_the_outcome() -> None:
    for status in ("won", "lost", "warning_closed"):
        dispute = _parse(status)
        assert dispute.outcome == status and not dispute.is_open
        assert dispute.closed_at == NOW


def test_close_after_open_keeps_first_seen_facts() -> None:
    opened = _parse("needs_response")
    closed = _parse("won", now=LATER, payment_id=None)
    merged = merge_dispute(opened, closed)
    assert merged.outcome == "won"
    assert merged.opened_at == opened.opened_at
    assert merged.payment_id == "pay-1"
    assert merged.closed_at == LATER


def test_late_open_event_never_reopens_a_closed_dispute() -> None:
    closed = _parse("lost")
    late_open = _parse("needs_response", now=LATER)
    assert merge_dispute(closed, late_open) == closed


def test_first_event_is_stored_as_is() -> None:
    dispute = _parse("under_review")
    assert merge_dispute(None, dispute) == dispute
