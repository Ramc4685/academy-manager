"""BLNO moves to the 1st/5th billing calendar on 2027-01-01 (L8, owner decision).

From that day BLNO's invoices are due four days after generation (the 5th for
a run on the 1st), autopay charges on the generation day, and manual payers
are reminded on the due date and 3 and 7 days after it. December runs on the
current schedule.

This writes a dated ``schedule_change`` onto BLNO's ``billing_settings``
document; ``BillingSettings.effective`` applies it on read from that day, and
the next settings write persists the promoted values. The base fields are not
touched.

Production BLNO only (``acad_blno_badminton``, as in 0207): every other
academy, the local seed and an empty database are untouched. Idempotent: a
change already present (this one, or one an operator wrote) is left alone.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0231_blno_billing_calendar"

log = logging.getLogger(__name__)

BLNO_ACADEMY_ID = "acad_blno_badminton"
SCHEDULE_CHANGE = {
    "effective_from": datetime(2027, 1, 1, tzinfo=UTC),
    "invoice_due_days": 4,
    "autopay_charge_offset_days": 0,
    "reminder_days": [0, 3, 7],
}


async def up(db: AsyncIOMotorDatabase[Any]) -> None:
    if await db["academies"].find_one({"academy_id": BLNO_ACADEMY_ID}, {"_id": 1}) is None:
        return
    settings = db["billing_settings"]
    doc = await settings.find_one({"academy_id": BLNO_ACADEMY_ID}, {"schedule_change": 1})
    if doc is None:
        await settings.insert_one(
            {"academy_id": BLNO_ACADEMY_ID, "schedule_change": SCHEDULE_CHANGE}
        )
    elif doc.get("schedule_change"):
        log.info("0231: BLNO already has a schedule_change; leaving it alone")
        return
    else:
        await settings.update_one(
            {"academy_id": BLNO_ACADEMY_ID, "schedule_change": None},
            {"$set": {"schedule_change": SCHEDULE_CHANGE}},
        )
    log.info("0231: BLNO billing calendar change scheduled for 2027-01-01")
