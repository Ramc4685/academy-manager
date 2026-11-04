"""Parent monthly report card claims.

Unique ``(academy_id, parent_id, digest_date)`` on ``parent_report_card_sends``,
the same idempotency index the parent digest has (migration 0148), with
``digest_date`` holding the report month (``YYYY-MM``): a family gets at most
one report card per academy per month.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0214_parent_report_card_sends"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    sends = db["parent_report_card_sends"]
    await sends.create_index("digest_id", unique=True, name="parent_report_card_send_id_unique")
    await sends.create_index(
        [("academy_id", 1), ("parent_id", 1), ("digest_date", 1)],
        unique=True,
        name="parent_report_card_sends_academy_parent_month_unique",
    )
