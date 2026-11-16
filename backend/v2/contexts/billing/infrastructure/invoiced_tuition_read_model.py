"""Invoiced tuition per class and academy-local month: the percent-coach pay base (L7).

Coach pay on a ``percent_of_revenue`` rate used to be the class fee x the
class's active enrollments today, so a drop on the 25th re-priced classes the
coach had already taught. The base is now what the academy actually billed
for the class that month, read from the ledger.

Per counted invoice (not draft, not void, not deleted; mapped to the class it
billed through the CONSUMED calculation snapshot for its enrollment and
month, or ``enrollments.session_id`` when there is none):

* the ``tuition`` and ``discount`` lines (the ``_TUITION_LINE_TYPES`` rule a
  class cancellation credit uses), less any header-only ``discount_cents``
  remainder no tuition-discount line carries (the
  ``_discount_base_subtotal_cents`` rule), floored at 0;
* an invoice with no lines falls back to ``subtotal_cents - discount_cents``;
* less the invoice's ``refunded_cents``, floored at 0, the same way a
  refunded checkout leaves the base.

A manual invoice with no ``enrollment_id`` names no class, so it is counted
in ``unattributed_invoices`` instead (a non-blocking period warning).

ACH discount, account credit, late fees, move proration, self-cancel fees and
adjustments are not tuition and stay out (ACH comes in only when the academy
turns ``payroll_ach_discount_reduces_base`` on). Referral credit is account
credit, so it stays out too; a sibling discount is a ``discount`` line and
nets in.

A registration checkout's first month has no ledger invoice: its paid
``FIRST_MONTH_PRORATION`` snapshot amount counts instead (unless
``payroll_count_checkout_first_month`` is off), less its refunds, and only
when the payment's registration application became an enrollment that still
exists. It never counts on top of an invoice for the same enrollment and
class-month.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.billing.domain.ledger import TUITION_DISCOUNT_SOURCE_TYPE
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository
from backend.v2.shared.tenancy import tenant_scope

_TUITION_LINE_TYPES = frozenset({"tuition", "discount"})
_ACH_LINE_TYPE = "ach_discount"
_UNCOUNTED_INVOICE_STATUSES = ["draft", "void"]
_PAID_CHECKOUT_STATUSES = ["succeeded", "paid", "partially_refunded"]
_BILLED_SNAPSHOT_TYPES = ["FIRST_MONTH_PRORATION", "MONTHLY_TUITION"]


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
    #: First month (``YYYY-MM``) assistants are paid in the app; ``None`` = never.
    assistant_pay_from: str | None = None
    #: Counted invoices in the months with tuition but no enrollment (no class).
    unattributed_invoices: int = 0


def invoice_tuition_cents(
    invoice: dict[str, Any], lines: list[dict[str, Any]], *, include_ach: bool
) -> int:
    refunded = int(invoice.get("refunded_cents") or 0)
    if not lines:
        return max(
            0,
            int(invoice.get("subtotal_cents") or 0)
            - int(invoice.get("discount_cents") or 0)
            - refunded,
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
    return max(0, tuition - header_only_discount - refunded)


class MongoInvoicedTuitionReadModel:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._db = db

    async def tuition_by_class_month(
        self,
        *,
        academy_id: str,
        session_ids: Iterable[str],
        months: Iterable[str],
    ) -> InvoicedTuition:
        # The caller's academy_id is authoritative, inside or outside a request.
        with tenant_scope(academy_id):
            settings = await MongoBillingSettingsRepository(self._db).get()
        result = InvoicedTuition(
            cancelled_class_share=settings.payroll_cancelled_class_share,
            missing_invoices=settings.payroll_missing_invoices,
            assistant_pay_from=settings.payroll_assistant_pay_from,
        )
        session_ids, months = sorted(set(session_ids)), sorted(set(months))
        if not months:
            return result

        # Invoices by month first, then the class each one billed (L7): a
        # class move later rewrites ``enrollments.session_id``, so the current
        # enrollment would re-attribute months the old class already taught.
        invoices = [
            row
            async for row in self._db["invoices"].find(
                {
                    "academy_id": academy_id,
                    "period": {"$in": months},
                    "status": {"$nin": _UNCOUNTED_INVOICE_STATUSES},
                    "is_deleted": {"$ne": True},
                }
            )
        ]
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

        include_ach = settings.payroll_ach_discount_reduces_base
        billed_session = await self._billed_sessions(academy_id, invoices)
        wanted = set(session_ids)
        invoiced_enrollments: set[tuple[str, str, str]] = set()
        unattributed = 0
        for invoice in invoices:
            cents = invoice_tuition_cents(
                invoice,
                lines_by_invoice.get(str(invoice["invoice_id"]), []),
                include_ach=include_ach,
            )
            enrollment_id = str(invoice.get("enrollment_id") or "")
            if not enrollment_id:
                # A manual invoice with no enrollment names no class, so it is
                # in no coach's base; the period says how many were left out.
                unattributed += cents > 0
                continue
            session_id = billed_session.get((enrollment_id, str(invoice["period"])))
            if session_id not in wanted:
                continue
            key = (session_id, str(invoice["period"]))
            result.amounts[key] = result.amounts.get(key, 0) + cents
            invoiced_enrollments.add((*key, enrollment_id))

        if settings.payroll_count_checkout_first_month and session_ids:
            await self._add_checkout_first_months(
                academy_id, session_ids, months, result.amounts, invoiced_enrollments
            )
        return replace(result, unattributed_invoices=unattributed)

    async def _billed_sessions(
        self, academy_id: str, invoices: list[dict[str, Any]]
    ) -> dict[tuple[str, str], str]:
        """``(enrollment_id, period) -> session_id`` the month was billed for.

        Read from the CONSUMED calculation snapshot the generator stamped when
        it billed that month (the first one, if a later run re-billed it);
        ``enrollments.session_id`` only when no snapshot exists.
        """
        pairs = {
            (str(inv["enrollment_id"]), str(inv["period"]))
            for inv in invoices
            if inv.get("enrollment_id")
        }
        if not pairs:
            return {}
        billed: dict[tuple[str, str], str] = {}
        async for snap in self._db["billing_calculation_snapshots"].find(
            {
                "academy_id": academy_id,
                "enrollment_id": {"$in": sorted({eid for eid, _ in pairs})},
                "billing_period_label": {"$in": sorted({month for _, month in pairs})},
                "status": "CONSUMED",
                "calculation_type": {"$in": _BILLED_SNAPSHOT_TYPES},
                "session_id": {"$nin": [None, ""]},
            },
            {"enrollment_id": 1, "billing_period_label": 1, "session_id": 1},
            sort=[("calculated_at", 1)],
        ):
            key = (str(snap["enrollment_id"]), str(snap["billing_period_label"]))
            billed.setdefault(key, str(snap["session_id"]))
        unresolved = sorted({eid for eid, month in pairs if (eid, month) not in billed})
        if unresolved:
            current: dict[str, str] = {}
            async for row in self._db["enrollments"].find(
                {"academy_id": academy_id, "enrollment_id": {"$in": unresolved}},
                {"enrollment_id": 1, "session_id": 1},
            ):
                if row.get("session_id"):
                    current[str(row["enrollment_id"])] = str(row["session_id"])
            for eid, month in pairs:
                if (eid, month) not in billed and eid in current:
                    billed[(eid, month)] = current[eid]
        return billed

    async def _add_checkout_first_months(
        self,
        academy_id: str,
        session_ids: list[str],
        months: list[str],
        amounts: dict[tuple[str, str], int],
        invoiced_enrollments: set[tuple[str, str, str]],
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
                    "payment_id": 1,
                    "session_id": 1,
                    "calculation_snapshot_id": 1,
                    "refunded_cents": 1,
                    "refunded_amount": 1,
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
        # A checkout counts only once its application became an enrollment: a
        # rejected or never-approved application's payment taught nobody.
        enrollment_by_payment = {
            str(row["payment_id"]): str(row["enrollment_id"])
            async for row in self._db["onboarding_applications"].find(
                {
                    "academy_id": academy_id,
                    "payment_id": {"$in": [str(p["payment_id"]) for p in payments]},
                    "enrollment_id": {"$nin": [None, ""]},
                },
                {"payment_id": 1, "enrollment_id": 1},
            )
        }
        existing = {
            str(row["enrollment_id"])
            async for row in self._db["enrollments"].find(
                {
                    "academy_id": academy_id,
                    "enrollment_id": {"$in": sorted(set(enrollment_by_payment.values()))},
                },
                {"enrollment_id": 1},
            )
        }
        for payment in payments:
            snapshot = snapshots.get(str(payment["calculation_snapshot_id"]))
            enrollment_id = enrollment_by_payment.get(str(payment["payment_id"]))
            if snapshot is None or enrollment_id not in existing:
                continue
            key = (str(payment["session_id"]), str(snapshot["billing_period_label"]))
            # That enrollment already has a ledger invoice for this class-month:
            # counting the checkout too would put the month in the base twice.
            if (*key, enrollment_id) in invoiced_enrollments:
                continue
            paid = int(snapshot.get("final_amount_cents") or 0)
            amounts[key] = amounts.get(key, 0) + max(
                0, paid - MongoPaymentRepository._refunded_cents(payment)
            )
