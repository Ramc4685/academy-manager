"""Class recap collections (new, empty: no backfill).

* ``class_recaps_occurrence_uq``: unique ``(academy_id, occurrence_id)``, one
  shared recap per dated class; the insert of revision 1 relies on it to
  refuse a second first write. Also serves the parent's ``$in`` lookup by the
  occurrences their child attended.
* ``class_recap_reports_report_uq``: unique ``(academy_id, report_id)``,
  insert-only reports, so a replayed submit never stores twice.
* ``class_recap_reports_occurrence_idx``: reports listed per class.
* ``class_recap_reports_handoff_idx``: the owner's open handoffs
  (``outcome``, unresolved), newest first.

Re-running is a no-op.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0243_class_recaps_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["class_recaps"].create_index(
        [("academy_id", 1), ("occurrence_id", 1)], unique=True, name="class_recaps_occurrence_uq"
    )
    reports = db["class_recap_reports"]
    await reports.create_index(
        [("academy_id", 1), ("report_id", 1)], unique=True, name="class_recap_reports_report_uq"
    )
    await reports.create_index(
        [("academy_id", 1), ("occurrence_id", 1), ("submitted_at", 1)],
        name="class_recap_reports_occurrence_idx",
    )
    await reports.create_index(
        [("academy_id", 1), ("outcome", 1), ("resolved_at", 1), ("submitted_at", -1)],
        name="class_recap_reports_handoff_idx",
    )
