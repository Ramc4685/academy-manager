"""Indexes for the ``coach_attendance_audit_log`` collection (#539).

Coach payroll attendance marks (``coach_attendance``) were edited in place
with no audit trail: a coach's status or rate_override_minor could be
silently overwritten with no before/after record. MongoCoachAttendanceAuditLogRepository
now appends one CoachAttendanceAuditEntry per edit that actually changes
status or rate_override_minor (creation and no-op resubmits are not audited).

Queries:

- History for one occurrence/coach pair, most recent first — needs
  (academy_id, occurrence_id, coach_id, at desc).
- Uniqueness / idempotent replay safety — (academy_id, audit_id), mirroring
  migration 0102's coach_rate_audit_id pattern.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0179_coach_attendance_audit_log"


async def up(db: AsyncIOMotorDatabase[Any]) -> None:
    await db.coach_attendance_audit_log.create_index(
        [
            ("academy_id", 1),
            ("occurrence_id", 1),
            ("coach_id", 1),
            ("at", -1),
        ],
        name="coach_attendance_audit_tenant_occurrence_coach_at",
    )
    await db.coach_attendance_audit_log.create_index(
        [("academy_id", 1), ("audit_id", 1)],
        name="coach_attendance_audit_id",
        unique=True,
    )
