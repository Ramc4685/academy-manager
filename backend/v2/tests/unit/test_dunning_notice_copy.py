"""Dunning notices carry a pay-now button and say what the parent must do (L1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.composition.email_adapters import InvoiceEmailAdapter
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.unit.test_invoice_email_naming import (
    _FakeAcademies,
    _FakeMemberships,
    _FakeSender,
    _FakeUsers,
)

pytestmark = pytest.mark.asyncio


async def _send(**overrides) -> dict:
    sender = _FakeSender()
    seen: list[str] = []

    async def pay_link(academy_id: str) -> tuple[str | None, str]:
        seen.append(academy_id)
        return "https://blno.example.com/parent/payments", "BLNO"

    adapter = InvoiceEmailAdapter(
        memberships=_FakeMemberships(),
        users=_FakeUsers(),
        academies=_FakeAcademies(),
        sender=sender,
        pay_link=pay_link,
    )
    kwargs = {
        "parent_id": "parent-1",
        "invoice_id": "inv-1",
        "period": "2026-09",
        "balance_due_cents": 7_000,
        "currency": "usd",
        "attempt_no": 1,
        "terminal": False,
        **overrides,
    }
    with tenant_scope("acad"):
        await adapter.send_dunning_notice(**kwargs)
    assert seen == ["acad"]
    return sender.calls[0]


async def test_failed_card_notice_has_pay_button_and_retry_date() -> None:
    call = await _send(next_attempt_at=datetime(2026, 9, 4, 14, tzinfo=UTC))
    assert "https://blno.example.com/parent/payments?pay=inv-1" in call["body"]
    assert "Pay now or update your card" in call["body"]
    assert "September 4" in call["body"]


async def test_no_saved_method_notice_asks_for_a_card_or_bank() -> None:
    call = await _send(attempt_no=0, failure_code="no_saved_payment_method")
    assert call["subject"].startswith("Add a payment method")
    assert "no saved card or bank account" in call["body"]
    assert "?pay=inv-1" in call["body"]


async def test_bank_retry_notice_names_the_next_debit() -> None:
    call = await _send(
        bank_debit=True,
        failure_code="insufficient_funds",
        next_attempt_at=datetime(2026, 9, 7, 14, tzinfo=UTC),
    )
    assert call["subject"].startswith("Bank payment returned")
    assert "September 7" in call["body"]


async def test_terminal_bank_notice_says_autopay_is_paused() -> None:
    call = await _send(bank_debit=True, terminal=True, failure_code="bank_account_closed")
    assert call["subject"].startswith("Autopay paused")
    assert "re-link your bank account or pay by card" in call["body"]
    assert "?pay=inv-1" in call["body"]


async def _receipt(**overrides) -> dict:
    sender = _FakeSender()
    adapter = InvoiceEmailAdapter(
        memberships=_FakeMemberships(),
        users=_FakeUsers(),
        academies=_FakeAcademies(),
        sender=sender,
    )
    kwargs = {
        "parent_id": "parent-1",
        "invoice_id": "inv-1",
        "period": "2026-09",
        "amount_cents": 7_000,
        "currency": "usd",
        **overrides,
    }
    with tenant_scope("acad"):
        await adapter.send_autopay_receipt(**kwargs)
    return sender.calls[0]


async def test_bank_receipt_says_the_bank_payment_cleared() -> None:
    call = await _receipt(bank_debit=True)
    assert "bank payment" in call["body"]
    assert "saved card" not in call["body"]


async def test_checkout_balance_receipt_needs_no_invoice() -> None:
    call = await _receipt(invoice_id=None, period=None, autopay=False)
    assert "We received your payment" in call["body"]
    assert "account balance" in call["subject"]
