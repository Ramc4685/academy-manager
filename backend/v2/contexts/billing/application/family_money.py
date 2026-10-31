"""What a family owes: the one rule, shared by the Billing tab and the family index.

Family billing spec (``docs/superpowers/specs/2026-09-05-family-billing-design.md``
§3.1) defines the header balance as the sum of ``balance_due_cents`` over the
family's open (chargeable) invoices. The People CRM family index
(``docs/design/people-crm/engineering-spec.md`` §3.2) shows the same number
for every family at once. Both call :func:`open_balance`, so the list and the
Billing tab cannot drift apart; nothing else may re-derive it.

Pure: no Mongo, no clock. The batched reads live in
``infrastructure/family_money_read_model.py`` (every family) and
``infrastructure/family_billing_read_model.py`` (one family).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from backend.v2.contexts.billing.application.autopay_eligibility import (
    CHARGEABLE_INVOICE_STATUSES,
)


class _InvoiceMoney(Protocol):
    @property
    def status(self) -> str: ...

    @property
    def balance_due_cents(self) -> int: ...


class _DatedInvoiceMoney(_InvoiceMoney, Protocol):
    @property
    def due_date(self) -> date | None: ...


@dataclass(frozen=True)
class OpenInvoiceMoney:
    """The three invoice facts the family money summary reads."""

    status: str
    balance_due_cents: int
    due_date: date | None = None


def is_open_invoice(status: str) -> bool:
    """Chargeable statuses are the open ones; the dunning worker agrees."""
    return status in CHARGEABLE_INVOICE_STATUSES


def open_balance(invoices: Iterable[_InvoiceMoney]) -> tuple[int, int]:
    """``(balance_cents, open_invoice_count)`` over the open invoices."""
    balance = 0
    count = 0
    for inv in invoices:
        if is_open_invoice(inv.status):
            balance += inv.balance_due_cents
            count += 1
    return balance, count


def registration_state(*, has_card: bool | None, last_invited_at: datetime | None) -> str:
    """Billing registration: a saved card, an invite sent, or neither."""
    if has_card:
        return "registered"
    if last_invited_at is not None:
        return "invited"
    return "not_invited"


@dataclass(frozen=True)
class FamilyMoneySummary:
    """One family's money at a glance, as the family index shows it.

    ``balance_cents`` and ``open_invoice_count`` are exactly the Billing tab
    header's numbers. "Overdue" is an open invoice with money still due whose
    due date is before the academy's today (People CRM spec §3.2, the Overdue
    chip). ``last_failed_payment_at`` is the newest failed charge attempt on
    an invoice that is still open. ``card_on_file`` is None when the customer
    row could not be read.
    """

    balance_cents: int = 0
    open_invoice_count: int = 0
    overdue_invoice_count: int = 0
    overdue_cents: int = 0
    oldest_overdue_due_on: date | None = None
    last_failed_payment_at: datetime | None = None
    card_on_file: bool | None = False
    registration: str = "not_invited"


def summarize_family_money(
    invoices: Iterable[_DatedInvoiceMoney],
    *,
    today: date,
    last_failed_payment_at: datetime | None = None,
    has_card: bool | None = False,
    last_invited_at: datetime | None = None,
) -> FamilyMoneySummary:
    rows = list(invoices)
    balance, count = open_balance(rows)
    overdue = [
        inv
        for inv in rows
        if is_open_invoice(inv.status)
        and inv.balance_due_cents > 0
        and inv.due_date is not None
        and inv.due_date < today
    ]
    due_dates = [inv.due_date for inv in overdue if inv.due_date is not None]
    return FamilyMoneySummary(
        balance_cents=balance,
        open_invoice_count=count,
        overdue_invoice_count=len(overdue),
        overdue_cents=sum(inv.balance_due_cents for inv in overdue),
        oldest_overdue_due_on=min(due_dates) if due_dates else None,
        last_failed_payment_at=last_failed_payment_at,
        card_on_file=has_card,
        registration=registration_state(has_card=has_card, last_invited_at=last_invited_at),
    )
