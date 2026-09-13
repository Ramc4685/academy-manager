"""A freshly minted invoice reaches the family on the same run (#659).

Before this, generation and delivery were fully decoupled: the monthly run
minted invoices and the separate ``SendGeneratedInvoices`` sweep mailed them
on its own cadence, so a parent could be charged before ever being billed.
Owner decision 2026-09-12: notify on mint, non-autopay families only —
autopay families keep getting the pre-charge notice instead of a pay link,
which is exactly what the sweep this hook reuses already guarantees.
"""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    GenerateMonthlyPayments,
    GenerateMonthlyPaymentsCommand,
    GenerateMonthlyPaymentsResult,
)

pytestmark = pytest.mark.asyncio


class _FakePayments:
    def __init__(self, *, created: int) -> None:
        self._created = created
        self.periods: list[str] = []

    async def generate_monthly_payments(self, period: str) -> GenerateMonthlyPaymentsResult:
        self.periods.append(period)
        return GenerateMonthlyPaymentsResult(created=self._created)


async def test_generation_notifies_families_on_mint() -> None:
    payments = _FakePayments(created=3)
    notified: list[str] = []

    async def notify(period: str) -> None:
        notified.append(period)

    result = await GenerateMonthlyPayments(payments=payments, notify_minted=notify).execute(
        GenerateMonthlyPaymentsCommand(period="2026-09")
    )

    assert result.created == 3
    assert notified == ["2026-09"]


async def test_generation_does_not_notify_when_nothing_was_minted() -> None:
    payments = _FakePayments(created=0)
    notified: list[str] = []

    async def notify(period: str) -> None:
        notified.append(period)

    await GenerateMonthlyPayments(payments=payments, notify_minted=notify).execute(
        GenerateMonthlyPaymentsCommand(period="2026-09")
    )

    assert notified == []


async def test_a_failed_notification_never_fails_the_billing_run() -> None:
    """Generation is the money-critical half; email is best effort."""
    payments = _FakePayments(created=2)

    async def notify(period: str) -> None:
        raise RuntimeError("resend is down")

    result = await GenerateMonthlyPayments(payments=payments, notify_minted=notify).execute(
        GenerateMonthlyPaymentsCommand(period="2026-09")
    )

    assert result.created == 2


async def test_unwired_notifier_leaves_generation_unchanged() -> None:
    payments = _FakePayments(created=1)

    result = await GenerateMonthlyPayments(payments=payments).execute(
        GenerateMonthlyPaymentsCommand(period="2026-09")
    )

    assert result.created == 1
    assert payments.periods == ["2026-09"]
