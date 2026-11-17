"""Occurrence documents the materialiser writes, and the started-today insert.

Lives outside ``admin.py`` because that file is at its line budget.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def occurrence_fields(row: dict[str, Any]) -> dict[str, Any]:
    """The scheduled shape of a materialised occurrence (no ids)."""
    return {
        "session_id": row["session_id"],
        "template_session_id": row["template_session_id"],
        "start_at": row["start_at"],
        "end_at": row["end_at"],
        "status": row["status"],
        "scheduled_coach_id": row["scheduled_coach_id"],
        "actual_coach_id": None,
        "substitute_coach_id": None,
        "assistant_coach_ids": row["assistant_coach_ids"],
        "is_billable": True,
        "is_payable": True,
    }


async def insert_started_today(
    db: Any, academy_id: str, session_id: str, row: dict[str, Any], zone_name: str, now: datetime
) -> None:
    """Create today's already-started occurrence only if the class has no row yet today.

    Never rewrites an existing row (it may be cancelled or covered), and any
    earlier row for this class today (e.g. before a time edit) blocks the
    insert, so a day never gets two payable classes.
    """
    local_day = (
        row["start_at"]
        .astimezone(ZoneInfo(zone_name))
        .replace(hour=0, minute=0, second=0, microsecond=0)
    )
    same_day = {
        "academy_id": academy_id,
        "$or": [{"session_id": session_id}, {"template_session_id": session_id}],
        "start_at": {"$gte": local_day, "$lt": now},
    }
    if await db["session_occurrences"].find_one(same_day):
        return
    await db["session_occurrences"].update_one(
        {"academy_id": academy_id, "occurrence_id": row["occurrence_id"]},
        {
            "$setOnInsert": {
                "academy_id": academy_id,
                "occurrence_id": row["occurrence_id"],
                **occurrence_fields(row),
            }
        },
        upsert=True,
    )
