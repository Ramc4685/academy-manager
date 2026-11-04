"""Prospect email opt-outs (inquiry acknowledgement, AI strategy Phase 1 #2).

Unique ``(academy_id, email)`` on ``email_prospect_opt_outs``: one row per
address per academy, written by the prospect unsubscribe page and read by
``ProspectOptOutGate`` before any email to a ``crm_contacts`` row. Partial on
``{"email": {"$gt": ""}}``, the planner-usable shape (#878).
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0217_email_prospect_opt_outs"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["email_prospect_opt_outs"].create_index(
        [("academy_id", 1), ("email", 1)],
        unique=True,
        partialFilterExpression={"email": {"$gt": ""}},
        name="email_prospect_opt_outs_academy_email_unique",
    )
