"""Admin/Comms/Finance indexes (Wave 3)."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0060"


async def up(db: AsyncIOMotorDatabase) -> None:
    messages = db["messages"]
    await messages.create_index(
        "message_id",
        unique=True,
        name="message_id_unique",
        partialFilterExpression={"message_id": {"$type": "string"}},
    )
    await messages.create_index(
        [("academy_id", 1), ("recipient_id", 1), ("created_at", -1)],
        name="recipient_inbox",
    )
    await messages.create_index(
        [("academy_id", 1), ("kind", 1), ("created_at", -1)],
        name="kind_timeline",
    )

    # FINANCE
    expenses = db["expenses"]
    await expenses.create_index(
        "expense_id",
        unique=True,
        name="expense_id_unique",
        partialFilterExpression={"expense_id": {"$type": "string"}},
    )
    await expenses.create_index(
        [("academy_id", 1), ("incurred_on", -1)],
        name="academy_expenses_timeline",
    )

    # FINANCE
    payouts = db["payouts"]
    await payouts.create_index(
        "payout_id",
        unique=True,
        name="payout_id_unique",
        partialFilterExpression={"payout_id": {"$type": "string"}},
    )
    await payouts.create_index(
        [("academy_id", 1), ("coach_id", 1), ("period_start", -1)],
        name="coach_payouts_timeline",
    )

    audit = db["audit_logs"]
    await audit.create_index([("academy_id", 1), ("created_at", -1)], name="academy_audit_timeline")
