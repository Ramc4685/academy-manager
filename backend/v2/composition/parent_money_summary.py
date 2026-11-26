"""Wiring for the parent money summary, invoice/payment labels (S57) and receipt (S58).

Its own module so ``composition/parent.py`` gains one field. Every read is
family-scoped by ``list_invoices`` / ``get_invoice`` (``ListParentInvoices`` /
``GetParentInvoice``: alias aware, tenant scoped) and request-tenant scoped by
the repositories; ids from the client are only ever looked up inside that set.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.v2.contexts.billing.application.parent_money import (
    GetParentMoneySummary,
    build_receipt,
    latest_fact_by_invoice,
    method_label,
)
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.contexts.billing.infrastructure.mongo_parent_payment_facts import (
    MongoParentPaymentFacts,
)
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup

_SETTLED_LABEL_STATUSES = frozenset({"succeeded", "refunded", "partially_refunded"})


def can_pay_online_from(enrollments: Sequence[dict[str, Any]]) -> bool:
    """False only when every live class is paid at the desk (or free) and at
    least one is desk-paid: the same rule the Payments page used client-side."""
    live = [row for row in enrollments if not row.get("departed")]
    offers = [str(row.get("autopay_offer") or "") for row in live]
    manual_only = "manual_payments" in offers and all(
        offer in {"manual_payments", "free_class"} for offer in offers
    )
    return not manual_only


@dataclass(frozen=True)
class ParentMoney:
    summary: Callable[[str], Awaitable[dict[str, Any]]]
    invoice_extras: Callable[[str, Sequence[LedgerInvoice]], Awaitable[dict[str, dict[str, Any]]]]
    payment_extras: Callable[[str, Sequence[Any]], Awaitable[dict[str, dict[str, Any]]]]
    receipt: Callable[[str, str], Awaitable[dict[str, Any] | None]]


def compose_parent_money(
    db: Any,
    *,
    list_invoices: Callable[[str], Awaitable[list[LedgerInvoice]]],
    get_invoice: Callable[..., Awaitable[dict[str, Any] | None]],
    get_lines: Callable[[str], Awaitable[list[InvoiceLine]]],
    list_children: Callable[[str], Awaitable[list[dict[str, Any]]]],
    list_enrollments: Callable[[str], Awaitable[list[dict[str, Any]]]],
    get_academy_info: Callable[..., Awaitable[dict[str, Any]]],
    payer_name: Callable[[str], Awaitable[str | None]],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ParentMoney:
    facts = MongoParentPaymentFacts(db)
    timezone_of = academy_timezone_lookup(db)

    async def child_names(parent_id: str) -> dict[str, str]:
        return {str(c["student_id"]): str(c["full_name"]) for c in await list_children(parent_id)}

    def _classes(enrollments: Sequence[dict[str, Any]]) -> dict[str, str]:
        return {
            str(e["enrollment_id"]): str(e.get("session_title") or "")
            for e in enrollments
            if e.get("enrollment_id")
        }

    async def class_by_enrollment(parent_id: str) -> dict[str, str]:
        return _classes(await list_enrollments(parent_id))

    async def enrollment_facts(parent_id: str) -> tuple[dict[str, str], bool]:
        # list_enrollments is the heavy parent read (autopay offer per class): once.
        enrollments = await list_enrollments(parent_id)
        return _classes(enrollments), can_pay_online_from(enrollments)

    async def academy_clock() -> tuple[date, str | None]:
        timezone_name = await timezone_of(current_academy_id())
        try:
            zone = ZoneInfo(timezone_name or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            zone = ZoneInfo("UTC")
        return clock().astimezone(zone).date(), timezone_name

    summary_uc = GetParentMoneySummary(
        list_invoices=list_invoices,
        get_lines=get_lines,
        payment_facts=facts,
        child_names=child_names,
        enrollment_facts=enrollment_facts,
        academy_clock=academy_clock,
    )

    async def invoice_extras(
        parent_id: str, invoices: Sequence[LedgerInvoice]
    ) -> dict[str, dict[str, Any]]:
        if not invoices:
            return {}
        names = await child_names(parent_id)
        classes = await class_by_enrollment(parent_id)
        _, timezone_name = await academy_clock()
        try:
            zone = ZoneInfo(timezone_name or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            zone = ZoneInfo("UTC")
        latest = latest_fact_by_invoice(await facts.for_invoices([i.invoice_id for i in invoices]))
        out: dict[str, dict[str, Any]] = {}
        for inv in invoices:
            fact = latest.get(inv.invoice_id)
            out[inv.invoice_id] = {
                "student_name": names.get(inv.student_id or ""),
                "class_name": classes.get(inv.enrollment_id or "") or None,
                "paid_on": fact.paid_at.astimezone(zone).date() if fact and fact.paid_at else None,
                "method_label": method_label(fact.method) if fact else None,
                "has_receipt": str(inv.status) == "paid",
            }
        return out

    async def payment_extras(parent_id: str, rows: Sequence[Any]) -> dict[str, dict[str, Any]]:
        if not rows:
            return {}
        invoice_ids_by_payment, methods = await facts.for_payments(
            [str(getattr(r, "payment_id", "") or "") for r in rows]
        )
        # Only invoices the family owns name a child; anything else stays blank.
        student_by_invoice = {
            inv.invoice_id: inv.student_id for inv in await list_invoices(parent_id)
        }
        names = await child_names(parent_id)
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            payment_id = str(getattr(row, "payment_id", "") or "")
            students: list[str] = []
            for invoice_id in invoice_ids_by_payment.get(payment_id, []):
                name = names.get(student_by_invoice.get(invoice_id) or "")
                if name and name not in students:
                    students.append(name)
            method = methods.get(payment_id)
            if method is None and getattr(row, "stripe_payment_intent_id", None):
                method = "stripe"  # legacy checkout rows carry no method field
            out[payment_id] = {
                "student_names": students,
                "method_label": method_label(method)
                if str(getattr(row, "status", "")) in _SETTLED_LABEL_STATUSES
                else None,
            }
        return out

    async def receipt(parent_id: str, invoice_id: str) -> dict[str, Any] | None:
        detail = await get_invoice(parent_id=parent_id, invoice_id=invoice_id)
        if detail is None or str(detail["invoice"].status) != "paid":
            return None
        invoice: LedgerInvoice = detail["invoice"]
        academy = await get_academy_info(academy_id=current_academy_id())
        _, timezone_name = await academy_clock()
        names = await child_names(parent_id)
        return build_receipt(
            invoice=invoice,
            lines=detail["lines"],
            facts=await facts.for_invoices([invoice.invoice_id]),
            academy=academy,
            payer_name=await payer_name(parent_id),
            student_name=names.get(invoice.student_id or ""),
            timezone_name=timezone_name,
        )

    return ParentMoney(
        summary=summary_uc.execute,
        invoice_extras=invoice_extras,
        payment_extras=payment_extras,
        receipt=receipt,
    )
