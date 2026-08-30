"""Unit tests for Phase 2A ledger domain ops."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    LedgerInvoice,
    LedgerPayment,
    add_line,
    allocate_payment_to_invoice,
    finalize,
    recompute_totals,
    record_delivery,
    void_invoice,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
DUE = date(2026, 6, 30)


def _invoice(
    *,
    status="open",
    subtotal_cents=10_000,
    discount_cents=0,
    total_cents=10_000,
    balance_due_cents=10_000,
) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id="inv-1",
        academy_id="acad-1",
        parent_id="parent-1",
        student_id="student-1",
        enrollment_id="enroll-1",
        period="2026-06",
        status=status,
        subtotal_cents=subtotal_cents,
        discount_cents=discount_cents,
        total_cents=total_cents,
        balance_due_cents=balance_due_cents,
        currency="usd",
        due_date=DUE,
        created_at=NOW,
        updated_at=NOW,
    )


def _line(amount_cents: int = 5_000, *, line_id: str = "line-1") -> InvoiceLine:
    return InvoiceLine(
        line_id=line_id,
        academy_id="acad-1",
        invoice_id="inv-1",
        line_type="tuition",
        description="Tuition",
        quantity=1,
        unit_amount_cents=amount_cents,
        amount_cents=amount_cents,
        created_at=NOW,
    )


def _payment(amount_cents: int = 5_000) -> LedgerPayment:
    return LedgerPayment(
        payment_id="pay-1",
        academy_id="acad-1",
        parent_id="parent-1",
        amount_cents=amount_cents,
        unapplied_amount_cents=amount_cents,
        currency="usd",
        status="succeeded",
        paid_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


# ---------------------------------------------------------------------------
# recompute_totals
# ---------------------------------------------------------------------------


def test_recompute_totals_sums_lines() -> None:
    inv = _invoice(subtotal_cents=0, total_cents=0, balance_due_cents=0)
    lines = [_line(3_000, line_id="l1"), _line(7_000, line_id="l2")]
    result = recompute_totals(inv, lines)
    assert result.subtotal_cents == 10_000


def test_recompute_totals_applies_discount() -> None:
    inv = _invoice(subtotal_cents=0, discount_cents=1_000, total_cents=0, balance_due_cents=0)
    lines = [_line(10_000)]
    result = recompute_totals(inv, lines)
    assert result.total_cents == 9_000


def test_recompute_totals_preserves_allocated_amount() -> None:
    # Invoice already has 4000 allocated (total=10000, balance=6000)
    inv = _invoice(total_cents=10_000, balance_due_cents=6_000)
    lines = [_line(10_000)]
    result = recompute_totals(inv, lines)
    # allocated = 10000 - 6000 = 4000; new_total = 10000; balance = 10000 - 4000 = 6000
    assert result.balance_due_cents == 6_000
    assert result.status == "partially_paid"


def test_recompute_totals_draft_status_unchanged() -> None:
    inv = _invoice(status="draft", subtotal_cents=0, total_cents=0, balance_due_cents=0)
    lines = [_line(5_000)]
    result = recompute_totals(inv, lines)
    # draft status must not be changed by recompute
    assert result.status == "draft"


def test_recompute_totals_paid_when_balance_zero() -> None:
    inv = _invoice(status="open", total_cents=5_000, balance_due_cents=5_000)
    lines = [_line(5_000)]
    # Simulate full allocation already done: total=5000, balance=0
    inv_fully_allocated = inv.model_copy(update={"balance_due_cents": 0})
    result = recompute_totals(inv_fully_allocated, lines)
    assert result.status == "paid"


def test_recompute_totals_uses_explicit_allocated_cents() -> None:
    # P0-2: when the caller passes the true summed allocations, balance must derive
    # from it — NOT from the (possibly stale) total_cents - balance_due_cents inference.
    # Stale fields claim 9000 allocated (total=10000, balance=1000); the real ledger
    # has only 3000 allocated, so the recomputed balance must be 10000 - 3000 = 7000.
    inv = _invoice(total_cents=10_000, balance_due_cents=1_000)
    lines = [_line(10_000)]
    result = recompute_totals(inv, lines, allocated_cents=3_000)
    assert result.balance_due_cents == 7_000
    assert result.status == "partially_paid"


def test_add_line_threads_explicit_allocated_cents() -> None:
    # add_line must forward allocated_cents so the post-add balance reflects real allocations.
    inv = _invoice(subtotal_cents=5_000, total_cents=5_000, balance_due_cents=0, status="open")
    existing = [_line(5_000, line_id="l1")]
    new_line = _line(3_000, line_id="l2")
    updated, _lines = add_line(inv, existing, new_line, now=NOW, allocated_cents=5_000)
    # total = 8000, allocated = 5000 -> balance 3000
    assert updated.total_cents == 8_000
    assert updated.balance_due_cents == 3_000
    assert updated.status == "partially_paid"


# ---------------------------------------------------------------------------
# add_line
# ---------------------------------------------------------------------------


def test_add_line_allowed_in_draft() -> None:
    inv = _invoice(status="draft", subtotal_cents=0, total_cents=0, balance_due_cents=0)
    new_line = _line(2_000, line_id="line-new")
    updated_inv, updated_lines = add_line(inv, [], new_line, now=NOW)
    assert len(updated_lines) == 1
    assert updated_inv.subtotal_cents == 2_000


def test_add_line_allowed_in_open() -> None:
    inv = _invoice(status="open")
    new_line = _line(1_000, line_id="line-new")
    _updated_inv, updated_lines = add_line(inv, [], new_line, now=NOW)
    assert len(updated_lines) == 1


def test_add_line_rejected_in_paid() -> None:
    inv = _invoice(status="paid")
    new_line = _line(1_000, line_id="line-new")
    with pytest.raises(ValueError, match="paid"):
        add_line(inv, [], new_line, now=NOW)


def test_add_line_rejected_in_void() -> None:
    inv = _invoice(status="void")
    new_line = _line(1_000, line_id="line-new")
    with pytest.raises(ValueError, match="void"):
        add_line(inv, [], new_line, now=NOW)


# ---------------------------------------------------------------------------
# finalize
# ---------------------------------------------------------------------------


def test_finalize_draft_to_open() -> None:
    inv = _invoice(status="draft")
    result = finalize(inv, now=NOW)
    assert result.status == "open"
    assert result.finalized_at == NOW


def test_finalize_sets_finalized_at() -> None:
    inv = _invoice(status="draft")
    later = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
    result = finalize(inv, now=later)
    assert result.finalized_at == later


def test_finalize_raises_on_non_draft() -> None:
    for bad_status in ("open", "partially_paid", "paid", "void"):
        inv = _invoice(status=bad_status)
        with pytest.raises(ValueError, match="draft"):
            finalize(inv, now=NOW)


# ---------------------------------------------------------------------------
# void_invoice
# ---------------------------------------------------------------------------


def test_void_allowed_in_draft() -> None:
    inv = _invoice(status="draft")
    result = void_invoice(inv, reason="test", now=NOW)
    assert result.status == "void"


def test_void_allowed_in_open() -> None:
    inv = _invoice(status="open")
    result = void_invoice(inv, reason="test", now=NOW)
    assert result.status == "void"


def test_void_allowed_in_partially_paid() -> None:
    inv = _invoice(status="partially_paid", balance_due_cents=5_000)
    result = void_invoice(inv, reason="test", now=NOW)
    assert result.status == "void"


def test_void_raises_on_paid() -> None:
    inv = _invoice(status="paid", balance_due_cents=0)
    with pytest.raises(ValueError, match="paid"):
        void_invoice(inv, reason="test", now=NOW)


def test_void_raises_on_already_void() -> None:
    inv = _invoice(status="void")
    with pytest.raises(ValueError, match="void"):
        void_invoice(inv, reason="test", now=NOW)


# ---------------------------------------------------------------------------
# record_delivery
# ---------------------------------------------------------------------------


def test_record_delivery_updates_delivery_axis_only() -> None:
    inv = _invoice(status="open")
    result = record_delivery(inv, outcome="sent", now=NOW)
    assert result.delivery_status == "sent"
    assert result.status == "open"  # financial status unchanged
    assert result.sent_at == NOW
    assert result.last_sent_at == NOW


def test_record_delivery_failed() -> None:
    inv = _invoice(status="open")
    result = record_delivery(inv, outcome="delivery_failed", now=NOW)
    assert result.delivery_status == "delivery_failed"
    assert result.status == "open"


def test_record_delivery_sent_at_not_overwritten_on_resend() -> None:
    first_send = datetime(2026, 6, 1, tzinfo=UTC)
    inv = _invoice(status="open")
    first_result = record_delivery(inv, outcome="sent", now=first_send)
    second_send = datetime(2026, 6, 10, tzinfo=UTC)
    second_result = record_delivery(first_result, outcome="sent", now=second_send)
    assert second_result.sent_at == first_send  # first send preserved
    assert second_result.last_sent_at == second_send


def test_record_delivery_raises_on_draft() -> None:
    inv = _invoice(status="draft")
    with pytest.raises(ValueError, match="draft"):
        record_delivery(inv, outcome="sent", now=NOW)


# ---------------------------------------------------------------------------
# allocate_payment_to_invoice — regression guard
# ---------------------------------------------------------------------------


def test_allocate_partial_no_credit() -> None:
    inv = _invoice(status="open", total_cents=10_000, balance_due_cents=10_000)
    pay = _payment(4_000)
    result = allocate_payment_to_invoice(
        invoice=inv,
        payment=pay,
        lines=[_line(10_000)],
        requested_amount_cents=4_000,
        allocation_id="alloc-1",
        now=NOW,
    )
    assert result.invoice.balance_due_cents == 6_000
    assert result.invoice.status == "partially_paid"
    assert result.payment.unapplied_amount_cents == 0
    assert result.overpayment_credit is None


def test_allocate_overpayment_creates_credit() -> None:
    inv = _invoice(status="open", total_cents=10_000, balance_due_cents=10_000)
    pay = _payment(12_000)
    result = allocate_payment_to_invoice(
        invoice=inv,
        payment=pay,
        lines=[],
        requested_amount_cents=12_000,
        allocation_id="alloc-2",
        now=NOW,
    )
    assert result.invoice.status == "paid"
    assert result.overpayment_credit is not None
    assert result.overpayment_credit.amount_cents == 2_000


def test_allocate_zero_balance_invoice_mints_full_credit() -> None:
    """#533: ACH settles after a manual payment zeroed the invoice.

    The full settled amount must become an overpayment credit instead of the
    allocation raising and stranding the money as an unapplied payment.
    """
    inv = _invoice(status="paid", total_cents=10_000, balance_due_cents=0)
    pay = _payment(10_000)
    result = allocate_payment_to_invoice(
        invoice=inv,
        payment=pay,
        lines=[],
        requested_amount_cents=10_000,
        allocation_id="alloc-3",
        now=NOW,
    )
    assert result.allocation.amount_cents == 0
    assert result.invoice.status == "paid"
    assert result.invoice.balance_due_cents == 0
    assert result.payment.unapplied_amount_cents == 0
    assert result.overpayment_credit is not None
    assert result.overpayment_credit.amount_cents == 10_000
    assert result.overpayment_credit.source_type == "OVERPAYMENT"


def test_allocate_zero_balance_preserves_invoice_status() -> None:
    """A zero-allocation never rewrites the invoice status (e.g. a zero-total
    open invoice must not flip to paid just because a credit was minted)."""
    inv = _invoice(status="open", subtotal_cents=0, total_cents=0, balance_due_cents=0)
    pay = _payment(2_500)
    result = allocate_payment_to_invoice(
        invoice=inv,
        payment=pay,
        lines=[],
        requested_amount_cents=2_500,
        allocation_id="alloc-4",
        now=NOW,
    )
    assert result.invoice.status == "open"
    assert result.overpayment_credit is not None
    assert result.overpayment_credit.amount_cents == 2_500


def test_allocate_raises_when_payment_has_no_unapplied_money() -> None:
    inv = _invoice(status="paid", total_cents=10_000, balance_due_cents=0)
    pay = _payment(10_000).model_copy(update={"unapplied_amount_cents": 0})
    with pytest.raises(ValueError, match="no payable"):
        allocate_payment_to_invoice(
            invoice=inv,
            payment=pay,
            lines=[],
            requested_amount_cents=10_000,
            allocation_id="alloc-5",
            now=NOW,
        )
