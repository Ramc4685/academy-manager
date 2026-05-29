"""# FINANCE — admin-facing reads + writes inside Billing.

Marked for promotion to its own Finance context when payout, expense,
reconciliation, or revenue-reporting rules become independently complex
(per ADR-0006 promotion trigger).

For now: simple CRUD aggregations.
"""

# FINANCE
from __future__ import annotations

from calendar import monthrange
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import PaymentRepository
from backend.v2.shared.http.errors import DomainError
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository
from backend.v2.shared.tenancy.context import current_academy_id


# FINANCE
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
    expected_revenue_cents: int | None = None
    students_count: int | None = None
    sessions_count: int | None = None
    rule_label: str | None = None


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
            deleted_at=doc.get("deleted_at"),  # type: ignore[arg-type]
            deleted_by=doc.get("deleted_by"),  # type: ignore[arg-type]
            delete_reason=doc.get("delete_reason"),  # type: ignore[arg-type]
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
        persisted = [self._to_domain(d) async for d in cursor]
        if persisted:
            return persisted
        return await self._derive_from_coach_attendance()

    async def list_for_coach(self, coach_id: str) -> list[Payout]:
        cursor = self._find_many({"coach_id": coach_id}, sort=[("period_start", -1)], limit=500)
        return [self._to_domain(d) async for d in cursor]

    async def _derive_from_coach_attendance(self) -> list[Payout]:
        academy_id = current_academy_id()
        attendance_rows = [
            doc
            async for doc in self._find_many_in_collection(
                "coach_attendance",
                {
                    "status": "present",
                },
                sort=[("marked_at", 1)],
            )
        ]
        if not attendance_rows:
            return []

        occurrence_ids = sorted({str(row["occurrence_id"]) for row in attendance_rows})
        occurrence_docs = {
            str(doc["occurrence_id"]): doc
            async for doc in self._find_many_in_collection(
                "session_occurrences",
                {
                    "occurrence_id": {"$in": occurrence_ids},
                    "is_payable": {"$ne": False},
                    "status": {"$ne": "cancelled"},
                },
            )
        }
        if not occurrence_docs:
            return []

        students_by_occurrence: dict[str, set[str]] = {
            occurrence_id: set() for occurrence_id in occurrence_ids
        }
        student_cursor = self._find_many_in_collection(
            "attendance",
            {
                "occurrence_id": {"$in": occurrence_ids},
                "status": {"$in": ["present", "late"]},
            },
            {"occurrence_id": 1, "student_id": 1},
        )
        async for row in student_cursor:
            if row.get("student_id"):
                students_by_occurrence.setdefault(str(row["occurrence_id"]), set()).add(
                    str(row["student_id"])
                )

        grouped: dict[tuple[str, str], dict[str, object]] = {}
        for attendance in attendance_rows:
            occurrence_id = str(attendance["occurrence_id"])
            occurrence = occurrence_docs.get(occurrence_id)
            if occurrence is None:
                continue
            coach_id = str(attendance["coach_id"])
            start_at = occurrence["start_at"]
            amount = await self._attendance_amount_minor(attendance, coach_id, start_at, occurrence)
            if amount is None:
                continue
            period = start_at.strftime("%Y-%m")
            bucket = grouped.setdefault(
                (period, coach_id),
                {"amount": 0, "students": set(), "occurrences": set()},
            )
            bucket["amount"] = int(bucket["amount"]) + amount
            bucket["occurrences"].add(occurrence_id)  # type: ignore[attr-defined]
            bucket["students"].update(students_by_occurrence.get(occurrence_id, set()))  # type: ignore[attr-defined]

        payouts: list[Payout] = []
        for (period, coach_id), bucket in grouped.items():
            amount_cents = int(bucket["amount"])
            if amount_cents <= 0:
                continue
            period_start, period_end = _period_window(period)
            payouts.append(
                Payout(
                    payout_id=f"attendance:{period}:{coach_id}",
                    academy_id=academy_id,
                    coach_id=coach_id,
                    amount_cents=amount_cents,
                    period_start=period_start,
                    period_end=period_end,
                    students_count=len(bucket["students"]),  # type: ignore[arg-type]
                    sessions_count=len(bucket["occurrences"]),  # type: ignore[arg-type]
                    rule_label="Coach attendance",
                )
            )
        return sorted(payouts, key=lambda payout: payout.period_start, reverse=True)

    async def _attendance_amount_minor(
        self,
        attendance: dict[str, object],
        coach_id: str,
        start_at: datetime,
        occurrence: dict[str, object],
    ) -> int | None:
        if attendance.get("rate_override_minor") is not None:
            return int(attendance["rate_override_minor"])

        rate = await self._find_one_in_collection(
            "coach_rates",
            {
                "coach_id": coach_id,
                "effective_from": {"$lte": start_at},
                "$or": [
                    {"effective_until": {"$exists": False}},
                    {"effective_until": None},
                    {"effective_until": {"$gt": start_at}},
                ],
                "status": {"$ne": "superseded"},
            },
            sort=[("effective_from", -1)],
        )
        if rate is None:
            return None

        amount_minor = int(rate.get("amount_minor", rate.get("amount_cents", 0)))
        if rate.get("billing_unit", "per_session") == "per_session":
            return amount_minor

        end_at = occurrence["end_at"]
        minutes = Decimal((end_at - start_at).total_seconds()) / Decimal(60)  # type: ignore[operator]
        return int(
            (Decimal(amount_minor) * minutes / Decimal(60)).quantize(
                Decimal("1"), rounding=ROUND_HALF_EVEN
            )
        )


def _period_window(period: str) -> tuple[datetime, datetime]:
    year, month = (int(part) for part in period.split("-", 1))
    period_start = datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        period_end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        last_day = monthrange(year, month)[1]
        period_end = datetime(year, month, last_day, 23, 59, 59, 999000, tzinfo=UTC)
    return period_start, period_end


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
