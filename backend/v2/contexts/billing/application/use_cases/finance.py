"""# FINANCE — admin-facing reads + writes inside Billing.

Marked for promotion to its own Finance context when payout, expense,
reconciliation, or revenue-reporting rules become independently complex
(per ADR-0006 promotion trigger).

For now: simple CRUD aggregations.
"""

# FINANCE
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.admin_money import month_label
from backend.v2.contexts.billing.application.ports import PaymentRepository
from backend.v2.shared.http.errors import DomainError
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository
from backend.v2.shared.tenancy.context import TenantContextUnset, current_academy_id
from backend.v2.shared.time import (
    AcademyTimezoneReader,
    ensure_utc,
    resolve_reporting_timezone,
)
from backend.v2.shared.time.academy_timezone import UTC_NAME

# FINANCE

# Which recorded student marks count as "the student attended" (#554).
# ``voided`` is deliberately absent: an annulled mark counts as unmarked for
# payroll, exactly as if the coach had never taken attendance for that row.
ATTENDED_STATUSES = ("present", "late")


class Expense(BaseModel):
    model_config = {"frozen": True}
    expense_id: str
    academy_id: str
    category: Literal["rent", "equipment", "salary", "marketing", "other"]
    amount_cents: int = Field(ge=0)
    note: str = ""
    incurred_on: datetime
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    delete_reason: str | None = None


class ExpenseNotFound(DomainError):
    code = "Finance.ExpenseNotFound"
    status_code = 404


class TuitionDiscountCategorySummary(BaseModel):
    model_config = {"frozen": True}

    category: str
    discount_cents: int = Field(ge=0)


class TuitionDiscountSummary(BaseModel):
    model_config = {"frozen": True}

    period: str
    gross_tuition_cents: int = Field(ge=0)
    discount_cents: int = Field(ge=0)
    net_tuition_cents: int = Field(ge=0)
    by_category: list[TuitionDiscountCategorySummary]


