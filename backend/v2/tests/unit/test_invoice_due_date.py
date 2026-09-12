"""Manual invoices must take their due date from Billing rules (#739).

The monthly generator dates its invoices ``today + invoice_due_days``; before
this helper existed every hand-billing path hard-coded 7, so an academy that
set 10 got two different due dates inside one month and month close reported
``charge_on_varies``.
"""

from __future__ import annotations

from datetime import date

from backend.v2.contexts.billing.application.use_cases.invoice_due_date import (
    DEFAULT_INVOICE_DUE_DAYS,
    invoice_due_days,
    resolve_invoice_due_date,
)

TODAY = date(2026, 6, 1)


class _Settings:
    def __init__(self, value: object) -> None:
        self.invoice_due_days = value


class _Reader:
    def __init__(self, settings: object) -> None:
        self._settings = settings

    async def get(self) -> object:
        return self._settings


class _BrokenReader:
    async def get(self) -> object:
        raise RuntimeError("mongo is down")


async def test_explicit_due_date_wins_over_the_configured_window() -> None:
    picked = date(2026, 6, 30)
    assert (
        await resolve_invoice_due_date(_Reader(_Settings(14)), due_date=picked, today=TODAY)
        == picked
    )


async def test_omitted_due_date_comes_from_the_academys_window() -> None:
    assert await resolve_invoice_due_date(
        _Reader(_Settings(14)), due_date=None, today=TODAY
    ) == date(2026, 6, 15)


async def test_a_configured_zero_means_due_today_not_the_default() -> None:
    assert (
        await resolve_invoice_due_date(_Reader(_Settings(0)), due_date=None, today=TODAY) == TODAY
    )


async def test_no_settings_reader_falls_back_to_the_model_default() -> None:
    assert await resolve_invoice_due_date(None, due_date=None, today=TODAY) == date(2026, 6, 8)
    assert DEFAULT_INVOICE_DUE_DAYS == 7


async def test_an_explicit_null_window_falls_back_rather_than_due_today() -> None:
    """`int(value or 0)` here would hand the dunning ladder a same-day charge."""
    assert await invoice_due_days(_Reader(_Settings(None))) == DEFAULT_INVOICE_DUE_DAYS


async def test_unreadable_settings_degrade_to_the_default() -> None:
    assert await invoice_due_days(_BrokenReader()) == DEFAULT_INVOICE_DUE_DAYS
