"""Invoiced tuition per class and academy-local month: the percent-coach pay base (L7).

Coach pay on a ``percent_of_revenue`` rate used to be the class fee x the
class's active enrollments today, so a drop on the 25th re-priced classes the
coach had already taught. The base is now what the academy actually billed
for the class that month, read from the ledger.

Per counted invoice (not draft, not void, not deleted; mapped to a class
through ``enrollments.session_id``):

* the ``tuition`` and ``discount`` lines (the ``_TUITION_LINE_TYPES`` rule a
  class cancellation credit uses), less any header-only ``discount_cents``
  remainder no tuition-discount line carries (the
  ``_discount_base_subtotal_cents`` rule), floored at 0;
* an invoice with no lines falls back to ``subtotal_cents - discount_cents``.

ACH discount, account credit, late fees, move proration, self-cancel fees and
adjustments are not tuition and stay out (ACH comes in only when the academy
turns ``payroll_ach_discount_reduces_base`` on). Referral credit is account
credit, so it stays out too; a sibling discount is a ``discount`` line and
nets in.

A registration checkout's first month has no ledger invoice: its paid
``FIRST_MONTH_PRORATION`` snapshot amount counts instead (unless
``payroll_count_checkout_first_month`` is off), found the way
``checkout_paid_period`` finds it, and never on top of an invoice for the
same family and class-month.

shortcut: a class move mid-month counts the whole month for the destination
class, because the invoice maps through the enrollment's current session.
Upgrade to a per-line session stamp if partial-month moves become common.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.domain.ledger import TUITION_DISCOUNT_SOURCE_TYPE

_TUITION_LINE_TYPES = frozenset({"tuition", "discount"})
_ACH_LINE_TYPE = "ach_discount"
_UNCOUNTED_INVOICE_STATUSES = ["draft", "void"]
_PAID_CHECKOUT_STATUSES = ["succeeded", "paid", "partially_refunded"]


@dataclass(frozen=True)
class InvoicedTuition:
    """Invoiced tuition per ``(session_id, "YYYY-MM")`` plus the share rules.

    A key is present for every class-month with at least one counted invoice
    (or checkout first month), even when it nets to 0 (a waiver): a missing
    key means the class-month was never invoiced.
    """

    amounts: dict[tuple[str, str], int] = field(default_factory=dict)
    cancelled_class_share: str = "ran_only"
    missing_invoices: str = "block"


def invoice_tuition_cents(
    invoice: dict[str, Any], lines: list[dict[str, Any]], *, include_ach: bool
) -> int:
    if not lines:
        return max(
            0, int(invoice.get("subtotal_cents") or 0) - int(invoice.get("discount_cents") or 0)
        )
    counted = set(_TUITION_LINE_TYPES) | ({_ACH_LINE_TYPE} if include_ach else set())
    tuition = sum(
        int(line.get("amount_cents") or 0) for line in lines if line.get("line_type") in counted
    )
    line_discount = sum(
        -int(line.get("amount_cents") or 0)
        for line in lines
        if line.get("source_type") == TUITION_DISCOUNT_SOURCE_TYPE
        and int(line.get("amount_cents") or 0) < 0
    )
    header_only_discount = max(0, int(invoice.get("discount_cents") or 0) - line_discount)
    return max(0, tuition - header_only_discount)


class MongoInvoicedTuitionReadModel:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._db = db

    async def _settings(self, academy_id: str) -> BillingSettings:
        doc = await self._db["billing_settings"].find_one({"academy_id": academy_id})
        if not doc:
            return BillingSettings.default(academy_id)
        doc = {k: v for k, v in doc.items() if k != "_id"}
        return BillingSettings.model_validate(doc)

    async def tuition_by_class_month(
        self,
        *,
        academy_id: str,
        session_ids: Iterable[str],
        months: Iterable[str],
    ) -> InvoicedTuition:
        settings = await self._settings(academy_id)
        result = InvoicedTuition(
            cancelled_class_share=settings.payroll_cancelled_class_share,
            missing_invoices=settings.payroll_missing_invoices,
        )
        session_ids, months = sorted(set(session_ids)), sorted(set(months))
        if not session_ids or not months:
            return result

        session_by_enrollment: dict[str, str] = {}
        async for row in self._db["enrollments"].find(
            {"academy_id": academy_id, "session_id": {"$in": session_ids}},
            {"enrollment_id": 1, "session_id": 1},
        ):
            session_by_enrollment[str(row["enrollment_id"])] = str(row["session_id"])

        invoices: list[dict[str, Any]] = []
        if session_by_enrollment:
            async for row in self._db["invoices"].find(
                {
                    "academy_id": academy_id,
                    "enrollment_id": {"$in": list(session_by_enrollment)},
                    "period": {"$in": months},
                    "status": {"$nin": _UNCOUNTED_INVOICE_STATUSES},
                    "is_deleted": {"$ne": True},
                }
            ):
                invoices.append(row)

        lines_by_invoice: dict[str, list[dict[str, Any]]] = {}
        if invoices:
            async for line in self._db["invoice_lines"].find(
                {
                    "academy_id": academy_id,
                    "invoice_id": {"$in": [str(inv["invoice_id"]) for inv in invoices]},
                },
                {"invoice_id": 1, "line_type": 1, "amount_cents": 1, "source_type": 1},
            ):
                lines_by_invoice.setdefault(str(line["invoice_id"]), []).append(line)

        invoiced_families: set[tuple[str, str, str]] = set()
        include_ach = settings.payroll_ach_discount_reduces_base
        for invoice in invoices:
            session_id = session_by_enrollment[str(invoice["enrollment_id"])]
            key = (session_id, str(invoice["period"]))
            cents = invoice_tuition_cents(
                invoice,
                lines_by_invoice.get(str(invoice["invoice_id"]), []),
                include_ach=include_ach,
            )
            result.amounts[key] = result.amounts.get(key, 0) + cents
            invoiced_families.add((*key, str(invoice.get("parent_id") or "")))

        if settings.payroll_count_checkout_first_month:
            await self._add_checkout_first_months(
                academy_id, session_ids, months, result.amounts, invoiced_families
            )
        return result

    async def _add_checkout_first_months(
        self,
        academy_id: str,
        session_ids: list[str],
        months: list[str],
        amounts: dict[tuple[str, str], int],
        invoiced_families: set[tuple[str, str, str]],
    ) -> None:
        payments = [
            row
            async for row in self._db["payments"].find(
                {
                    "academy_id": academy_id,
                    "session_id": {"$in": session_ids},
                    "status": {"$in": _PAID_CHECKOUT_STATUSES},
                    "calculation_snapshot_id": {"$nin": [None, ""]},
                },
                {
                    "session_id": 1,
                    "calculation_snapshot_id": 1,
                    "parent_id": 1,
                    "parent_user_id": 1,
                },
            )
        ]
        if not payments:
            return
        snapshots = {
            str(row["snapshot_id"]): row
            async for row in self._db["billing_calculation_snapshots"].find(
                {
                    "academy_id": academy_id,
                    "snapshot_id": {"$in": [str(p["calculation_snapshot_id"]) for p in payments]},
                    "calculation_type": "FIRST_MONTH_PRORATION",
                    "billing_period_label": {"$in": months},
                },
                {"snapshot_id": 1, "billing_period_label": 1, "final_amount_cents": 1},
            )
        }
        for payment in payments:
            snapshot = snapshots.get(str(payment["calculation_snapshot_id"]))
            if snapshot is None:
                continue
            key = (str(payment["session_id"]), str(snapshot["billing_period_label"]))
            parent_id = str(payment.get("parent_id") or payment.get("parent_user_id") or "")
            # The same family already has a ledger invoice for this class-month:
            # counting the checkout too would bill the coach's base twice.
            if (*key, parent_id) in invoiced_families:
                continue
            amounts[key] = amounts.get(key, 0) + max(
                0, int(snapshot.get("final_amount_cents") or 0)
            )