class MongoTuitionDiscountSummaryQuery(TenantScopedRepository):
    collection_name = "invoice_lines"

    async def execute(self, period: str) -> TuitionDiscountSummary:
        invoice_ids: list[str] = []
        async for invoice in self._find_many_in_collection(
            "invoices",
            {"period": period, "status": {"$ne": "void"}},
            {"invoice_id": 1},
        ):
            invoice_id = invoice.get("invoice_id")
            if invoice_id:
                invoice_ids.append(str(invoice_id))

        gross_tuition_cents = 0
        discount_cents = 0
        by_category: dict[str, int] = {}
        if invoice_ids:
            async for line in self._find_many({"invoice_id": {"$in": invoice_ids}}):
                amount = int(line.get("amount_cents", 0))
                if line.get("source_type") == "tuition_discount":
                    value = abs(amount)
                    discount_cents += value
                    category = str(line.get("category") or "other")
                    by_category[category] = by_category.get(category, 0) + value
                elif line.get("line_type") == "tuition":
                    gross_tuition_cents += amount

        rows = [
            TuitionDiscountCategorySummary(category=category, discount_cents=value)
            for category, value in sorted(
                by_category.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]
        return TuitionDiscountSummary(
            period=period,
            gross_tuition_cents=gross_tuition_cents,
            discount_cents=discount_cents,
            net_tuition_cents=max(gross_tuition_cents - discount_cents, 0),
            by_category=rows,
        )


# FINANCE
class MongoExpenseRepository(TenantScopedRepository):
    collection_name = "expenses"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Expense:
        return Expense(
            expense_id=str(doc["expense_id"]),
            academy_id=str(doc["academy_id"]),
            category=doc.get("category", "other"),
            amount_cents=int(doc["amount_cents"]),
            note=str(doc.get("note", "")),
            incurred_on=doc["incurred_on"],
            deleted_at=doc.get("deleted_at"),
            deleted_by=doc.get("deleted_by"),
            delete_reason=doc.get("delete_reason"),
        )

    async def add(self, e: Expense) -> None:
        await self._insert_one(
            {k: v for k, v in e.model_dump(mode="python").items() if k != "academy_id"}
        )

    async def get(self, expense_id: str) -> Expense | None:
        doc = await self._find_one({"expense_id": expense_id, "deleted_at": None})
        return self._to_domain(doc) if doc else None

    async def update(self, e: Expense) -> None:
        doc = e.model_dump(mode="python")
        result = await self._update_one(
            {"expense_id": e.expense_id, "deleted_at": None},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
        )
        if result.matched_count == 0:
            raise ExpenseNotFound("expense missing", expense_id=e.expense_id)

    async def soft_delete(self, expense_id: str, *, actor_id: str, reason: str) -> None:
        result = await self._update_one(
            {"expense_id": expense_id, "deleted_at": None},
            {
                "$set": {
                    "deleted_at": datetime.now(UTC),
                    "deleted_by": actor_id,
                    "delete_reason": reason,
                }
            },
        )
        if result.matched_count == 0:
            raise ExpenseNotFound("expense missing", expense_id=expense_id)

    async def list_recent(self, limit: int = 200) -> list[Expense]:
        cursor = self._find_many({"deleted_at": None}, sort=[("incurred_on", -1)], limit=limit)
        return [self._to_domain(d) async for d in cursor]


# FINANCE
class RecordExpenseCommand(BaseModel):
    model_config = {"frozen": True}
    category: Literal["rent", "equipment", "salary", "marketing", "other"]
    amount_cents: int = Field(ge=0)
    note: str = ""
    incurred_on: datetime | None = None


# FINANCE
class RecordExpense:
    def __init__(
        self, *, expenses: MongoExpenseRepository, academy_id: str | Callable[[], str]
    ) -> None:
        self._expenses = expenses
        self._academy_id = academy_id

    async def execute(self, cmd: RecordExpenseCommand) -> Expense:
        e = Expense(
            expense_id=str(new_ulid()),
            # Resolved per call: composition passes the request-tenant callable.
            academy_id=(self._academy_id() if callable(self._academy_id) else self._academy_id),
            category=cmd.category,
            amount_cents=cmd.amount_cents,
            note=cmd.note,
            incurred_on=cmd.incurred_on or datetime.now(UTC),
        )
        await self._expenses.add(e)
        return e


class EditExpenseCommand(BaseModel):
    model_config = {"frozen": True}
    expense_id: str
    category: Literal["rent", "equipment", "salary", "marketing", "other"] | None = None
    amount_cents: int | None = Field(default=None, ge=0)
    note: str | None = None
    incurred_on: datetime | None = None
    actor_id: str | None = None
    reason: str | None = None


class EditExpense:
    def __init__(self, *, expenses: MongoExpenseRepository) -> None:
        self._expenses = expenses

    async def execute(self, cmd: EditExpenseCommand) -> Expense:
        current = await self._expenses.get(cmd.expense_id)
        if current is None:
            raise ExpenseNotFound("expense missing", expense_id=cmd.expense_id)
        update: dict[str, object] = {}
        for field_name in ("category", "amount_cents", "note", "incurred_on"):
            value = getattr(cmd, field_name)
            if value is not None:
                update[field_name] = value
        edited = current.model_copy(update=update)
        await self._expenses.update(edited)
        return edited


class DeleteExpenseCommand(BaseModel):
    model_config = {"frozen": True}
    expense_id: str
    actor_id: str
    reason: str


class DeleteExpense:
    def __init__(self, *, expenses: MongoExpenseRepository) -> None:
        self._expenses = expenses

    async def execute(self, cmd: DeleteExpenseCommand) -> None:
        await self._expenses.soft_delete(
            cmd.expense_id,
            actor_id=cmd.actor_id,
            reason=cmd.reason,
        )


# FINANCE
class AcademyRevenueQuery:
    """Aggregate revenue = sum(payments.amount_cents - payments.refunded_cents)
    grouped by month for the last N months.
    """

    def __init__(
        self,
        *,
        payments: PaymentRepository,
        academy_timezone: AcademyTimezoneReader | None = None,
    ) -> None:
        self._payments = payments
        self._academy_timezone = academy_timezone

    async def _reporting_timezone(self) -> str:
        """The academy's clock, or UTC when no reader/tenant is wired (#608)."""
        if self._academy_timezone is None:
            return UTC_NAME
        try:
            academy_id = current_academy_id()
        except TenantContextUnset:
            return UTC_NAME
        return await resolve_reporting_timezone(self._academy_timezone, academy_id)

    async def execute(self, parent_id_filter: str | None = None) -> dict[str, int]:
        # Wave 3 keeps this simple: walk every payment for the parent (or all)
        # and bucket by YYYY-MM. Production scale would use a Mongo aggregation.
        timezone_name = await self._reporting_timezone()
        result: dict[str, int] = {}
        payments = (
            await self._payments.list_for_parent(parent_id_filter)
            if parent_id_filter
            else await self._payments.list_all()
        )
        for p in payments:
            if p.status not in ("succeeded", "partially_refunded", "refunded"):
                continue
            net = p.amount_cents - p.refunded_cents
            key = month_label(ensure_utc(p.created_at), timezone_name)
            result[key] = result.get(key, 0) + net
        return result
