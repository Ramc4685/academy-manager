from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.finance import (
    DeleteExpense,
    DeleteExpenseCommand,
    EditExpense,
    EditExpenseCommand,
    Expense,
    ExpenseNotFound,
    MongoExpenseRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope


@dataclass
class FakeExpenseStore:
    rows: dict[str, Expense] = field(default_factory=dict)
    edits: list[Expense] = field(default_factory=list)
    deleted: list[tuple[str, str, str]] = field(default_factory=list)

    async def get(self, expense_id: str) -> Expense | None:
        return self.rows.get(expense_id)

    async def update(self, expense: Expense) -> None:
        self.rows[expense.expense_id] = expense
        self.edits.append(expense)

    async def soft_delete(self, expense_id: str, *, actor_id: str, reason: str) -> None:
        if expense_id not in self.rows:
            raise ExpenseNotFound("expense missing", expense_id=expense_id)
        self.deleted.append((expense_id, actor_id, reason))


def _expense() -> Expense:
    return Expense(
        expense_id="exp-1",
        academy_id="acad",
        category="equipment",
        amount_cents=4500,
        note="Shuttles",
        incurred_on=datetime(2026, 5, 20, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_admin_can_edit_existing_expense() -> None:
    store = FakeExpenseStore(rows={"exp-1": _expense()})
    use_case = EditExpense(expenses=store)

    updated = await use_case.execute(
        EditExpenseCommand(
            expense_id="exp-1",
            category="marketing",
            amount_cents=9900,
            note="Tournament flyers",
            incurred_on=datetime(2026, 5, 21, tzinfo=UTC),
            actor_id="admin-1",
            reason="receipt correction",
        )
    )

    assert updated.category == "marketing"
    assert updated.amount_cents == 9900
    assert updated.note == "Tournament flyers"
    assert updated.incurred_on == datetime(2026, 5, 21, tzinfo=UTC)
    assert store.edits == [updated]


@pytest.mark.asyncio
async def test_admin_soft_deletes_expense_with_reason() -> None:
    store = FakeExpenseStore(rows={"exp-1": _expense()})
    use_case = DeleteExpense(expenses=store)

    await use_case.execute(
        DeleteExpenseCommand(
            expense_id="exp-1",
            actor_id="admin-1",
            reason="duplicate receipt",
        )
    )

    assert store.deleted == [("exp-1", "admin-1", "duplicate receipt")]


@pytest.mark.asyncio
async def test_expense_edit_and_delete_raise_not_found_for_missing_or_cross_tenant_rows() -> None:
    store = FakeExpenseStore(rows={})

    with pytest.raises(ExpenseNotFound):
        await EditExpense(expenses=store).execute(
            EditExpenseCommand(
                expense_id="missing-expense",
                note="Blocked",
                actor_id="admin-1",
                reason="wrong tenant or missing",
            )
        )

    with pytest.raises(ExpenseNotFound):
        await DeleteExpense(expenses=store).execute(
            DeleteExpenseCommand(
                expense_id="missing-expense",
                actor_id="admin-1",
                reason="wrong tenant or missing",
            )
        )

    assert store.edits == []
    assert store.deleted == []


@pytest.mark.asyncio
async def test_mongo_expense_edit_and_delete_do_not_cross_tenant_boundary() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test_db"]
    await db["expenses"].insert_one(
        {
            "expense_id": "exp-shared",
            "academy_id": "academy-b",
            "category": "equipment",
            "amount_cents": 4500,
            "note": "Other tenant receipt",
            "incurred_on": datetime(2026, 5, 20, tzinfo=UTC),
        }
    )

    with tenant_scope("academy-a"):
        repo = MongoExpenseRepository(db)
        with pytest.raises(ExpenseNotFound):
            await EditExpense(expenses=repo).execute(
                EditExpenseCommand(
                    expense_id="exp-shared",
                    note="Should not apply",
                    actor_id="admin-1",
                    reason="tenant mismatch",
                )
            )
        with pytest.raises(ExpenseNotFound):
            await DeleteExpense(expenses=repo).execute(
                DeleteExpenseCommand(
                    expense_id="exp-shared",
                    actor_id="admin-1",
                    reason="tenant mismatch",
                )
            )

    row = await db["expenses"].find_one({"expense_id": "exp-shared"})
    assert row["note"] == "Other tenant receipt"
    assert row.get("deleted_at") is None
