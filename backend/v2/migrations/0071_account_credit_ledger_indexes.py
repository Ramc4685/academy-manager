from __future__ import annotations


version = "0071_account_credit_ledger_indexes"


async def up(db) -> None:
    await db.account_credit_ledger.create_index(
        [("academy_id", 1), ("parent_id", 1), ("status", 1)]
    )
    await db.account_credit_ledger.create_index([("academy_id", 1), ("expires_at", 1)])
    await db.credit_applications.create_index(
        [("academy_id", 1), ("credit_id", 1), ("invoice_id", 1)],
        unique=True,
    )
