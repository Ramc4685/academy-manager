"""#1033: the monthly-generation ops digest counts every invoice email once.

The notify-on-mint pass (#659) sends first, inside generation; the scheduler's
sweep afterwards only finds what is still undelivered. Both outcomes now feed
the same counters, and a whole-pass failure is an explicit signal, including
on a retry-only tick.

These tests compose the real ``GenerateMonthlyPayments`` (with its mint hook)
and the real ``_run_monthly_invoice_generation``; only the ledger and the
send pass are faked, and the fake send pass behaves like
``SendGeneratedInvoices``: it selects undelivered invoices only, so an invoice
sent once is never selected (or counted) again.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    GenerateMonthlyPayments,
    GenerateMonthlyPaymentsCommand,
    GenerateMonthlyPaymentsResult,
)
from backend.v2.contexts.billing.application.use_cases.send_generated_invoices import (
    SendGeneratedInvoicesResult,
)
from backend.v2.main import _monthly_generation_retry_reason, _run_monthly_invoice_generation
from backend.v2.shared.tenancy.context import current_academy_id
from backend.v2.tests.unit.test_scheduler_academies import (
    _FakeDb,
    _FakeSettings,
    _seed_history,
    _settings_getter,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 5, 3, 0)


class _Ledger:
    """Per-academy invoices: kind is "pay_link" or "autopay"; delivered flips once."""

    def __init__(self) -> None:
        self.invoices: dict[str, list[dict[str, object]]] = {}
        self.to_mint: dict[str, list[str]] = {}

    async def generate_monthly_payments(self, period: str) -> GenerateMonthlyPaymentsResult:
        academy = current_academy_id()
        kinds = self.to_mint.pop(academy, [])
        self.invoices.setdefault(academy, []).extend(
            {"kind": kind, "delivered": False, "period": period} for kind in kinds
        )
        return GenerateMonthlyPaymentsResult(created=len(kinds))


class _SendPass:
    """Like SendGeneratedInvoices: undelivered only. ``fail_next`` makes the
    next N per-invoice sends fail; ``raise_next`` makes the next pass raise."""

    def __init__(self, ledger: _Ledger) -> None:
        self.ledger = ledger
        self.fail_next: dict[str, int] = {}
        self.raise_next: dict[str, int] = {}
        self.deliveries: list[tuple[str, int]] = []

    async def __call__(self, period: str) -> SendGeneratedInvoicesResult:
        academy = current_academy_id()
        if self.raise_next.get(academy, 0):
            self.raise_next[academy] -= 1
            raise RuntimeError("email provider down")
        emailed = failed = notified = 0
        for index, invoice in enumerate(self.ledger.invoices.get(academy, [])):
            if invoice["delivered"] or invoice["period"] != period:
                continue
            if self.fail_next.get(academy, 0):
                self.fail_next[academy] -= 1
                failed += 1
                continue
            invoice["delivered"] = True
            self.deliveries.append((academy, index))
            if invoice["kind"] == "autopay":
                notified += 1
            else:
                emailed += 1
        return SendGeneratedInvoicesResult(
            emailed=emailed, email_failed=failed, autopay_notified=notified
        )


def _wire(academies: list[str]) -> tuple[_FakeDb, _Ledger, _SendPass, object]:
    db = _FakeDb()
    for academy in academies:
        _seed_history(db, academy, "2026-08")
    ledger = _Ledger()
    send = _SendPass(ledger)
    use_case = GenerateMonthlyPayments(payments=ledger, notify_minted=send)  # type: ignore[arg-type]

    async def generate(period: str) -> GenerateMonthlyPaymentsResult:
        return await use_case.execute(GenerateMonthlyPaymentsCommand(period=period))

    return db, ledger, send, generate


async def _run(db, generate, send, academies: list[str]) -> dict[str, int]:
    return await _run_monthly_invoice_generation(
        db=db,
        academy_ids=academies,
        get_billing_settings=_settings_getter({a: _FakeSettings(1) for a in academies}),
        generate=generate,
        now=NOW,
        send_invoices=send,
    )


async def test_all_sent_on_mint_counts_ten_emailed_not_zero() -> None:
    db, ledger, send, generate = _wire(["a"])
    ledger.to_mint["a"] = ["pay_link"] * 10

    totals = await _run(db, generate, send, ["a"])

    assert totals["created"] == 10
    assert totals["invoices_emailed"] == 10
    assert totals["invoice_emails_failed"] == 0
    assert len(send.deliveries) == 10  # the empty sweep resent nothing
    assert _monthly_generation_retry_reason(totals) is None


async def test_autopay_notices_are_counted_apart_from_invoice_emails() -> None:
    db, ledger, send, generate = _wire(["a"])
    ledger.to_mint["a"] = ["pay_link"] * 6 + ["autopay"] * 4

    totals = await _run(db, generate, send, ["a"])

    assert totals["invoices_emailed"] == 6
    assert totals["invoice_autopay_notices_sent"] == 4


async def test_partial_mint_failures_retried_by_the_sweep_count_each_outcome_once() -> None:
    db, ledger, send, generate = _wire(["a"])
    ledger.to_mint["a"] = ["pay_link"] * 10
    send.fail_next["a"] = 2  # two fail on mint; the sweep delivers them

    totals = await _run(db, generate, send, ["a"])

    assert totals["invoices_emailed"] == 10
    assert totals["invoice_emails_failed"] == 2  # the earlier failure stays visible
    assert len(send.deliveries) == 10


async def test_a_mint_pass_that_raises_is_flagged_and_the_sweep_still_delivers() -> None:
    db, ledger, send, generate = _wire(["a"])
    ledger.to_mint["a"] = ["pay_link"] * 3
    send.raise_next["a"] = 1  # the mint pass raises; the sweep runs clean

    totals = await _run(db, generate, send, ["a"])

    assert totals["created"] == 3  # generation success is preserved
    assert totals["invoice_mint_send_failed"] == 1
    assert totals["invoices_emailed"] == 3
    assert totals["invoice_email_pass_failed"] == 0


async def test_a_retry_only_tick_whose_sweep_raises_is_an_explicit_failure() -> None:
    db, _ledger, send, generate = _wire(["a"])
    _seed_history(db, "a", "2026-09")  # already generated: retry-only tick
    send.raise_next["a"] = 1

    totals = await _run(db, generate, send, ["a"])

    assert totals["academy_count"] == 0
    assert totals["invoice_email_pass_failed"] == 1
    assert totals["invoices_emailed"] == 0
    assert _monthly_generation_retry_reason(totals) is not None


async def test_two_academies_in_one_cycle_sum_without_crossing() -> None:
    db, ledger, send, generate = _wire(["a", "b"])
    ledger.to_mint["a"] = ["pay_link"] * 2
    ledger.to_mint["b"] = ["autopay"] * 3

    totals = await _run(db, generate, send, ["a", "b"])

    assert (totals["invoices_emailed"], totals["invoice_autopay_notices_sent"]) == (2, 3)
    assert sorted({academy for academy, _ in send.deliveries}) == ["a", "b"]
