"""Copy class (A0-8): a new class from an existing one, optionally with its roster.

Composes the normal write paths instead of re-implementing them: the class is
created by ``CreateSession`` (timezone resolution, duplicate-series refusal)
and each copied student is added by ``EditRosterAdd`` (seat check, lifecycle
event, welcome and roster notices). Money policy (who may copy a price) is the
caller's decision, passed as ``include_price``.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentQuery,
    SessionWriter,
    StudentQuery,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    COMMUNICATION_PACK_FIELDS,
    CreateSession,
    CreateSessionCommand,
    EditRosterAdd,
    EditRosterAddCommand,
)
from backend.v2.contexts.enrollment.domain.errors import (
    CopyRosterRefused,
    DuplicateSessionSeries,
    SessionNotFound,
)
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.shared.http.errors import DomainError

log = logging.getLogger(__name__)

__all__ = ["CopyRosterRefused", "CopySession", "CopySessionCommand"]


class CopySessionCommand(BaseModel):
    model_config = {"frozen": True}
    source_session_id: str
    title: str
    # None = keep the source's value. A copy with the same title and schedule
    # is refused as a duplicate series, exactly like Create.
    days_of_week: list[str] | None = None
    start_time: str | None = None
    end_time: str | None = None
    include_price: bool = False
    copy_roster: bool = False
    actor_id: str | None = None


class CopiedRosterRow(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    full_name: str
    ok: bool
    error_code: str | None = None
    message: str | None = None


class CopySessionResult(BaseModel):
    model_config = {"frozen": True}
    session: Session
    roster: list[CopiedRosterRow]


class CopySession:
    def __init__(
        self,
        *,
        sessions: SessionWriter,
        create_session: CreateSession,
        enrollments: EnrollmentQuery,
        students: StudentQuery,
        roster_add: EditRosterAdd,
    ) -> None:
        self._sessions = sessions
        self._create_session = create_session
        self._enrollments = enrollments
        self._students = students
        self._roster_add = roster_add

    async def execute(self, cmd: CopySessionCommand) -> CopySessionResult:
        source = await self._sessions.get(cmd.source_session_id)
        if source is None:
            raise SessionNotFound("class not found", session_id=cmd.source_session_id)
        days = cmd.days_of_week if cmd.days_of_week is not None else source.days_of_week
        start_time = cmd.start_time or source.start_time
        end_time = cmd.end_time or source.end_time
        if cmd.copy_roster:
            if not source.days_of_week:
                raise CopyRosterRefused(
                    "A one-off class's students can't be copied. Copy the class on its own."
                )
            if (sorted(days or []), start_time, end_time) == (
                sorted(source.days_of_week),
                source.start_time,
                source.end_time,
            ):
                raise CopyRosterRefused(
                    "Change the days or times to copy the students: the copy meets when "
                    "this class does, so they'd be enrolled and billed twice."
                )
        try:
            session = await self._create_session.execute(self._create_command(source, cmd))
        except DuplicateSessionSeries as exc:
            # Usually a retry whose first attempt already made the copy (the
            # response was lost). Say so and hand back the class that exists.
            raise DuplicateSessionSeries(
                "A class with this coach, location and schedule already exists, so no copy "
                "was made. If you just copied this class, the copy is already there.",
                **exc.details,
            ) from exc
        roster = await self._copy_roster(source, session, cmd) if cmd.copy_roster else []
        return CopySessionResult(session=session, roster=roster)

    @staticmethod
    def _create_command(source: Session, cmd: CopySessionCommand) -> CreateSessionCommand:
        days = cmd.days_of_week if cmd.days_of_week is not None else source.days_of_week
        return CreateSessionCommand(
            coach_id=source.coach_id,
            title=cmd.title,
            location=source.location,
            # Recurring classes re-derive their instants from the schedule;
            # a one-off class keeps the source's instants.
            start_at=None if source.days_of_week else source.start_at,
            end_at=None if source.days_of_week else source.end_at,
            capacity=source.capacity,
            amount_cents=source.amount_cents if cmd.include_price else None,
            days_of_week=days,
            start_time=cmd.start_time or source.start_time,
            end_time=cmd.end_time or source.end_time,
            timezone=source.timezone,
            assistant_coach_ids=list(source.assistant_coach_ids),
            **{f: getattr(source, f) for f in COMMUNICATION_PACK_FIELDS},
        )

    async def _copy_roster(
        self, source: Session, session: Session, cmd: CopySessionCommand
    ) -> list[CopiedRosterRow]:
        # Active students only: a held or paused student is away from class,
        # and enrolling them active in the copy would bill them for it.
        rows = await self._enrollments.active_for_session(source.session_id)
        students = {
            s.student_id: s for s in await self._students.by_ids([r.student_id for r in rows])
        }
        results: list[CopiedRosterRow] = []
        for row in rows:
            student = students.get(row.student_id)
            if student is None:
                results.append(
                    CopiedRosterRow(
                        student_id=row.student_id,
                        full_name="(unknown student)",
                        ok=False,
                        error_code="Enrollment.StudentNotFound",
                        message="Student record not found.",
                    )
                )
                continue
            try:
                await self._roster_add.execute(
                    EditRosterAddCommand(
                        session_id=session.session_id,
                        student_id=student.student_id,
                        parent_id=student.parent_id,
                        full_name=student.full_name,
                        actor_id=cmd.actor_id,
                        reason=f"copied from {source.title}",
                    )
                )
            except DomainError as exc:
                results.append(
                    CopiedRosterRow(
                        student_id=student.student_id,
                        full_name=student.full_name,
                        ok=False,
                        error_code=exc.code,
                        message=exc.message,
                    )
                )
                continue
            except Exception:
                # The class and earlier students already exist; report this one.
                log.exception(
                    "copy_session_roster_row_failed session_id=%s student_id=%s",
                    session.session_id,
                    student.student_id,
                )
                results.append(
                    CopiedRosterRow(
                        student_id=student.student_id,
                        full_name=student.full_name,
                        ok=False,
                        error_code="Enrollment.RosterAddFailed",
                        message="Could not add this student. Add them from the roster.",
                    )
                )
                continue
            results.append(
                CopiedRosterRow(student_id=student.student_id, full_name=student.full_name, ok=True)
            )
        return results
