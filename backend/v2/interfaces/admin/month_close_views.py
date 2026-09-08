"""Response models for ``GET /admin/reports/month-close``.

Field names follow spec §4.2 of
``docs/superpowers/specs/2026-09-07-month-close-design.md`` exactly. The read
model hands back plain dicts; these models shape them and drop anything the
spec does not name (``extra="ignore"``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

OddCode = Literal[
    "invoice_without_enrollment",
    "paused_family_invoiced",
    "autopay_no_card",
    "autopay_on_dead_enrollment",
]


class _View(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AdminMonthCloseVoidReason(_View):
    reason: str
    count: int


class AdminMonthCloseInvoices(_View):
    generated: int
    emailed: int
    autopay_notices: int
    not_sent: int
    voided: int
    voided_cents: int
    void_reasons: list[AdminMonthCloseVoidReason] = []


class AdminMonthCloseMoney(_View):
    billed_cents: int
    collected_cents: int
    outstanding_cents: int
    # Null, never 0, when nothing was billed — the page renders "—" so an
    # empty month does not read as a total collection failure (spec §4.3).
    collection_rate: float | None = None


class AdminMonthCloseTally(_View):
    count: int
    cents: int


class AdminMonthCloseAutopayRun(_View):
    # Null when the period has no invoice with a due date at all.
    charge_on: str | None = None
    # True when the run's invoices do not share one due date; the page appends
    # "and later" to the earliest.
    charge_on_varies: bool = False
    has_run: bool
    scheduled: AdminMonthCloseTally
    succeeded: AdminMonthCloseTally
    failed: AdminMonthCloseTally
    pending: AdminMonthCloseTally


class AdminMonthCloseOddItem(_View):
    kind: Literal["family", "invoice"]
    id: str
    label: str
    href: str


class AdminMonthCloseOdd(_View):
    code: OddCode
    label: str
    # The true count; ``items`` is capped at 20 so the page can say
    # "showing 20 of N".
    count: int
    items: list[AdminMonthCloseOddItem] = []


class AdminMonthCloseDiscountCategory(_View):
    category: str
    amount_cents: int


class AdminMonthCloseTuitionDiscounts(_View):
    gross_cents: int
    discount_cents: int
    net_cents: int
    by_category: list[AdminMonthCloseDiscountCategory] = []


class AdminMonthCloseView(_View):
    generated_at: str
    timezone: str
    period: str
    invoices: AdminMonthCloseInvoices
    money: AdminMonthCloseMoney
    autopay_run: AdminMonthCloseAutopayRun
    odd: list[AdminMonthCloseOdd]
    # Null when the discount query was unavailable, which also puts
    # ``discounts_unavailable`` in ``warnings``.
    tuition_discounts: AdminMonthCloseTuitionDiscounts | None = None
    # Free-form on purpose: a new degraded source must be able to name itself
    # without a coordinated frontend release. The page renders one muted line.
    warnings: list[str] = []
