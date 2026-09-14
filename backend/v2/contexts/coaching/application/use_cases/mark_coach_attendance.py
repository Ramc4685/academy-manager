"""Mark coach payroll attendance for one occurrence.

This row *is* a payroll input: ``status`` decides whether the date is paid
at all and ``rate_override_minor`` decides how much. Once Finance has
approved or paid the payout period covering the date, the snapshot no
longer re-reads these rows, so a late edit is silent drift rather than a
correction — issue #787. The ``PayoutPeriodLock`` port answers "is that
window frozen?" without Coaching importing Finance, and a frozen window
refuses the write (``PayoutPeriodFrozen``, 409) instead of accepting an
edit nobody will ever see.

The freeze is a guardrail, not a dead end: an academy owner who states a
reason can still push a correction through (issue #821). That override is
always audited — reason included — because it moves money inside a period
Finance has already signed off on.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.coaching.application.ports import (
    CoachAttendanceAuditRepository,
    CoachAttendanceRepository,
    OccurrenceLookup,
    PayoutPeriodLock,
)
from backend.v2.contexts.coaching.domain.errors import PayoutPeriodFrozen
from backend.v2.contexts.coaching.domain.models import (
    CoachAttendance,
    CoachAttendanceAuditEntry,
    CoachAttendanceRole,
    CoachAttendanceSource,
    CoachAttendanceStatus,
)
from backend.v2.shared.ids import new_ulid


class MarkCoachAttendanceCommand(BaseModel):
    occurrence_id: str
    coach_id: str
    status: CoachAttendanceStatus
    role: CoachAttendanceRole = "lead"
    source: CoachAttendanceSource
    rate_override_minor: int | None = Field(default=None, ge=0)
    note: str = ""
    override_reason: str | None = None
    """Owner-only justification for editing inside a frozen payout period (#821)."""


class MarkCoachAttendance:
    def __init__(
        self,
        *,
        coach_attendance: CoachAttendanceRepository,
        occurrence_lookup: OccurrenceLookup,
        academy_id: str,
        payout_lock: PayoutPeriodLock | None = None,
        clock: Callable[[], datetime] | None = None,
        coach_attendance_audit: CoachAttendanceAuditRepository | None = None,
    ) -> None:
        self._coach_attendance = coach_attendance
        self._occurrence_lookup = occurrence_lookup
        self._academy_id = academy_id
        self._payout_lock = payout_lock
        self._clock = clock or (lambda: datetime.now(UTC))
        self._coach_attendance_audit = coach_attendance_audit

    async def execute(
        self,
        command: MarkCoachAttendanceCommand,
        *,
        actor_id: str,
        actor_is_owner: bool = False,
    ) -> CoachAttendance:
        occurrence = await self._occurrence_lookup.get(command.occurrence_id)
        if occurrence is None:
            raise ValueError("Occurrence not found")

        if command.source == "coach_self":
            assigned = {
                occurrence.scheduled_coach_id,
                occurrence.actual_coach_id,
                occurrence.substitute_coach_id,
            }
            if command.coach_id != actor_id or command.coach_id not in assigned:
                raise PermissionError("Coach is not assigned to this occurrence")

        overridden_status = await self._resolve_payout_window(
            coach_id=command.coach_id,
            at=occurrence.starts_at,
            actor_is_owner=actor_is_owner,
            override_reason=command.override_reason,
        )

        existing = await self._coach_attendance.find_for_occurrence_coach(
            command.occurrence_id,
            command.coach_id,
        )
        row = CoachAttendance(
            attendance_id=existing.attendance_id if existing else new_ulid(),
            academy_id=self._academy_id,
            occurrence_id=command.occurrence_id,
            coach_id=command.coach_id,
            status=command.status,
            role=command.role,
            source=command.source,
            marked_by=actor_id,
            marked_at=self._clock(),
            rate_override_minor=command.rate_override_minor,
            note=command.note,
        )
        saved = await self._coach_attendance.upsert(row)

        changed = existing is not None and (
            existing.status != row.status or existing.rate_override_minor != row.rate_override_minor
        )
        # An owner override is audited unconditionally: it writes into a period
        # Finance already approved, so even a first mark or a no-op resubmit
        # must leave a trace with the stated reason (#821).
        if (changed or overridden_status is not None) and self._coach_attendance_audit is not None:
            await self._coach_attendance_audit.append(
                CoachAttendanceAuditEntry(
                    audit_id=new_ulid(),
                    academy_id=self._academy_id,
                    occurrence_id=command.occurrence_id,
                    coach_id=command.coach_id,
                    actor_id=actor_id,
                    at=self._clock(),
                    before_status=existing.status if existing else None,
                    after_status=row.status,
                    before_rate_override_minor=existing.rate_override_minor if existing else None,
                    after_rate_override_minor=row.rate_override_minor,
                    override_reason=(command.override_reason or "").strip() or None
                    if overridden_status is not None
                    else None,
                )
            )

        return saved

    async def _resolve_payout_window(
        self,
        *,
        coach_id: str,
        at: datetime,
        actor_is_owner: bool,
        override_reason: str | None,
    ) -> str | None:
        """Return the frozen period status when an owner override lets the write
        proceed anyway, ``None`` when the window is simply open — and raise
        ``PayoutPeriodFrozen`` otherwise.

        Owner *and* reason are both required: owner alone would make the freeze
        meaningless for the person most likely to bypass it, and a reason from a
        non-owner is not authority to move money Finance has signed off on.
        """
        if self._payout_lock is None:
            return None
        status = await self._payout_lock.locked_status_for(coach_id=coach_id, at=at)
        if status is None:
            return None
        if actor_is_owner and (override_reason or "").strip():
            return status
        raise PayoutPeriodFrozen(
            "cannot change coach attendance after payout is approved or paid",
            coach_id=coach_id,
            occurrence_at=at.isoformat(),
            payout_status=status,
        )
