"""# FINANCE — admin-facing reads + writes inside Billing.

Marked for promotion to its own Finance context when payout, expense,
reconciliation, or revenue-reporting rules become independently complex
(per ADR-0006 promotion trigger).

For now: simple CRUD aggregations.
"""

# FINANCE
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import PaymentRepository
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository


# FINANCE
class Expense(BaseModel):
    model_config = {"frozen": True}
    expense_id: str
    academy_id: str
    category: Literal["rent", "equipment", "salary", "marketing", "other"]
    amount_cents: int = Field(ge=0)
    note: str = ""
    incurred_on: datetime


# FINANCE
class Payout(BaseModel):
    model_config = {"frozen": True}
    payout_id: str
    academy_id: str
    coach_id: str
    amount_cents: int = Field(ge=0)
    period_start: datetime
    period_end: datetime
    paid_at: datetime | None = None


# FINANCE
class MongoExpenseRepository(TenantScopedRepository):
    collection_name = "expenses"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Expense:
        return Expense(
            expense_id=str(doc["expense_id"]),
            academy_id=str(doc["academy_id"]),
            category=doc.get("category", "other"),  # type: ignore[arg-type]
            amount_cents=int(doc["amount_cents"]),  # type: ignore[arg-type]
            note=str(doc.get("note", "")),
            incurred_on=doc["incurred_on"],  # type: ignore[arg-type]
        )

    async def add(self, e: Expense) -> None:
        await self._insert_one({k: v for k, v in e.model_dump(mode="python").items() if k != "academy_id"})

    async def list_recent(self, limit: int = 200) -> list[Expense]:
        cursor = self._find_many({}, sort=[("incurred_on", -1)], limit=limit)
        return [self._to_domain(d) async for d in cursor]


# FINANCE
class MongoPayoutRepository(TenantScopedRepository):
    collection_name = "payouts"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Payout:
        return Payout(
            payout_id=str(doc["payout_id"]),
            academy_id=str(doc["academy_id"]),
            coach_id=str(doc["coach_id"]),
            amount_cents=int(doc["amount_cents"]),  # type: ignore[arg-type]
            period_start=doc["period_start"],  # type: ignore[arg-type]
            period_end=doc["period_end"],  # type: ignore[arg-type]
            paid_at=doc.get("paid_at"),  # type: ignore[arg-type]
        )

    async def list_all(self) -> list[Payout]:
        cursor = self._find_many({}, sort=[("period_start", -1)], limit=500)
        return [self._to_domain(d) async for d in cursor]

    async def list_for_coach(self, coach_id: str) -> list[Payout]:
        cursor = self._find_many({"coach_id": coach_id}, sort=[("period_start", -1)], limit=500)
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
    def __init__(self, *, expenses: MongoExpenseRepository, academy_id: str) -> None:
        self._expenses = expenses
        self._academy_id = academy_id

    async def execute(self, cmd: RecordExpenseCommand) -> Expense:
        e = Expense(
            expense_id=str(new_ulid()),
            academy_id=self._academy_id,
            category=cmd.category,
            amount_cents=cmd.amount_cents,
            note=cmd.note,
            incurred_on=cmd.incurred_on or datetime.now(UTC),
        )
        await self._expenses.add(e)
        return e


# FINANCE
class AcademyRevenueQuery:
    """Aggregate revenue = sum(payments.amount_cents - payments.refunded_cents)
    grouped by month for the last N months.
    """

    def __init__(self, *, payments: PaymentRepository) -> None:
        self._payments = payments

    async def execute(self, parent_id_filter: str | None = None) -> dict[str, int]:
        # Wave 3 keeps this simple: walk every payment for the parent (or all)
        # and bucket by YYYY-MM. Production scale would use a Mongo aggregation.
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
            key = p.created_at.strftime("%Y-%m")
            result[key] = result.get(key, 0) + net
        return result
