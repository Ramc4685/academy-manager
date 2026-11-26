"""Parent money summary and receipt (S57, S58; spec docs/design/parent-money.md).

"Due" is invoices already issued and unpaid, never an estimate; a receipt is a
printable page for a paid invoice. Every figure the parent sees is computed
here, never in the browser.

Invariant: the summary's ``lines`` always add up to ``amount_due_cents``. An
invoice whose stored lines do not add up to its total (legacy shape, or credit
applied at mint, which no line records) contributes one child line equal to
its balance, so a wrong breakdown is never returned.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.v2.contexts.billing.application.autopay_eligibility import invoice_is_chargeable
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice

#: Issued invoices: a draft is not sent yet and a void one is owed by nobody.
ISSUED_INVOICE_STATUSES = frozenset({"open", "partially_paid", "paid"})
_PERIOD_LIMIT = 12

_METHOD_LABELS = {
    "cash": "Paid in cash",
    "check": "Paid by check",
    "zelle": "Paid by Zelle",
    "venmo": "Paid by Venmo",
    "bank_transfer": "Paid by bank transfer",
    # Checkout takes card or bank debit and the ledger does not say which.
    "stripe_checkout": "Paid online",
    "stripe": "Paid online",
    "stripe_legacy": "Paid online",
    "stripe_autopay": "Paid by autopay",
    "stripe_subscription": "Paid by autopay",
}
_METHOD_WORDS = {
    "cash": "Cash",
    "check": "Check",
    "zelle": "Zelle",
    "venmo": "Venmo",
    "bank_transfer": "Bank transfer",
    "stripe_checkout": "Online",
    "stripe": "Online",
    "stripe_legacy": "Online",
    "stripe_autopay": "Autopay",
    "stripe_subscription": "Autopay",
}


def method_label(method: str | None) -> str:
    """Parent-facing sentence for how a payment was made."""
    return _METHOD_LABELS.get(str(method or ""), "Paid")


def method_word(method: str | None) -> str:
    """The bare word a receipt row shows."""
    return _METHOD_WORDS.get(str(method or ""), "Other")


def invoice_is_due(invoice: LedgerInvoice) -> bool:
    """The one "the family owes this" rule, shared by Home and Payments."""
    return invoice_is_chargeable(str(invoice.status), int(invoice.balance_due_cents))


def period_label(period: str) -> str:
    try:
        return datetime.strptime(period, "%Y-%m").strftime("%B %Y")
    except ValueError:
        return period


@dataclass(frozen=True)
class PaymentFact:
    """One live allocation of a settled payment onto an invoice."""

    invoice_id: str
    payment_id: str
    amount_cents: int
    paid_at: datetime | None
    method: str | None


class ParentPaymentFacts(Protocol):
    async def for_invoices(self, invoice_ids: Sequence[str]) -> list[PaymentFact]: ...


def _zone(timezone_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _local_date(value: datetime | None, zone: ZoneInfo) -> date | None:
    return value.astimezone(zone).date() if value is not None else None


def _itemize(
    invoice: LedgerInvoice, lines: Sequence[InvoiceLine]
) -> tuple[int, dict[str, int], int] | None:
    """(gross child amount, negative lines by description, already paid) when
    the stored lines explain the invoice total; None when they do not."""
    if not lines or sum(line.amount_cents for line in lines) != invoice.total_cents:
        return None
    positive = sum(line.amount_cents for line in lines if line.amount_cents > 0)
    negatives: dict[str, int] = {}
    for line in lines:
        if line.amount_cents < 0:
            negatives[line.description] = negatives.get(line.description, 0) + line.amount_cents
    return positive, negatives, invoice.total_cents - invoice.balance_due_cents


def _fallback_lines(
    due: Sequence[LedgerInvoice], child_names: dict[str, str]
) -> list[dict[str, Any]]:
    return [
        {
            "kind": "child",
            "student_id": inv.student_id,
            "label": child_names.get(inv.student_id or "", "Family"),
            "detail": period_label(inv.period),
            "amount_cents": inv.balance_due_cents,
        }
        for inv in due
    ]


def build_money_summary(
    *,
    invoices: Sequence[LedgerInvoice],
    lines_by_invoice: dict[str, list[InvoiceLine]],
    facts: Iterable[PaymentFact],
    child_names: dict[str, str],
    class_by_enrollment: dict[str, str],
    today: date,
    timezone_name: str | None,
    can_pay_online: bool,
) -> dict[str, Any]:
    zone = _zone(timezone_name)
    due = sorted(
        (inv for inv in invoices if invoice_is_due(inv)),
        key=lambda inv: (inv.due_date, inv.invoice_id),
    )
    amount_due = sum(inv.balance_due_cents for inv in due)
    due_dates = sorted({inv.due_date for inv in due})
    due_date = due_dates[0] if due_dates else None

    children: dict[str | None, dict[str, Any]] = {}
    discounts: dict[str, int] = {}
    already_paid = 0
    for inv in due:
        items = _itemize(inv, lines_by_invoice.get(inv.invoice_id, []))
        row = children.setdefault(inv.student_id, {"amount_cents": 0, "details": []})
        row["amount_cents"] += inv.balance_due_cents if items is None else items[0]
        detail = " · ".join(
            part
            for part in (
                class_by_enrollment.get(inv.enrollment_id or ""),
                period_label(inv.period).split(" ")[0],
            )
            if part
        )
        if detail and detail not in row["details"]:
            row["details"].append(detail)
        if items is not None:
            for label, cents in items[1].items():
                discounts[label] = discounts.get(label, 0) + cents
            already_paid += items[2]

    lines: list[dict[str, Any]] = [
        {
            "kind": "child",
            "student_id": student_id,
            "label": child_names.get(student_id, "Family") if student_id else "Family",
            "detail": ", ".join(row["details"]) or None,
            "amount_cents": row["amount_cents"],
        }
        for student_id, row in children.items()
        if row["amount_cents"]
    ]
    lines.sort(key=lambda line: (line["label"] == "Family", line["label"]))
    lines += [
        {"kind": "discount", "student_id": None, "label": label, "detail": None, "amount_cents": cents}
        for label, cents in discounts.items()
        if cents
    ]
    if already_paid:
        lines.append(
            {
                "kind": "paid",
                "student_id": None,
                "label": "Already paid",
                "detail": None,
                "amount_cents": -already_paid,
            }
        )
    if sum(line["amount_cents"] for line in lines) != amount_due:
        # Unreachable by construction; a breakdown that does not add up must
        # still never reach a parent.
        lines = _fallback_lines(due, child_names)

    issued = [inv for inv in invoices if str(inv.status) in ISSUED_INVOICE_STATUSES]
    periods: dict[str, dict[str, int]] = {}
    for inv in issued:
        bucket = periods.setdefault(inv.period, {"billed": 0, "paid": 0, "due": 0})
        bucket["billed"] += inv.total_cents
        bucket["paid"] += inv.total_cents - inv.balance_due_cents
        bucket["due"] += inv.balance_due_cents if invoice_is_due(inv) else 0

    issued_ids = {inv.invoice_id for inv in issued}
    by_payment: dict[str, dict[str, Any]] = {}
    for fact in facts:
        if fact.invoice_id not in issued_ids or fact.paid_at is None:
            continue
        entry = by_payment.setdefault(
            fact.payment_id, {"amount_cents": 0, "paid_at": fact.paid_at, "method": fact.method}
        )
        entry["amount_cents"] += fact.amount_cents
    last = max(by_payment.values(), key=lambda e: e["paid_at"].timestamp(), default=None)

    days_overdue = (today - due_date).days if due_date and due_date < today else 0
    return {
        "currency": next((inv.currency for inv in due), None)
        or next((inv.currency for inv in invoices), "usd"),
        "amount_due_cents": amount_due,
        "due_date": due_date,
        "overdue": days_overdue > 0,
        "days_overdue": days_overdue,
        "multiple_due_dates": len(due_dates) > 1,
        "can_pay_online": can_pay_online,
        "lines": lines,
        "periods": [
            {
                "period": period,
                "label": period_label(period),
                "billed_cents": bucket["billed"],
                "paid_cents": bucket["paid"],
                "due_cents": bucket["due"],
            }
            for period, bucket in sorted(periods.items(), reverse=True)[:_PERIOD_LIMIT]
        ],
        "last_payment": (
            {
                "amount_cents": last["amount_cents"],
                "paid_on": _local_date(last["paid_at"], zone),
                "method_label": method_label(last["method"]),
            }
            if last
            else None
        ),
    }


def _when(fact: PaymentFact) -> float:
    return fact.paid_at.timestamp() if fact.paid_at else 0.0


def latest_fact_by_invoice(facts: Iterable[PaymentFact]) -> dict[str, PaymentFact]:
    latest: dict[str, PaymentFact] = {}
    for fact in facts:
        held = latest.get(fact.invoice_id)
        if fact.paid_at is not None and (held is None or _when(fact) > _when(held)):
            latest[fact.invoice_id] = fact
    return latest


class GetParentMoneySummary:
    """``GET /parent/money-summary``: the family's own issued invoices only.

    Ownership is whatever ``list_invoices`` (``ListParentInvoices``: alias
    aware, tenant scoped) returns; this never takes a family id from the client.
    """

    def __init__(
        self,
        *,
        list_invoices: Callable[[str], Awaitable[list[LedgerInvoice]]],
        get_lines: Callable[[str], Awaitable[list[InvoiceLine]]],
        payment_facts: ParentPaymentFacts,
        child_names: Callable[[str], Awaitable[dict[str, str]]],
        class_by_enrollment: Callable[[str], Awaitable[dict[str, str]]],
        can_pay_online: Callable[[str], Awaitable[bool]],
        academy_clock: Callable[[], Awaitable[tuple[date, str | None]]],
    ) -> None:
        self._list_invoices = list_invoices
        self._get_lines = get_lines
        self._facts = payment_facts
        self._child_names = child_names
        self._classes = class_by_enrollment
        self._can_pay_online = can_pay_online
        self._clock = academy_clock

    async def execute(self, parent_id: str) -> dict[str, Any]:
        invoices = await self._list_invoices(parent_id)
        lines_by_invoice = {
            inv.invoice_id: await self._get_lines(inv.invoice_id)
            for inv in invoices
            if invoice_is_due(inv)
        }
        issued_ids = [
            inv.invoice_id for inv in invoices if str(inv.status) in ISSUED_INVOICE_STATUSES
        ]
        today, timezone_name = await self._clock()
        return build_money_summary(
            invoices=invoices,
            lines_by_invoice=lines_by_invoice,
            facts=await self._facts.for_invoices(issued_ids) if issued_ids else [],
            child_names=await self._child_names(parent_id),
            class_by_enrollment=await self._classes(parent_id),
            today=today,
            timezone_name=timezone_name,
            can_pay_online=await self._can_pay_online(parent_id),
        )
