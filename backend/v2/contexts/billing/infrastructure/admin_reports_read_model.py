"""Admin reporting read models (KPIs, dashboards, financial reports).

Mongo aggregation pipelines behind the admin BFF's report endpoints. These
were extracted verbatim from ``composition/admin.py`` (audit item MT1) so the
composition root stays pure wiring; the pipelines themselves are unchanged,
including their tenant scoping — every ``$match`` carries the ``academy_id``
resolved from the request via ``current_academy_id()``.

Each ``make_*`` function is a factory: it takes the Motor database and returns
the async callable the BFF exposes.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from bson import ObjectId as BsonObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.billing.application.admin_money import (
    aging_label,
    cents_to_dollars,
    coerce_report_datetime,
    invoice_due_date,
    invoice_outstanding_cents,
    invoice_paid_cents,
    invoice_provider_keys,
    ledger_payment_effective_at,
    ledger_payment_effective_month,
    ledger_payment_effective_window_query,
    legacy_payment_cash_candidate_query,
    month_bounds,
    payment_collected_cents,
    payment_due_date,
    payment_effective_month,
    payment_outstanding_cents,
    payment_provider_keys,
    payment_revenue_net_cents,
    round_money_minor,
)
from backend.v2.shared.occurrences import occurrence_session_id
from backend.v2.shared.tenancy import current_academy_id


def make_reports_kpis(db: AsyncIOMotorDatabase[Any]) -> object:
    """Returns an async callable that computes KPIs on-demand from live collections."""
    from datetime import UTC, datetime, timedelta

    from backend.v2.shared.tenancy import current_academy_id

    async def get_reports_kpis() -> dict[str, int | float]:
        academy_id = current_academy_id()
        now = datetime.now(UTC)
        period_str = now.strftime("%Y-%m")
        start_month, end_month = month_bounds(period_str)
        cutoff_30d = now - timedelta(days=30)

        # active_students: distinct students with active enrollment
        pipeline_students: list[dict[str, Any]] = [
            {"$match": {"academy_id": academy_id, "status": "active"}},
            {"$group": {"_id": "$student_id"}},
            {"$count": "n"},
        ]
        res = await db.enrollments.aggregate(pipeline_students).to_list(length=1)
        active_students: int = res[0]["n"] if res else 0

        # attendance_rate_30d
        pipeline_att: list[dict[str, Any]] = [
            {
                "$match": {
                    "academy_id": academy_id,
                    "marked_at": {"$gte": cutoff_30d},
                    "status": {"$in": ["present", "absent", "late"]},
                }
            },
            {
                "$group": {
                    "_id": None,
                    "present": {
                        "$sum": {"$cond": [{"$in": ["$status", ["present", "late"]]}, 1, 0]}
                    },
                    "total": {"$sum": 1},
                }
            },
        ]
        res2 = await db.attendance.aggregate(pipeline_att).to_list(length=1)
        if res2 and res2[0]["total"] > 0:
            attendance_rate_30d = round(res2[0]["present"] / res2[0]["total"], 4)
        else:
            attendance_rate_30d = 0.0

        # dues_collected_mtd
        pipeline_dues: list[dict[str, Any]] = [
            {
                "$match": {
                    "academy_id": academy_id,
                    "status": {"$in": ["succeeded", "paid"]},
                    "created_at": {"$gte": start_month, "$lt": end_month},
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total": {
                        "$sum": {
                            "$subtract": [
                                "$amount_cents",
                                {"$ifNull": ["$refunded_cents", 0]},
                            ]
                        }
                    },
                }
            },
        ]
        res3 = await db.ledger_payments.aggregate(pipeline_dues).to_list(length=1)
        dues_collected_mtd_cents: int = res3[0]["total"] if res3 else 0

        # pending_waivers
        active_student_ids_cursor = db.enrollments.find(
            {"academy_id": academy_id, "status": "active"}, {"student_id": 1}
        )
        active_ids = {doc["student_id"] async for doc in active_student_ids_cursor}
        signed_cursor = db.waiver_acceptances.find(
            {
                "academy_id": academy_id,
                "student_id": {"$in": list(active_ids)},
                "is_deleted": {"$ne": True},
            },
            {"student_id": 1},
        )
        signed_ids = {doc["student_id"] async for doc in signed_cursor}
        pending_waivers = len(active_ids - signed_ids)

        return {
            "active_students": active_students,
            "attendance_rate_30d": attendance_rate_30d,
            "dues_collected_mtd_cents": dues_collected_mtd_cents,
            "pending_waivers": pending_waivers,
        }

    return get_reports_kpis


class AdminEffectiveRevenueQuery:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._db = db

    async def execute(self, parent_id_filter: str | None = None) -> dict[str, int]:
        from backend.v2.shared.tenancy import current_academy_id

        academy_id = current_academy_id()
        result: dict[str, int] = {}
        ledger_keys: set[str] = set()
        ledger_payment_ids: list[str] = []
        successful_statuses = ["succeeded", "paid", "partially_refunded", "refunded"]
        provider_key_fields = [
            "payment_id",
            "invoice_id",
            "invoice_number",
            "stripe_invoice_id",
            "stripe_payment_intent_id",
            "stripe_checkout_session_id",
        ]

        ledger_query: dict[str, Any] = {
            "academy_id": academy_id,
            "status": {"$in": successful_statuses},
        }
        if parent_id_filter:
            ledger_query["parent_id"] = parent_id_filter

        ledger_months = await self._aggregate_months(
            "ledger_payments",
            self._ledger_revenue_pipeline(ledger_query),
        )
        if ledger_months is None:
            ledger_months = await self._ledger_revenue_fallback(ledger_query)
        self._merge_months(result, ledger_months)

        ledger_key_projection = dict.fromkeys(provider_key_fields, 1)
        async for payment in self._db["ledger_payments"].find(
            ledger_query,
            ledger_key_projection,
        ):
            ledger_keys.update(payment_provider_keys(payment))
            payment_id = str(payment.get("payment_id") or "")
            if payment_id:
                ledger_payment_ids.append(payment_id)

        if ledger_payment_ids:
            await self._add_allocation_keys(
                academy_id,
                ledger_payment_ids,
                ledger_keys,
            )

        legacy_query: dict[str, Any] = {
            "academy_id": academy_id,
            "status": {"$in": successful_statuses},
            "is_deleted": {"$ne": True},
        }
        if parent_id_filter:
            legacy_query["parent_id"] = parent_id_filter

        legacy_months = await self._aggregate_months(
            "payments",
            self._legacy_revenue_pipeline(legacy_query),
        )
        if legacy_months is None:
            legacy_months = await self._legacy_revenue_fallback(legacy_query)
        self._merge_months(result, legacy_months)
        if ledger_keys:
            duplicate_months = await self._legacy_duplicate_revenue_months(
                legacy_query,
                ledger_keys,
                provider_key_fields,
            )
            self._subtract_months(result, duplicate_months)

        return dict(sorted(result.items()))

    @staticmethod
    def _merge_months(result: dict[str, int], months: dict[str, int]) -> None:
        for month, cents in months.items():
            result[month] = result.get(month, 0) + cents

    @staticmethod
    def _subtract_months(result: dict[str, int], months: dict[str, int]) -> None:
        for month, cents in months.items():
            result[month] = result.get(month, 0) - cents
            if result[month] == 0:
                del result[month]

    @staticmethod
    def _tenant_scoped(query: dict[str, Any]) -> dict[str, Any]:
        """Re-assert the request tenant on a caller-built query.

        The callers already set ``academy_id`` from ``current_academy_id()``;
        pinning it again here keeps the scoping visible at the raw ``find``
        call sites (see ``tests/test_no_raw_tenant_mongo_access.py``) and makes
        an un-scoped caller impossible rather than merely unlikely.
        """
        return {**query, "academy_id": current_academy_id()}

    @staticmethod
    def _chunks(values: list[str], size: int = 500) -> list[list[str]]:
        return [values[index : index + size] for index in range(0, len(values), size)]

    @staticmethod
    def _net_cents_expression() -> dict[str, Any]:
        legacy_final_cents = {"$multiply": ["$final_amount", 100]}
        legacy_gross_cents = {
            "$multiply": [
                {"$ifNull": ["$amount", {"$ifNull": ["$gross_amount", 0]}]},
                100,
            ]
        }
        discount_cents = {
            "$ifNull": [
                "$discount_cents",
                {"$multiply": [{"$ifNull": ["$discount", 0]}, 100]},
            ]
        }
        payable_cents = {
            "$ifNull": [
                "$final_amount_cents",
                {
                    "$ifNull": [
                        legacy_final_cents,
                        {
                            "$subtract": [
                                {
                                    "$ifNull": [
                                        "$amount_cents",
                                        {
                                            "$ifNull": [
                                                "$gross_amount_cents",
                                                legacy_gross_cents,
                                            ]
                                        },
                                    ]
                                },
                                discount_cents,
                            ]
                        },
                    ]
                },
            ]
        }
        received_cents = {
            "$ifNull": [
                "$paid_amount_cents",
                {
                    "$ifNull": [
                        "$amount_received_cents",
                        {
                            "$ifNull": [
                                {"$multiply": ["$paid_amount", 100]},
                                {
                                    "$ifNull": [
                                        {"$multiply": ["$amount_received", 100]},
                                        payable_cents,
                                    ]
                                },
                            ]
                        },
                    ]
                },
            ]
        }
        return {
            "$max": [
                {
                    "$subtract": [
                        received_cents,
                        {"$ifNull": ["$refunded_cents", 0]},
                    ]
                },
                0,
            ]
        }

    @classmethod
    def _ledger_revenue_pipeline(cls, match: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"$match": match},
            {
                "$project": {
                    "effective_at": {
                        "$cond": [
                            {
                                "$or": [
                                    {"$eq": ["$paid_at", None]},
                                    {"$eq": ["$paid_at", ""]},
                                ]
                            },
                            "$created_at",
                            "$paid_at",
                        ]
                    },
                    "net_cents": cls._net_cents_expression(),
                }
            },
            {
                "$match": {
                    "$and": [
                        {"effective_at": {"$ne": None}},
                        {"effective_at": {"$ne": ""}},
                    ]
                }
            },
            {
                "$group": {
                    "_id": {
                        "$dateToString": {
                            "format": "%Y-%m",
                            "date": "$effective_at",
                        }
                    },
                    "revenue_cents": {"$sum": "$net_cents"},
                    "row_count": {"$sum": 1},
                }
            },
        ]

    @classmethod
    def _legacy_revenue_pipeline(cls, match: dict[str, Any]) -> list[dict[str, Any]]:
        effective_value = {
            "$cond": [
                {
                    "$and": [
                        {"$ne": ["$paid_at", None]},
                        {"$ne": ["$paid_at", ""]},
                    ]
                },
                "$paid_at",
                {
                    "$cond": [
                        {
                            "$and": [
                                {"$ne": ["$payment_date", None]},
                                {"$ne": ["$payment_date", ""]},
                            ]
                        },
                        "$payment_date",
                        {
                            "$cond": [
                                {
                                    "$and": [
                                        {"$ne": ["$created_at", None]},
                                        {"$ne": ["$created_at", ""]},
                                    ]
                                },
                                "$created_at",
                                "$period",
                            ]
                        },
                    ]
                },
            ]
        }
        effective_month = {
            "$let": {
                "vars": {"effective": effective_value},
                "in": {
                    "$cond": [
                        {"$eq": [{"$type": "$$effective"}, "date"]},
                        {
                            "$dateToString": {
                                "format": "%Y-%m",
                                "date": "$$effective",
                            }
                        },
                        {"$substrBytes": [{"$toString": "$$effective"}, 0, 7]},
                    ]
                },
            }
        }
        return [
            {"$match": match},
            {
                "$project": {
                    "effective_month": effective_month,
                    "net_cents": cls._net_cents_expression(),
                }
            },
            {
                "$match": {
                    "$and": [
                        {"effective_month": {"$ne": None}},
                        {"effective_month": {"$ne": ""}},
                    ]
                }
            },
            {
                "$group": {
                    "_id": "$effective_month",
                    "revenue_cents": {"$sum": "$net_cents"},
                    "row_count": {"$sum": 1},
                }
            },
        ]

    async def _aggregate_months(
        self, collection_name: str, pipeline: list[dict[str, Any]]
    ) -> dict[str, int] | None:
        try:
            rows = await self._db[collection_name].aggregate(pipeline).to_list(length=None)
        except Exception:
            # mongomock does not implement all production aggregation expressions
            # used above for mixed date/string legacy fields. Fall back to the same
            # projected read so tests and local tooling preserve behavior.
            return None
        if not rows and pipeline and "$match" in pipeline[0]:
            matched_count = await self._db[collection_name].count_documents(pipeline[0]["$match"])
            if matched_count:
                return None
        months: dict[str, int] = {}
        grouped_count = 0
        for row in rows:
            grouped_count += int(row.get("row_count") or 0)
            month = str(row.get("_id") or "")
            if month:
                months[month] = months.get(month, 0) + int(row.get("revenue_cents") or 0)
            else:
                return None
        if pipeline and "$match" in pipeline[0]:
            matched_count = await self._db[collection_name].count_documents(pipeline[0]["$match"])
            if grouped_count and grouped_count < matched_count:
                return None
        return months

    async def _ledger_revenue_fallback(self, match: dict[str, Any]) -> dict[str, int]:
        projection = {
            "amount_cents": 1,
            "final_amount_cents": 1,
            "gross_amount_cents": 1,
            "amount": 1,
            "final_amount": 1,
            "gross_amount": 1,
            "discount_cents": 1,
            "discount": 1,
            "paid_amount_cents": 1,
            "amount_received_cents": 1,
            "paid_amount": 1,
            "amount_received": 1,
            "refunded_cents": 1,
            "paid_at": 1,
            "created_at": 1,
        }
        months: dict[str, int] = {}
        async for payment in self._db["ledger_payments"].find(match, projection):
            month = ledger_payment_effective_month(payment)
            if month:
                months[month] = months.get(month, 0) + payment_revenue_net_cents(payment)
        return months

    async def _legacy_revenue_fallback(self, match: dict[str, Any]) -> dict[str, int]:
        projection = {
            "amount_cents": 1,
            "final_amount_cents": 1,
            "gross_amount_cents": 1,
            "amount": 1,
            "final_amount": 1,
            "gross_amount": 1,
            "discount_cents": 1,
            "discount": 1,
            "paid_amount_cents": 1,
            "amount_received_cents": 1,
            "paid_amount": 1,
            "amount_received": 1,
            "refunded_cents": 1,
            "paid_at": 1,
            "payment_date": 1,
            "created_at": 1,
            "period": 1,
        }
        months: dict[str, int] = {}
        async for payment in self._db["payments"].find(self._tenant_scoped(match), projection):
            month = payment_effective_month(payment)
            if month:
                months[month] = months.get(month, 0) + payment_revenue_net_cents(payment)
        return months

    async def _add_allocation_keys(
        self,
        academy_id: str,
        ledger_payment_ids: list[str],
        ledger_keys: set[str],
    ) -> None:
        for payment_id_batch in self._chunks(ledger_payment_ids):
            allocation_cursor = self._db["payment_allocations"].find(
                {
                    "academy_id": academy_id,
                    "payment_id": {"$in": payment_id_batch},
                },
                {"invoice_id": 1},
            )
            async for allocation in allocation_cursor:
                invoice_id = str(allocation.get("invoice_id") or "")
                if invoice_id:
                    ledger_keys.add(invoice_id)

    async def _legacy_duplicate_revenue_months(
        self,
        base_query: dict[str, Any],
        ledger_keys: set[str],
        provider_key_fields: list[str],
    ) -> dict[str, int]:
        projection = {
            "payment_id": 1,
            "amount_cents": 1,
            "final_amount_cents": 1,
            "gross_amount_cents": 1,
            "amount": 1,
            "final_amount": 1,
            "gross_amount": 1,
            "discount_cents": 1,
            "discount": 1,
            "paid_amount_cents": 1,
            "amount_received_cents": 1,
            "paid_amount": 1,
            "amount_received": 1,
            "refunded_cents": 1,
            "paid_at": 1,
            "payment_date": 1,
            "created_at": 1,
            "period": 1,
        }
        months: dict[str, int] = {}
        seen: set[str] = set()
        # The report still needs all-history de-dupe keys because it returns all
        # months. Keep each Mongo command bounded and subtract only duplicate
        # legacy projections, instead of sending one unbounded $nin set.
        for key_batch in self._chunks(sorted(ledger_keys)):
            duplicate_query = {
                **base_query,
                "$or": [{field: {"$in": key_batch}} for field in provider_key_fields],
            }
            async for payment in self._db["payments"].find(
                self._tenant_scoped(duplicate_query), projection
            ):
                row_id = str(payment.get("payment_id") or payment.get("_id") or "")
                if not row_id or row_id in seen:
                    continue
                seen.add(row_id)
                month = payment_effective_month(payment)
                if month:
                    months[month] = months.get(month, 0) + payment_revenue_net_cents(payment)
        return months


def make_reports_dashboard(db: AsyncIOMotorDatabase[Any]) -> object:
    """Returns an async callable for the owner finance/operations dashboard."""
    from backend.v2.shared.tenancy import current_academy_id

    async def get_reports_dashboard(period: str) -> dict[str, Any]:
        academy_id = current_academy_id()
        start, end = month_bounds(period)

        cash_collected_cents = 0
        billed_cents = 0
        outstanding_dues_cents = 0
        failed_payment_count = 0
        partial_payment_count = 0
        collection_family_ids: set[str] = set()
        aging_totals: dict[str, dict[str, Any]] = {
            label: {"amount_cents": 0, "family_ids": set(), "family_amounts": {}}
            for label in ("Current", "1-30", "31-60", "60+")
        }
        invoice_keys: set[str] = set()
        ledger_payment_keys: set[str] = set()
        ledger_payment_ids: set[str] = set()
        successful_ledger_statuses = ["succeeded", "paid", "partially_refunded", "refunded"]
        invoices_cursor = db["invoices"].find(
            {
                "academy_id": academy_id,
                "period": period,
                "status": {"$nin": ["void", "waived", "cancelled"]},
                "is_deleted": {"$ne": True},
            }
        )
        async for invoice in invoices_cursor:
            invoice_keys.update(invoice_provider_keys(invoice))
            if str(invoice.get("status") or "") == "partially_paid":
                partial_payment_count += 1
            outstanding = invoice_outstanding_cents(invoice)
            outstanding_dues_cents += outstanding
            billed_cents += invoice_paid_cents(invoice) + outstanding
            if outstanding:
                family_id = str(
                    invoice.get("parent_id")
                    or invoice.get("family_id")
                    or invoice.get("student_id")
                    or invoice.get("invoice_id")
                    or ""
                )
                if family_id:
                    collection_family_ids.add(family_id)
                due_date = invoice_due_date(invoice, end.date())
                days_late = max((end.date() - due_date).days, 0)
                label = aging_label(days_late)
                bucket = aging_totals[label]
                bucket["amount_cents"] = int(bucket["amount_cents"]) + outstanding
                family_ids = bucket["family_ids"]
                if isinstance(family_ids, set) and family_id:
                    family_ids.add(family_id)
                    family_amounts = bucket["family_amounts"]
                    family_amounts[family_id] = int(family_amounts.get(family_id, 0)) + outstanding

        ledger_payments_cursor = db["ledger_payments"].find(
            {
                "academy_id": academy_id,
                **ledger_payment_effective_window_query(start, end),
                "status": {"$in": successful_ledger_statuses},
            },
            {
                "payment_id": 1,
                "invoice_id": 1,
                "invoice_number": 1,
                "stripe_invoice_id": 1,
                "stripe_payment_intent_id": 1,
                "stripe_checkout_session_id": 1,
                "amount_cents": 1,
                "final_amount_cents": 1,
                "gross_amount_cents": 1,
                "amount": 1,
                "final_amount": 1,
                "gross_amount": 1,
                "discount_cents": 1,
                "discount": 1,
                "paid_amount_cents": 1,
                "amount_received_cents": 1,
                "paid_amount": 1,
                "amount_received": 1,
                "refunded_cents": 1,
                "paid_at": 1,
                "created_at": 1,
            },
        )
        async for ledger_payment in ledger_payments_cursor:
            if ledger_payment_effective_month(ledger_payment) != period:
                continue
            ledger_payment_keys.update(payment_provider_keys(ledger_payment))
            payment_id = str(ledger_payment.get("payment_id") or "")
            if payment_id:
                ledger_payment_ids.add(payment_id)
            cash_collected_cents += payment_revenue_net_cents(ledger_payment)

        ledger_key_cursor = db["ledger_payments"].find(
            {
                "academy_id": academy_id,
                "status": {"$in": successful_ledger_statuses},
            },
            {
                "payment_id": 1,
                "invoice_id": 1,
                "invoice_number": 1,
                "stripe_invoice_id": 1,
                "stripe_payment_intent_id": 1,
                "stripe_checkout_session_id": 1,
            },
        )
        async for ledger_payment in ledger_key_cursor:
            ledger_payment_keys.update(payment_provider_keys(ledger_payment))
            payment_id = str(ledger_payment.get("payment_id") or "")
            if payment_id:
                ledger_payment_ids.add(payment_id)

        ledger_payment_id_list = sorted(ledger_payment_ids)
        for index in range(0, len(ledger_payment_id_list), 500):
            payment_id_batch = ledger_payment_id_list[index : index + 500]
            allocation_cursor = db["payment_allocations"].find(
                {
                    "academy_id": academy_id,
                    "payment_id": {"$in": payment_id_batch},
                },
                {"invoice_id": 1},
            )
            async for allocation in allocation_cursor:
                invoice_id = str(allocation.get("invoice_id") or "")
                if invoice_id:
                    ledger_payment_keys.add(invoice_id)

        failed_attempts_cursor = db["payment_attempts"].find(
            {
                "academy_id": academy_id,
                "created_at": {"$gte": start, "$lt": end},
                "status": "failed",
            }
        )
        async for _attempt in failed_attempts_cursor:
            failed_payment_count += 1

        cash_payments_cursor = db["payments"].find(
            legacy_payment_cash_candidate_query(academy_id, period, start, end),
            {
                "payment_id": 1,
                "invoice_id": 1,
                "invoice_number": 1,
                "stripe_invoice_id": 1,
                "stripe_payment_intent_id": 1,
                "stripe_checkout_session_id": 1,
                "status": 1,
                "amount_cents": 1,
                "final_amount_cents": 1,
                "gross_amount_cents": 1,
                "amount": 1,
                "final_amount": 1,
                "gross_amount": 1,
                "discount_cents": 1,
                "discount": 1,
                "paid_amount_cents": 1,
                "amount_received_cents": 1,
                "paid_amount": 1,
                "amount_received": 1,
                "refunded_cents": 1,
                "paid_at": 1,
                "payment_date": 1,
                "created_at": 1,
                "period": 1,
            },
        )
        async for payment in cash_payments_cursor:
            if payment_effective_month(payment) != period:
                continue
            payment_keys = payment_provider_keys(payment)
            if payment_keys & (invoice_keys | ledger_payment_keys):
                continue
            cash_collected_cents += payment_collected_cents(payment)

        risk_payments_cursor = db["payments"].find(
            {
                "academy_id": academy_id,
                "period": period,
                "is_deleted": {"$ne": True},
            },
            {
                "payment_id": 1,
                "invoice_id": 1,
                "invoice_number": 1,
                "stripe_invoice_id": 1,
                "stripe_payment_intent_id": 1,
                "stripe_checkout_session_id": 1,
                "status": 1,
                "parent_id": 1,
                "family_id": 1,
                "student_id": 1,
                "due_date": 1,
                "due_at": 1,
                "created_at": 1,
                "amount_cents": 1,
                "final_amount_cents": 1,
                "gross_amount_cents": 1,
                "paid_amount_cents": 1,
                "amount_received_cents": 1,
                "balance_due_cents": 1,
                "refunded_cents": 1,
            },
        )
        async for payment in risk_payments_cursor:
            payment_keys = payment_provider_keys(payment)
            if payment_keys & invoice_keys:
                continue
            status = str(payment.get("status") or "")
            if status == "failed":
                failed_payment_count += 1
            elif status == "partially_paid":
                partial_payment_count += 1
            outstanding = payment_outstanding_cents(payment)
            outstanding_dues_cents += outstanding
            billed_cents += payment_collected_cents(payment) + outstanding
            if outstanding:
                family_id = str(
                    payment.get("parent_id")
                    or payment.get("family_id")
                    or payment.get("student_id")
                    or payment.get("payment_id")
                    or ""
                )
                if family_id:
                    collection_family_ids.add(family_id)
                due_date = payment_due_date(payment, end.date())
                days_late = max((end.date() - due_date).days, 0)
                label = aging_label(days_late)
                bucket = aging_totals[label]
                bucket["amount_cents"] = int(bucket["amount_cents"]) + outstanding
                family_ids = bucket["family_ids"]
                if isinstance(family_ids, set) and family_id:
                    family_ids.add(family_id)
                    family_amounts = bucket["family_amounts"]
                    family_amounts[family_id] = int(family_amounts.get(family_id, 0)) + outstanding

        present_count = 0
        recorded_count = 0
        attendance_cursor = db["attendance"].find(
            {
                "academy_id": academy_id,
                "marked_at": {"$gte": start, "$lt": end},
                "status": {"$in": ["present", "late", "absent"]},
            }
        )
        async for attendance in attendance_cursor:
            recorded_count += 1
            if str(attendance.get("status")) in {"present", "late"}:
                present_count += 1
        attendance_rate = round(present_count / recorded_count, 4) if recorded_count else None

        session_ids: list[str] = []
        scheduled_count = 0
        completed_count = 0
        cancelled_count = 0
        capacity = 0
        sessions_cursor = db["sessions"].find(
            {
                "academy_id": academy_id,
                "start_at": {"$gte": start, "$lt": end},
                "is_deleted": {"$ne": True},
            }
        )
        async for session in sessions_cursor:
            session_id = str(session.get("session_id") or session.get("_id"))
            session_ids.append(session_id)
            status = str(session.get("status") or "scheduled")
            if status == "completed":
                completed_count += 1
            elif status == "cancelled":
                cancelled_count += 1
            else:
                scheduled_count += 1
            if status != "cancelled":
                capacity += int(session.get("capacity") or session.get("max_students") or 0)

        enrolled_seats = 0
        if session_ids:
            enrollments_cursor = db["enrollments"].find(
                {
                    "academy_id": academy_id,
                    "session_id": {"$in": session_ids},
                    "status": "active",
                    "is_deleted": {"$ne": True},
                },
                {"student_id": 1},
            )
            async for _enrollment in enrollments_cursor:
                enrolled_seats += 1
        capacity_utilization = round(enrolled_seats / capacity, 4) if capacity else None

        waitlist_count = 0
        if session_ids:
            waitlist_count = await db["waitlist"].count_documents(
                {
                    "academy_id": academy_id,
                    "session_id": {"$in": session_ids},
                    "status": {"$in": ["waiting", "active"]},
                    "is_deleted": {"$ne": True},
                }
            )

        expenses_total_cents = 0
        expense_categories: dict[str, dict[str, int]] = {}
        expenses_cursor = db["expenses"].find(
            {
                "academy_id": academy_id,
                "incurred_on": {"$gte": start, "$lt": end},
                "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
            }
        )
        async for expense in expenses_cursor:
            category = str(expense.get("category") or "other")
            amount = int(expense.get("amount_cents") or 0)
            expenses_total_cents += amount
            category_row = expense_categories.setdefault(
                category,
                {"amount_cents": 0, "count": 0},
            )
            category_row["amount_cents"] += amount
            category_row["count"] += 1
        expense_rows = [
            {"category": category, **values}
            for category, values in sorted(expense_categories.items())
        ]
        rent_cents = int(expense_categories.get("rent", {}).get("amount_cents", 0))
        misc_expenses_cents = expenses_total_cents - rent_cents

        estimated_payroll_cents = 0
        approved_payroll_cents = 0
        paid_payroll_cents = 0
        payout_period_rows = 0
        payout_cursor = db["payout_periods"].find(
            {
                "academy_id": academy_id,
                "period_start": {"$gte": start, "$lt": end},
            }
        )
        async for payout_period in payout_cursor:
            payout_period_rows += 1
            total = int(payout_period.get("total_minor") or 0)
            estimated_payroll_cents += total
            status = str(payout_period.get("status") or "draft")
            if status in {"approved", "paid"}:
                approved_payroll_cents += total
            if status == "paid":
                paid_payroll_cents += int(payout_period.get("paid_amount_minor") or total)
        unpaid_payroll_cents = max(approved_payroll_cents - paid_payroll_cents, 0)

        payroll_for_pnl = (
            approved_payroll_cents
            if approved_payroll_cents > 0
            else estimated_payroll_cents
            if estimated_payroll_cents > 0
            else None
        )
        net_profit_cents = (
            cash_collected_cents - expenses_total_cents - payroll_for_pnl
            if payroll_for_pnl is not None
            else None
        )
        profit_margin = (
            round(net_profit_cents / cash_collected_cents, 4)
            if net_profit_cents is not None and cash_collected_cents > 0
            else None
        )

        empty_states: list[str] = []
        if cash_collected_cents == 0:
            empty_states.append("No collected payment rows found for this month.")
        if recorded_count == 0:
            empty_states.append("No attendance marks found for this month.")
        if not session_ids:
            empty_states.append("No sessions found for this month.")
        if expenses_total_cents == 0:
            empty_states.append("No expenses found for this month.")
        if payout_period_rows == 0:
            empty_states.append("No payout periods generated for this month.")

        # Resolve display names for aging drill-down. parent_id may be a
        # user_id, a firebase uid, or a raw ObjectId depending on the writer,
        # so match all three (same lookup the billing/finance paths use).
        all_family_ids = {
            family_id
            for label in aging_totals
            for family_id in aging_totals[label]["family_amounts"]
        }
        family_names: dict[str, str] = {}
        if all_family_ids:
            id_list = sorted(all_family_ids)
            oid_ids = [BsonObjectId(p) for p in id_list if BsonObjectId.is_valid(p)]
            or_filter: list[dict[str, Any]] = [
                {"user_id": {"$in": id_list}},
                {"firebase_uid": {"$in": id_list}},
            ]
            if oid_ids:
                or_filter.append({"_id": {"$in": oid_ids}})
            users_cursor = db["users"].find(
                {"academy_id": academy_id, "$or": or_filter},
                {
                    "user_id": 1,
                    "firebase_uid": 1,
                    "display_name": 1,
                    "first_name": 1,
                    "last_name": 1,
                },
            )
            async for user in users_cursor:
                display = str(
                    user.get("display_name")
                    or f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                    or ""
                )
                if not display:
                    continue
                for key in (
                    str(user.get("user_id") or ""),
                    str(user.get("firebase_uid") or ""),
                    str(user["_id"]),
                ):
                    if key and key in all_family_ids:
                        family_names[key] = display

        aging_buckets = [
            {
                "label": label,
                "amount_cents": int(aging_totals[label]["amount_cents"]),
                "family_count": len(aging_totals[label]["family_ids"]),
                "families": [
                    {
                        "family_id": family_id,
                        "family_name": family_names.get(family_id),
                        "amount_cents": amount,
                    }
                    for family_id, amount in sorted(
                        aging_totals[label]["family_amounts"].items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ],
            }
            for label in ("Current", "1-30", "31-60", "60+")
        ]

        collection_rate = (
            round(min(cash_collected_cents / billed_cents, 1.0), 4) if billed_cents > 0 else None
        )

        return {
            "period": period,
            "cash_collected_cents": cash_collected_cents,
            "billed_cents": billed_cents,
            "collection_rate": collection_rate,
            "outstanding_dues_cents": outstanding_dues_cents,
            "attendance": {
                "present_count": present_count,
                "recorded_count": recorded_count,
                "attendance_rate": attendance_rate,
                "empty": recorded_count == 0,
            },
            "sessions": {
                "scheduled_count": scheduled_count,
                "completed_count": completed_count,
                "cancelled_count": cancelled_count,
                "enrolled_seats": enrolled_seats,
                "capacity": capacity,
                "capacity_utilization": capacity_utilization,
                "waitlist_count": waitlist_count,
                "empty": not session_ids,
            },
            "expenses": {
                "total_cents": expenses_total_cents,
                "by_category": expense_rows,
            },
            "collections_risk": {
                "overdue_family_count": len(collection_family_ids),
                "overdue_cents": outstanding_dues_cents,
                "failed_payment_count": failed_payment_count,
                "partial_payment_count": partial_payment_count,
                "aging_buckets": aging_buckets,
            },
            "profit_and_loss": {
                "revenue_cents": cash_collected_cents,
                "coach_payroll_cents": payroll_for_pnl,
                "rent_cents": rent_cents,
                "misc_expenses_cents": misc_expenses_cents,
                "net_profit_cents": net_profit_cents,
                "profit_margin": profit_margin,
            },
            "payroll": {
                "estimated_cents": estimated_payroll_cents if payout_period_rows else None,
                "approved_cents": approved_payroll_cents if payout_period_rows else None,
                "paid_cents": paid_payroll_cents if payout_period_rows else None,
                "unpaid_cents": unpaid_payroll_cents if payout_period_rows else None,
                "blocked_by": None
                if payout_period_rows
                else "No generated payout periods for this month.",
            },
            "empty_states": empty_states,
        }

    return get_reports_dashboard


def make_projected_income_report(db: AsyncIOMotorDatabase[Any]) -> object:
    """Returns an async callable projecting next-month expected tuition.

    Projection = active session enrollments x the session's monthly fee
    (per-student ``override_price_cents`` wins when present), split by whether
    the enrollment is on autopay (``student_billing_enrollments`` with
    ``autopay_enrollment_status == "active"``). Cash actually collected is
    reported by the dashboard; this is the forward-looking counterpart.
    """
    from backend.v2.shared.tenancy import current_academy_id

    async def get_projected_income(period: str) -> dict[str, Any]:
        academy_id = current_academy_id()

        enrollment_rows: list[dict[str, Any]] = []
        session_ids: set[str] = set()
        enrollments_cursor = db["enrollments"].find(
            {
                "academy_id": academy_id,
                "status": "active",
                "is_deleted": {"$ne": True},
            },
            {"enrollment_id": 1, "session_id": 1, "parent_id": 1, "student_id": 1},
        )
        async for enrollment in enrollments_cursor:
            session_id = str(enrollment.get("session_id") or "")
            if not session_id:
                continue
            session_ids.add(session_id)
            enrollment_rows.append(
                {
                    "enrollment_id": str(enrollment.get("enrollment_id") or ""),
                    "session_id": session_id,
                }
            )

        sessions_by_id: dict[str, dict[str, Any]] = {}
        if session_ids:
            sessions_cursor = db["sessions"].find(
                {
                    "academy_id": academy_id,
                    "session_id": {"$in": sorted(session_ids)},
                    "is_deleted": {"$ne": True},
                },
                {"session_id": 1, "title": 1, "name": 1, "amount_cents": 1},
            )
            async for session in sessions_cursor:
                sessions_by_id[str(session.get("session_id") or session.get("_id"))] = session

        # Autopay status + price override are keyed by the same enrollment_id
        # on the billing aggregate (student_billing_enrollments).
        autopay_by_enrollment: dict[str, str] = {}
        override_by_enrollment: dict[str, int | None] = {}
        enrollment_ids = sorted(
            {row["enrollment_id"] for row in enrollment_rows if row["enrollment_id"]}
        )
        for index in range(0, len(enrollment_ids), 500):
            batch = enrollment_ids[index : index + 500]
            billing_cursor = db["student_billing_enrollments"].find(
                {"academy_id": academy_id, "enrollment_id": {"$in": batch}},
                {"enrollment_id": 1, "autopay_enrollment_status": 1, "override_price_cents": 1},
            )
            async for billing in billing_cursor:
                enrollment_id = str(billing.get("enrollment_id") or "")
                if not enrollment_id:
                    continue
                autopay_by_enrollment[enrollment_id] = str(
                    billing.get("autopay_enrollment_status") or "not_offered"
                )
                override = billing.get("override_price_cents")
                override_by_enrollment[enrollment_id] = (
                    int(override) if override is not None else None
                )

        total_cents = 0
        autopay_cents = 0
        manual_cents = 0
        autopay_count = 0
        manual_count = 0
        by_session: dict[str, dict[str, Any]] = {}
        for row in enrollment_rows:
            session = sessions_by_id.get(row["session_id"])
            if session is None:
                continue
            monthly_fee = int(session.get("amount_cents") or 0)
            override = override_by_enrollment.get(row["enrollment_id"])
            expected = override if override is not None else monthly_fee
            if expected <= 0:
                continue
            is_autopay = autopay_by_enrollment.get(row["enrollment_id"]) == "active"
            total_cents += expected
            if is_autopay:
                autopay_cents += expected
                autopay_count += 1
            else:
                manual_cents += expected
                manual_count += 1
            session_row = by_session.setdefault(
                row["session_id"],
                {
                    "session_id": row["session_id"],
                    "title": str(session.get("title") or session.get("name") or ""),
                    "monthly_fee_cents": monthly_fee,
                    "enrollment_count": 0,
                    "expected_cents": 0,
                },
            )
            session_row["enrollment_count"] += 1
            session_row["expected_cents"] += expected

        rows = sorted(
            by_session.values(),
            key=lambda item: (-int(item["expected_cents"]), str(item["title"])),
        )
        return {
            "period": period,
            "total_cents": total_cents,
            "autopay_cents": autopay_cents,
            "manual_cents": manual_cents,
            "enrollment_count": autopay_count + manual_count,
            "autopay_enrollment_count": autopay_count,
            "manual_enrollment_count": manual_count,
            "by_session": rows,
            "empty": not rows,
        }

    return get_projected_income


def _report_iso(value: Any) -> str | None:
    parsed = coerce_report_datetime(value)
    return parsed.isoformat() if parsed is not None else None


_LEDGER_SUCCESS_STATUSES = ["succeeded", "paid", "partially_refunded", "refunded"]


def make_refunds_report(
    db: AsyncIOMotorDatabase[Any],
) -> Callable[[str], Awaitable[dict[str, Any]]]:
    """Cash-basis refunds & credits issued in a month, from the append-only audit trail.

    ``billing_audit_log`` (action=refund_issued) is the only per-event refund record
    with a timestamp; ``refunded_cents`` on invoices/payments is a cumulative total.
    Credits come from ``account_credit_ledger``.
    """
    from backend.v2.shared.tenancy import current_academy_id

    async def get_refunds_report(period: str) -> dict[str, Any]:
        academy_id = current_academy_id()
        start, end = month_bounds(period)

        refunds: list[dict[str, Any]] = []
        total_refunded_cents = 0
        invoice_ids: set[str] = set()
        audit_cursor = (
            db["billing_audit_log"]
            .find(
                {
                    "academy_id": academy_id,
                    "action": "refund_issued",
                    "at": {"$gte": start, "$lt": end},
                }
            )
            .sort([("at", -1)])
        )
        async for entry in audit_cursor:
            before = entry.get("before") or {}
            after = entry.get("after") or {}
            amount_cents = max(
                int(after.get("refunded_cents") or 0) - int(before.get("refunded_cents") or 0),
                0,
            )
            invoice_id = str(entry.get("invoice_id") or "") or None
            if invoice_id:
                invoice_ids.add(invoice_id)
            total_refunded_cents += amount_cents
            refunds.append(
                {
                    "refund_at": _report_iso(entry.get("at")),
                    "invoice_id": invoice_id,
                    "invoice_number": None,
                    "payment_id": str(entry.get("payment_id") or "") or None,
                    "parent_id": None,
                    "student_id": None,
                    "amount_cents": amount_cents,
                    "reason": entry.get("reason"),
                    "actor_id": str(entry.get("actor_id") or "") or None,
                }
            )

        if invoice_ids:
            invoice_meta: dict[str, dict[str, Any]] = {}
            invoice_cursor = db["invoices"].find(
                {"academy_id": academy_id, "invoice_id": {"$in": sorted(invoice_ids)}},
                {"invoice_id": 1, "invoice_number": 1, "parent_id": 1, "student_id": 1},
            )
            async for invoice in invoice_cursor:
                invoice_meta[str(invoice.get("invoice_id"))] = {
                    "invoice_number": invoice.get("invoice_number"),
                    "parent_id": str(invoice.get("parent_id") or "") or None,
                    "student_id": str(invoice.get("student_id") or "") or None,
                }
            for row in refunds:
                meta = invoice_meta.get(row["invoice_id"] or "")
                if meta:
                    row.update(meta)

        credits: list[dict[str, Any]] = []
        total_credit_cents = 0
        credit_cursor = (
            db["account_credit_ledger"]
            .find(
                {
                    "academy_id": academy_id,
                    "created_at": {"$gte": start, "$lt": end},
                }
            )
            .sort([("created_at", -1)])
        )
        async for credit in credit_cursor:
            amount_cents = int(credit.get("amount_cents") or 0)
            total_credit_cents += amount_cents
            credits.append(
                {
                    "credit_id": str(credit.get("credit_id") or credit.get("_id")),
                    "created_at": _report_iso(credit.get("created_at")),
                    "parent_id": str(credit.get("parent_id") or "") or None,
                    "student_id": str(credit.get("student_id") or "") or None,
                    "invoice_id": str(credit.get("invoice_id") or "") or None,
                    "type": str(credit.get("type") or "") or None,
                    "status": str(credit.get("status") or "") or None,
                    "amount_cents": amount_cents,
                    "remaining_amount_cents": int(credit.get("remaining_amount_cents") or 0),
                    "reason": credit.get("reason"),
                }
            )

        return {
            "period": period,
            "total_refunded_cents": total_refunded_cents,
            "refund_count": len(refunds),
            "refunds": refunds,
            "total_credit_cents": total_credit_cents,
            "credit_count": len(credits),
            "credits": credits,
        }

    return get_refunds_report


def make_revenue_by_category_report(
    db: AsyncIOMotorDatabase[Any],
) -> Callable[[str], Awaitable[dict[str, Any]]]:
    """Cash-basis revenue by invoice-line category.

    Each ``payment_allocations`` row created in the month is prorated across the
    target invoice's positive lines by line amount, so category totals sum exactly
    to the money applied to invoices that month. Money received but not yet
    applied to any invoice is reported separately as ``unapplied_cents``.
    """
    from backend.v2.shared.tenancy import current_academy_id

    async def get_revenue_by_category_report(period: str) -> dict[str, Any]:
        academy_id = current_academy_id()
        start, end = month_bounds(period)

        allocated_by_invoice: dict[str, int] = {}
        allocation_cursor = db["payment_allocations"].find(
            {
                "academy_id": academy_id,
                "created_at": {"$gte": start, "$lt": end},
            },
            {"invoice_id": 1, "amount_cents": 1},
        )
        async for allocation in allocation_cursor:
            invoice_id = str(allocation.get("invoice_id") or "")
            amount_cents = int(allocation.get("amount_cents") or 0)
            if invoice_id and amount_cents > 0:
                allocated_by_invoice[invoice_id] = (
                    allocated_by_invoice.get(invoice_id, 0) + amount_cents
                )

        totals: dict[str, int] = {}
        labels: dict[str, str | None] = {}

        def _add(category: str, label: str | None, cents: int) -> None:
            if cents <= 0:
                return
            totals[category] = totals.get(category, 0) + cents
            if label and not labels.get(category):
                labels[category] = label

        invoice_ids = sorted(allocated_by_invoice)
        for index in range(0, len(invoice_ids), 500):
            batch = invoice_ids[index : index + 500]
            lines_by_invoice: dict[str, list[dict[str, Any]]] = {}
            line_cursor = db["invoice_lines"].find(
                {"academy_id": academy_id, "invoice_id": {"$in": batch}},
                {
                    "invoice_id": 1,
                    "line_type": 1,
                    "category": 1,
                    "category_label": 1,
                    "amount_cents": 1,
                },
            )
            async for line in line_cursor:
                lines_by_invoice.setdefault(str(line.get("invoice_id") or ""), []).append(line)
            for invoice_id in batch:
                allocated = allocated_by_invoice[invoice_id]
                lines = [
                    line
                    for line in lines_by_invoice.get(invoice_id, [])
                    if int(line.get("amount_cents") or 0) > 0
                ]
                positive_total = sum(int(line.get("amount_cents") or 0) for line in lines)
                if not lines or positive_total <= 0:
                    _add("uncategorized", None, allocated)
                    continue
                assigned = 0
                largest_category = ""
                largest_share = -1
                for line in lines:
                    line_cents = int(line.get("amount_cents") or 0)
                    share = allocated * line_cents // positive_total
                    category = str(line.get("category") or line.get("line_type") or "other")
                    label = line.get("category_label")
                    _add(category, str(label) if label else None, share)
                    assigned += share
                    if share > largest_share:
                        largest_share = share
                        largest_category = category
                remainder = allocated - assigned
                if remainder > 0 and largest_category:
                    _add(largest_category, None, remainder)

        unapplied_cents = 0
        unapplied_cursor = db["ledger_payments"].find(
            {
                "academy_id": academy_id,
                **ledger_payment_effective_window_query(start, end),
                "status": {"$in": _LEDGER_SUCCESS_STATUSES},
            },
            {"unapplied_amount_cents": 1, "paid_at": 1, "created_at": 1},
        )
        async for payment in unapplied_cursor:
            if ledger_payment_effective_month(payment) != period:
                continue
            unapplied_cents += max(int(payment.get("unapplied_amount_cents") or 0), 0)

        rows = [
            {
                "category": category,
                "category_label": labels.get(category),
                "amount_cents": cents,
            }
            for category, cents in sorted(totals.items(), key=lambda item: (-item[1], item[0]))
        ]
        return {
            "period": period,
            "total_allocated_cents": sum(totals.values()),
            "unapplied_cents": unapplied_cents,
            "rows": rows,
        }

    return get_revenue_by_category_report


def make_deposit_slip_report(
    db: AsyncIOMotorDatabase[Any],
) -> Callable[[str], Awaitable[dict[str, Any]]]:
    """Payments received grouped by day and payment method, for bank reconciliation.

    Gross money received per day (UTC, on ``paid_at`` falling back to ``created_at``);
    refunds are intentionally NOT netted out — a later refund does not change what
    was deposited on the day the payment arrived.
    """
    from backend.v2.shared.tenancy import current_academy_id

    async def get_deposit_slip_report(period: str) -> dict[str, Any]:
        academy_id = current_academy_id()
        start, end = month_bounds(period)

        day_totals: dict[str, dict[str, dict[str, int]]] = {}
        payment_cursor = db["ledger_payments"].find(
            {
                "academy_id": academy_id,
                **ledger_payment_effective_window_query(start, end),
                "status": {"$in": _LEDGER_SUCCESS_STATUSES},
            },
            {"amount_cents": 1, "payment_method": 1, "paid_at": 1, "created_at": 1},
        )
        async for payment in payment_cursor:
            if ledger_payment_effective_month(payment) != period:
                continue
            effective_at = ledger_payment_effective_at(payment)
            if effective_at is None:
                continue
            day = effective_at.date().isoformat()
            method = str(payment.get("payment_method") or "unknown")
            amount_cents = max(int(payment.get("amount_cents") or 0), 0)
            bucket = day_totals.setdefault(day, {}).setdefault(
                method, {"amount_cents": 0, "count": 0}
            )
            bucket["amount_cents"] += amount_cents
            bucket["count"] += 1

        days = []
        total_cents = 0
        total_count = 0
        for day in sorted(day_totals):
            methods: list[dict[str, Any]] = [
                {"method": method, "amount_cents": stats["amount_cents"], "count": stats["count"]}
                for method, stats in sorted(
                    day_totals[day].items(),
                    key=lambda item: (-item[1]["amount_cents"], item[0]),
                )
            ]
            day_cents = sum(int(m["amount_cents"]) for m in methods)
            day_count = sum(int(m["count"]) for m in methods)
            total_cents += day_cents
            total_count += day_count
            days.append(
                {"date": day, "total_cents": day_cents, "count": day_count, "methods": methods}
            )

        return {
            "period": period,
            "total_cents": total_cents,
            "count": total_count,
            "days": days,
        }

    return get_deposit_slip_report


def _csv_safe(value: Any) -> Any:
    """Neutralise spreadsheet formula injection in free-text CSV cells.

    Values starting with =, +, -, or @ execute as formulas when the export is
    opened in Excel/Sheets (or imported into QuickBooks); prefix with a quote.
    """
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return f"'{value}"
    return value


def make_financial_report_csv(db: AsyncIOMotorDatabase[Any]) -> object:
    """CSV renderers for the phase-3 financial reports.

    Returns an async callable ``(report_name, period) -> str | None``; ``None`` means
    the name is not a financial report and the caller should fall through to the
    legacy export branches.
    """
    get_refunds_report = make_refunds_report(db)
    get_revenue_by_category_report = make_revenue_by_category_report(db)
    get_deposit_slip_report = make_deposit_slip_report(db)

    async def financial_report_csv(report_name: str, period: str | None = None) -> str | None:
        if report_name not in {"refunds", "revenue-by-category", "deposit-slip", "quickbooks"}:
            return None
        effective_period = period or datetime.now(UTC).strftime("%Y-%m")
        out = io.StringIO()
        writer = csv.writer(out)
        if report_name == "refunds":
            report = await get_refunds_report(effective_period)
            writer.writerow(
                [
                    "type",
                    "date",
                    "invoice_id",
                    "invoice_number",
                    "payment_id",
                    "parent_id",
                    "student_id",
                    "amount_cents",
                    "reason",
                ]
            )
            for row in report["refunds"]:
                writer.writerow(
                    [
                        "refund",
                        row["refund_at"],
                        row["invoice_id"],
                        row["invoice_number"],
                        row["payment_id"],
                        row["parent_id"],
                        row["student_id"],
                        row["amount_cents"],
                        _csv_safe(row["reason"]),
                    ]
                )
            for row in report["credits"]:
                writer.writerow(
                    [
                        "credit",
                        row["created_at"],
                        row["invoice_id"],
                        None,
                        None,
                        row["parent_id"],
                        row["student_id"],
                        row["amount_cents"],
                        _csv_safe(row["reason"]),
                    ]
                )
        elif report_name == "revenue-by-category":
            report = await get_revenue_by_category_report(effective_period)
            writer.writerow(["period", "category", "category_label", "amount_cents"])
            for row in report["rows"]:
                writer.writerow(
                    [
                        effective_period,
                        _csv_safe(row["category"]),
                        _csv_safe(row["category_label"]),
                        row["amount_cents"],
                    ]
                )
            if report["unapplied_cents"]:
                writer.writerow(
                    [
                        effective_period,
                        "unapplied",
                        "Unapplied payments",
                        report["unapplied_cents"],
                    ]
                )
        elif report_name == "deposit-slip":
            report = await get_deposit_slip_report(effective_period)
            writer.writerow(["date", "method", "count", "amount_cents"])
            for day in report["days"]:
                for method_row in day["methods"]:
                    writer.writerow(
                        [
                            day["date"],
                            _csv_safe(method_row["method"]),
                            method_row["count"],
                            method_row["amount_cents"],
                        ]
                    )
        else:
            # Monthly summary journal entries in the QuickBooks Online CSV import
            # format. JE 1: cash received (debit Undeposited Funds, credit income by
            # category, balanced by an unapplied-payments line). JE 2: refunds given.
            revenue = await get_revenue_by_category_report(effective_period)
            deposits = await get_deposit_slip_report(effective_period)
            refunds = await get_refunds_report(effective_period)
            _, month_end = month_bounds(effective_period)
            journal_date = (month_end - timedelta(days=1)).strftime("%m/%d/%Y")
            writer.writerow(["JournalNo", "JournalDate", "Memo", "Account", "Debits", "Credits"])
            collected_cents = deposits["total_cents"]
            allocated_cents = revenue["total_allocated_cents"]
            if collected_cents or allocated_cents:
                memo = f"{effective_period} payments received"
                journal_no = f"{effective_period}-REV"
                writer.writerow(
                    [
                        journal_no,
                        journal_date,
                        memo,
                        "Undeposited Funds",
                        cents_to_dollars(collected_cents),
                        "",
                    ]
                )
                for row in revenue["rows"]:
                    account = _csv_safe(f"Income:{row['category_label'] or row['category']}")
                    writer.writerow(
                        [
                            journal_no,
                            journal_date,
                            memo,
                            account,
                            "",
                            cents_to_dollars(row["amount_cents"]),
                        ]
                    )
                balance_cents = collected_cents - allocated_cents
                if balance_cents > 0:
                    writer.writerow(
                        [
                            journal_no,
                            journal_date,
                            memo,
                            "Unapplied Customer Payments",
                            "",
                            cents_to_dollars(balance_cents),
                        ]
                    )
                elif balance_cents < 0:
                    writer.writerow(
                        [
                            journal_no,
                            journal_date,
                            memo,
                            "Unapplied Customer Payments",
                            cents_to_dollars(-balance_cents),
                            "",
                        ]
                    )
            refunded_cents = refunds["total_refunded_cents"]
            if refunded_cents:
                memo = f"{effective_period} refunds issued"
                journal_no = f"{effective_period}-REF"
                writer.writerow(
                    [
                        journal_no,
                        journal_date,
                        memo,
                        "Refunds Given",
                        cents_to_dollars(refunded_cents),
                        "",
                    ]
                )
                writer.writerow(
                    [
                        journal_no,
                        journal_date,
                        memo,
                        "Undeposited Funds",
                        "",
                        cents_to_dollars(refunded_cents),
                    ]
                )
        return out.getvalue()

    return financial_report_csv


def make_session_economics_report(db: AsyncIOMotorDatabase[Any]) -> object:
    """Returns an async callable for monthly session-level economics."""
    from backend.v2.shared.tenancy import current_academy_id

    async def get_session_economics(period: str) -> dict[str, Any]:
        academy_id = current_academy_id()
        start, end = month_bounds(period)

        occurrence_by_id: dict[str, str] = {}
        occurrences_by_session: dict[str, int] = {}
        occurrences_cursor = db["session_occurrences"].find(
            {
                "academy_id": academy_id,
                "start_at": {"$gte": start, "$lt": end},
                "status": {"$ne": "cancelled"},
                "is_payable": {"$ne": False},
            },
            {"occurrence_id": 1, "session_id": 1, "template_session_id": 1},
        )
        async for occurrence in occurrences_cursor:
            session_id = occurrence_session_id(occurrence)
            occurrence_id = str(occurrence.get("occurrence_id") or "")
            if not session_id or not occurrence_id:
                continue
            occurrence_by_id[occurrence_id] = session_id
            occurrences_by_session[session_id] = occurrences_by_session.get(session_id, 0) + 1

        session_ids = sorted(occurrences_by_session)
        sessions_by_id: dict[str, dict[str, Any]] = {}
        if session_ids:
            sessions_cursor = db["sessions"].find(
                {
                    "academy_id": academy_id,
                    "session_id": {"$in": session_ids},
                    "is_deleted": {"$ne": True},
                }
            )
            async for session in sessions_cursor:
                sessions_by_id[str(session.get("session_id") or session.get("_id"))] = session

        active_enrollments_by_session: dict[str, int] = {
            session_id: 0 for session_id in session_ids
        }
        enrollment_to_session: dict[str, str] = {}
        if session_ids:
            enrollments_cursor = db["enrollments"].find(
                {
                    "academy_id": academy_id,
                    "session_id": {"$in": session_ids},
                    "status": "active",
                    "is_deleted": {"$ne": True},
                },
                {"enrollment_id": 1, "session_id": 1},
            )
            async for enrollment in enrollments_cursor:
                session_id = str(enrollment.get("session_id") or "")
                enrollment_id = str(enrollment.get("enrollment_id") or "")
                if not session_id:
                    continue
                active_enrollments_by_session[session_id] = (
                    active_enrollments_by_session.get(session_id, 0) + 1
                )
                if enrollment_id:
                    enrollment_to_session[enrollment_id] = session_id

        expected_by_session: dict[str, int] = {}
        per_occurrence_by_session: dict[str, int] = {}
        monthly_fee_by_session: dict[str, int] = {}
        for session_id in session_ids:
            session = sessions_by_id.get(session_id, {})
            monthly_fee = int(session.get("amount_cents") or 0)
            enrollment_count = active_enrollments_by_session.get(session_id, 0)
            occurrence_count = occurrences_by_session.get(session_id, 0)
            monthly_fee_by_session[session_id] = monthly_fee
            expected_total = monthly_fee * enrollment_count
            expected_by_session[session_id] = expected_total
            per_occurrence_by_session[session_id] = (
                round_money_minor(Decimal(expected_total) / Decimal(occurrence_count))
                if occurrence_count
                else 0
            )

        paid_by_session: dict[str, int] = {session_id: 0 for session_id in session_ids}
        billed_unpaid_by_session: dict[str, int] = {session_id: 0 for session_id in session_ids}
        paid_enrollments_by_session: dict[str, set[str]] = {
            session_id: set() for session_id in session_ids
        }
        unpaid_enrollments_by_session: dict[str, set[str]] = {
            session_id: set() for session_id in session_ids
        }
        invoice_keys: set[str] = set()

        def session_for_doc(doc: dict[str, Any]) -> str | None:
            direct_session_id = str(doc.get("session_id") or "")
            if direct_session_id:
                return direct_session_id
            enrollment_id = str(doc.get("enrollment_id") or "")
            if enrollment_id:
                return enrollment_to_session.get(enrollment_id)
            return None

        invoices_cursor = db["invoices"].find(
            {
                "academy_id": academy_id,
                "period": period,
                "status": {"$nin": ["void", "waived", "cancelled"]},
                "is_deleted": {"$ne": True},
            }
        )
        async for invoice in invoices_cursor:
            invoice_keys.update(invoice_provider_keys(invoice))
            backfill_payment_id = invoice.get("backfill_payment_id")
            if backfill_payment_id:
                invoice_keys.add(str(backfill_payment_id))
            doc_session_id = session_for_doc(invoice)
            if doc_session_id is None or doc_session_id not in paid_by_session:
                continue
            paid = invoice_paid_cents(invoice)
            outstanding = invoice_outstanding_cents(invoice)
            paid_by_session[doc_session_id] += paid
            billed_unpaid_by_session[doc_session_id] += outstanding
            enrollment_id = str(invoice.get("enrollment_id") or "")
            if enrollment_id:
                if paid > 0 and outstanding == 0:
                    paid_enrollments_by_session[doc_session_id].add(enrollment_id)
                if outstanding > 0 or paid == 0:
                    unpaid_enrollments_by_session[doc_session_id].add(enrollment_id)

        payments_cursor = db["payments"].find(
            {
                "academy_id": academy_id,
                "period": period,
                "is_deleted": {"$ne": True},
            }
        )
        async for payment in payments_cursor:
            payment_keys = {
                str(value)
                for value in (
                    payment.get("invoice_id"),
                    payment.get("invoice_number"),
                    payment.get("payment_id"),
                    payment.get("stripe_invoice_id"),
                    payment.get("stripe_payment_intent_id"),
                )
                if value
            }
            if payment_keys & invoice_keys:
                continue
            doc_session_id = session_for_doc(payment)
            if doc_session_id is None or doc_session_id not in paid_by_session:
                continue
            paid = payment_collected_cents(payment)
            outstanding = payment_outstanding_cents(payment)
            paid_by_session[doc_session_id] += paid
            billed_unpaid_by_session[doc_session_id] += outstanding
            enrollment_id = str(payment.get("enrollment_id") or "")
            if enrollment_id:
                if paid > 0 and outstanding == 0:
                    paid_enrollments_by_session[doc_session_id].add(enrollment_id)
                if outstanding > 0 or paid == 0:
                    unpaid_enrollments_by_session[doc_session_id].add(enrollment_id)

        coach_payroll_by_session: dict[str, int] = {session_id: 0 for session_id in session_ids}
        payout_period_ids: list[str] = []
        payout_periods_cursor = db["payout_periods"].find(
            {
                "academy_id": academy_id,
                "period_start": {"$gte": start, "$lt": end},
            },
            {"period_id": 1},
        )
        async for payout_period in payout_periods_cursor:
            period_id = str(payout_period.get("period_id") or "")
            if period_id:
                payout_period_ids.append(period_id)
        if payout_period_ids:
            lines_cursor = db["payout_period_lines"].find(
                {
                    "academy_id": academy_id,
                    "period_id": {"$in": payout_period_ids},
                },
                {"occurrence_id": 1, "amount_minor": 1},
            )
            async for line in lines_cursor:
                line_session_id = occurrence_by_id.get(str(line.get("occurrence_id") or ""))
                if line_session_id is not None and line_session_id in coach_payroll_by_session:
                    coach_payroll_by_session[line_session_id] += int(line.get("amount_minor") or 0)

        rent_cents = 0
        other_expenses_cents = 0
        expenses_cursor = db["expenses"].find(
            {
                "academy_id": academy_id,
                "incurred_on": {"$gte": start, "$lt": end},
                "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
            }
        )
        async for expense in expenses_cursor:
            amount = int(expense.get("amount_cents") or 0)
            if str(expense.get("category") or "other") == "rent":
                rent_cents += amount
            else:
                other_expenses_cents += amount

        expected_total = sum(expected_by_session.values())
        rent_allocations = _allocate_report_amount(rent_cents, expected_by_session)
        other_allocations = _allocate_report_amount(other_expenses_cents, expected_by_session)

        rows: list[dict[str, Any]] = []
        for session_id in session_ids:
            session = sessions_by_id.get(session_id, {})
            expected_revenue = expected_by_session.get(session_id, 0)
            paid = paid_by_session.get(session_id, 0)
            unpaid = max(expected_revenue - paid, billed_unpaid_by_session.get(session_id, 0), 0)
            coach_payroll = coach_payroll_by_session.get(session_id, 0)
            rent = rent_allocations.get(session_id, 0)
            other = other_allocations.get(session_id, 0)
            profit = expected_revenue - coach_payroll - rent - other
            paid_student_count = len(paid_enrollments_by_session.get(session_id, set()))
            unpaid_student_count = max(
                active_enrollments_by_session.get(session_id, 0) - paid_student_count,
                len(unpaid_enrollments_by_session.get(session_id, set())),
            )
            rows.append(
                {
                    "session_id": session_id,
                    "title": str(
                        session.get("title")
                        or session.get("name")
                        or session.get("session_name")
                        or "Untitled session"
                    ),
                    "coach_name": str(session.get("coach_name") or "") or None,
                    "active_enrollment_count": active_enrollments_by_session.get(session_id, 0),
                    "paid_student_count": paid_student_count,
                    "unpaid_student_count": unpaid_student_count,
                    "monthly_fee_cents": monthly_fee_by_session.get(session_id, 0),
                    "payable_occurrence_count": occurrences_by_session.get(session_id, 0),
                    "expected_revenue_per_occurrence_cents": per_occurrence_by_session.get(
                        session_id, 0
                    ),
                    "expected_revenue_cents": expected_revenue,
                    "paid_cents": paid,
                    "unpaid_cents": unpaid,
                    "coach_payroll_cents": coach_payroll,
                    "rent_cents": rent,
                    "other_expenses_cents": other,
                    "expected_profit_cents": profit,
                    "profit_margin": round(profit / expected_revenue, 4)
                    if expected_revenue
                    else None,
                }
            )

        rows.sort(key=lambda row: (str(row["title"]).lower(), str(row["session_id"])))

        paid_total = sum(int(row["paid_cents"]) for row in rows)
        unpaid_total = sum(int(row["unpaid_cents"]) for row in rows)
        coach_payroll_total = sum(coach_payroll_by_session.values())
        expected_profit = expected_total - coach_payroll_total - rent_cents - other_expenses_cents
        empty_states: list[str] = []
        if not rows:
            empty_states.append("No payable session occurrences found for this month.")
        if rows and sum(active_enrollments_by_session.values()) == 0:
            empty_states.append("No active enrollments found for payable sessions.")
        if rows and not payout_period_ids:
            empty_states.append("No payout periods generated for this month.")
        if rows and paid_total == 0 and unpaid_total == 0:
            empty_states.append("No attributable billing rows found for these sessions.")

        return {
            "period": period,
            "summary": {
                "expected_revenue_cents": expected_total,
                "paid_cents": paid_total,
                "unpaid_cents": unpaid_total,
                "coach_payroll_cents": coach_payroll_total,
                "rent_cents": rent_cents,
                "other_expenses_cents": other_expenses_cents,
                "expected_profit_cents": expected_profit,
                "profit_margin": round(expected_profit / expected_total, 4)
                if expected_total
                else None,
            },
            "sessions": rows,
            "empty_states": empty_states,
        }

    return get_session_economics


def _allocate_report_amount(
    total_cents: int, expected_by_session: dict[str, int]
) -> dict[str, int]:
    expected_total = sum(expected_by_session.values())
    allocations = {session_id: 0 for session_id in expected_by_session}
    if total_cents <= 0 or expected_total <= 0:
        return allocations

    remaining = total_cents
    session_ids = sorted(expected_by_session)
    for index, session_id in enumerate(session_ids):
        if index == len(session_ids) - 1:
            allocations[session_id] = remaining
            break
        amount = round_money_minor(
            Decimal(total_cents)
            * Decimal(expected_by_session.get(session_id, 0))
            / Decimal(expected_total)
        )
        allocations[session_id] = amount
        remaining -= amount
    return allocations


def make_list_enrollment_events(db: Any) -> object:
    from backend.v2.shared.tenancy import current_academy_id

    async def list_enrollment_events(enrollment_id: str) -> list[dict[str, Any]]:
        academy_id = current_academy_id()
        cursor = db.enrollment_events.find(
            {"enrollment_id": enrollment_id, "academy_id": academy_id},
            sort=[("occurred_at", 1)],
        )
        results = []
        async for doc in cursor:
            results.append(
                {
                    "event_id": str(doc.get("event_id") or doc.get("_id", "")),
                    "event_type": str(doc.get("event_type", "")),
                    "effective_date": str(doc.get("effective_at", ""))[:10],
                    "actor_id": str(doc.get("actor_id", "")),
                    "reason": doc.get("reason"),
                    "billing_result": doc.get("billing_result"),
                    "credit_id": doc.get("credit_id"),
                }
            )
        return results

    return list_enrollment_events
