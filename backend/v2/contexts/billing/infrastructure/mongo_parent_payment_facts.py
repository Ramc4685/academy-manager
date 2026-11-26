"""Settled payments behind a family's invoices (parent Payments summary, receipt).

Live ``payment_allocations`` rows are the truth: a reversed allocation is
deleted, so it never shows. Only payments in ``SETTLED_PAYMENT_STATUSES``
count. Every query carries ``academy_id`` (TenantScopedRepository); the caller
passes only invoice ids it already proved belong to the family.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.billing.application.parent_money import PaymentFact
from backend.v2.contexts.billing.domain.ledger import SETTLED_PAYMENT_STATUSES
from backend.v2.shared.tenancy.repository import TenantScopedRepository


def _utc(value: Any) -> datetime | None:
    # Motor returns naive UTC datetimes unless the client is tz_aware.
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class MongoParentPaymentFacts(TenantScopedRepository):
    collection_name = "payment_allocations"

    async def for_invoices(self, invoice_ids: Sequence[str]) -> list[PaymentFact]:
        ids = sorted(set(invoice_ids))
        if not ids:
            return []
        allocations = await self._find_many(
            {"invoice_id": {"$in": ids}}
        ).to_list(length=None)
        payment_ids = sorted({str(a["payment_id"]) for a in allocations if a.get("payment_id")})
        if not payment_ids:
            return []
        payments = {
            str(p["payment_id"]): p
            async for p in self._find_many_in_collection(
                "ledger_payments",
                {
                    "payment_id": {"$in": payment_ids},
                    "status": {"$in": sorted(SETTLED_PAYMENT_STATUSES)},
                },
                {"_id": 0, "payment_id": 1, "paid_at": 1, "created_at": 1, "payment_method": 1},
            )
        }
        facts: list[PaymentFact] = []
        for allocation in allocations:
            payment = payments.get(str(allocation.get("payment_id")))
            if payment is None:
                continue
            facts.append(
                PaymentFact(
                    invoice_id=str(allocation["invoice_id"]),
                    payment_id=str(allocation["payment_id"]),
                    amount_cents=int(allocation.get("amount_cents") or 0),
                    paid_at=_utc(payment.get("paid_at") or payment.get("created_at")),
                    method=payment.get("payment_method"),
                )
            )
        return facts

    async def for_payments(
        self, payment_ids: Sequence[str]
    ) -> tuple[dict[str, list[str]], dict[str, str | None]]:
        """(invoice ids each payment paid, its stored method) for history rows.

        Any status: a pending or failed row still names its child and method.
        """
        ids = sorted({pid for pid in payment_ids if pid})
        if not ids:
            return {}, {}
        invoices_by_payment: dict[str, list[str]] = {}
        async for allocation in self._find_many({"payment_id": {"$in": ids}}):
            invoices_by_payment.setdefault(str(allocation["payment_id"]), []).append(
                str(allocation["invoice_id"])
            )
        methods = {
            str(p["payment_id"]): p.get("payment_method")
            async for p in self._find_many_in_collection(
                "ledger_payments",
                {"payment_id": {"$in": ids}},
                {"_id": 0, "payment_id": 1, "payment_method": 1},
            )
        }
        return invoices_by_payment, methods
