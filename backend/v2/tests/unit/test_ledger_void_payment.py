"""Domain rules for voiding a ledger payment (#619).

Invoices have had ``void_invoice`` since the ledger was built; payments had no
equivalent, so a test/erroneous manual payment could only be "undone" (which
erases the paid fields and re-opens the row for a fresh mark-paid) or left on
the books forever. ``void_payment`` is the mirror image: a terminal, audited,
non-destructive state.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.domain.ledger import LedgerPayment, void_payment

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


def _payment(**overrides: object) -> LedgerPayment:
    base: dict[str, object] = {
        "payment_id": "pay-619",
        "academy_id": "acad-1",
        "parent_id": "parent-1",
        "amount_cents": 10_000,
        "unapplied_amount_cents": 0,
        "currency": "usd",
        "status": "succeeded",
        "payment_method": "cash",
        "paid_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return LedgerPayment(**base)  # type: ignore[arg-type]


def test_void_payment_stamps_reason_actor_and_time() -> None:
    result = void_payment(_payment(), reason="test payment", voided_by="admin1", now=NOW)

    assert result.status == "voided"
    assert result.void_reason == "test payment"
    assert result.voided_at == NOW
    assert result.voided_by == "admin1"


def test_void_payment_strands_no_spendable_funds() -> None:
    """A voided payment must not keep money an allocator could still spend."""
    result = void_payment(
        _payment(unapplied_amount_cents=10_000), reason="test", voided_by="admin1", now=NOW
    )

    assert result.unapplied_amount_cents == 0
    # The original amount stays on the row: this is a soft void, not a delete.
    assert result.amount_cents == 10_000


def test_void_payment_allowed_for_pending_and_failed_rows() -> None:
    for status in ("pending", "failed"):
        result = void_payment(_payment(status=status), reason="t", voided_by="a", now=NOW)
        assert result.status == "voided"


def test_void_payment_raises_when_already_voided() -> None:
    already = void_payment(_payment(), reason="t", voided_by="a", now=NOW)
    with pytest.raises(ValueError, match="already voided"):
        void_payment(already, reason="t", voided_by="a", now=NOW)


def test_void_payment_refuses_settled_stripe_funds() -> None:
    """Real Stripe money is returned through the refund flow, never voided."""
    stripe_paid = _payment(status="succeeded", stripe_payment_intent_id="pi_live_1")
    with pytest.raises(ValueError, match="refund"):
        void_payment(stripe_paid, reason="t", voided_by="a", now=NOW)


def test_void_payment_allows_unsettled_stripe_rows() -> None:
    """An EXPIRED/failed checkout row holds no funds — freely voidable (#619)."""
    expired = _payment(status="failed", stripe_payment_intent_id="pi_test_1", paid_at=None)
    assert void_payment(expired, reason="t", voided_by="a", now=NOW).status == "voided"
