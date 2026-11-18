"""Class recap use cases: read, direct entry, after-class report, owner
handoff, and the parent's own-child view.

Every recap write goes through :class:`SaveClassRecap`, the one guarded
writer. Direct entry replaces the recap (the coach edits what they see, under
a revision check). A report only ever ADDS: once the reading passes the
domain's ``resolve_report`` it is merged into the current recap and saved
through ``SaveClassRecap`` with the report id as the mutation id, so a replay
converges and a concurrent edit conflicts instead of being overwritten.

Who may do what on one occurrence:

* the assigned lead coach (scheduled, actual or substitute, not assistant-only)
  and the academy owner may write and submit reports;
* listed assistants and covering admins may read the recap, not write it;
* raw reports are private: the author and the owner see them, nobody else;
* a report reaches the model only when the coach asks for AI on that submit
  and the academy's AI is available, and then only as aliased, redacted text;
  otherwise it is handed to the owner, who finds it on the admin dashboard;
* parents only get :class:`ListChildClassRecaps`: classes their child was
  marked present for, what the class worked on, what their child practised,
  and passes as the pass pipeline records them.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.coaching.application.ports import OccurrenceDetails, OccurrenceLookup
from backend.v2.contexts.coaching.application.use_cases.mark_attendance import (
    ensure_occurrence_started,
)
from backend.v2.contexts.coaching.domain.class_recap import (
    CONFIRMED_PRESENT,
    AliasedSkill,
    ClassRecap,
    RecapSource,
    ReportFacts,
    RosterName,
    alias_report,
    first_name,
    merge_practice,
    resolve_report,
)

# Explicit re-exports: interfaces build commands and views from these without
# importing the domain (tests/structural/test_layering.py).
from backend.v2.contexts.coaching.domain.class_recap import (
    MAX_PARTICIPANTS as MAX_PARTICIPANTS,
)
from backend.v2.contexts.coaching.domain.class_recap import (
    MAX_TAUGHT_SKILLS as MAX_TAUGHT_SKILLS,
)
from backend.v2.contexts.coaching.domain.class_recap import ChildPractice as ChildPractice
from backend.v2.contexts.coaching.domain.class_recap import ClassReport as ClassReport
from backend.v2.contexts.coaching.domain.errors import (
    RecapConflict,
    RecapInvalid,
    RecapNotAllowed,
    RecapWriteForbidden,
    SessionCancelled,
)
from backend.v2.contexts.coaching.domain.models import Attendance
from backend.v2.shared.ids import new_ulid

REPORT_MAX_CHARS = 2000
CHILD_RECAP_LIMIT = 20
HANDOFF_LIMIT = 50


# --- ports -----------------------------------------------------------------


class ClassRecapRepository(Protocol):
    async def get(self, occurrence_id: str) -> ClassRecap | None: ...

    async def save(self, recap: ClassRecap, *, expected_revision: int) -> bool:
        """Insert (``expected_revision == 0``) or replace the recap only while
        it is still at ``expected_revision``. False when it moved on."""
        ...

    async def list_for_occurrences(self, occurrence_ids: list[str]) -> list[ClassRecap]: ...


class ClassReportRepository(Protocol):
    async def get(self, report_id: str) -> ClassReport | None: ...

    async def insert(self, report: ClassReport) -> bool:
        """Insert-only; False when the report id already exists."""
        ...

    async def list_for_occurrence(self, occurrence_id: str) -> list[ClassReport]: ...

    async def list_open_handoffs(self, *, limit: int) -> list[ClassReport]:
        """Unresolved reports handed to the owner, newest first."""
        ...

    async def resolve(self, report_id: str, *, by: str, at: datetime) -> ClassReport | None:
        """Mark an unresolved handoff handled; None when there is none."""
        ...


class OccurrenceAttendanceReader(Protocol):
    async def list_for_occurrence(self, occurrence_id: str) -> list[Attendance]: ...


class StudentAttendanceReader(Protocol):
    async def confirmed_occurrence_ids(self, student_id: str, *, limit: int) -> list[str]:
        """Occurrences this child is currently marked present/late for, newest first."""
        ...


class PassedSkills(Protocol):
    """The authoritative pass pipeline (student_progress), read only."""

    async def passed(self, student_id: str, skill_ids: list[str]) -> set[str]: ...


class SkillOption(BaseModel):
    model_config = {"frozen": True}

    skill_id: str
    name: str
    level_name: str = ""


class RecapSkillCatalog(Protocol):
    """Real curriculum skills of the academy, any level."""

    async def options(self) -> list[SkillOption]:
        """Active skills a class may have worked on (bounded)."""
        ...

    async def names(self, skill_ids: list[str], *, active_only: bool) -> dict[str, str]:
        """Names of the ids that exist (and are active when asked)."""
        ...


class StudentNames(Protocol):
    async def full_names(self, student_ids: list[str]) -> dict[str, str]: ...


class ClassReportInterpreter(Protocol):
    """Reads an aliased, redacted report. ``None`` when no model may or can
    run (disabled, not entitled, capped or failed): the report then goes to
    the owner and the recap is entered by hand."""

    async def interpret(
        self,
        *,
        text: str,
        student_aliases: list[str],
        skills: list[AliasedSkill],
        approver: str,
    ) -> ReportFacts | None: ...


# --- shared ----------------------------------------------------------------


class RecapActor(BaseModel):
    model_config = {"frozen": True}

    user_id: str
    is_owner: bool = False
    is_supervisor: bool = False
    is_assistant_only: bool = False


def _can_edit(occ: OccurrenceDetails, actor: RecapActor) -> bool:
    """Raises :class:`RecapNotAllowed` when the actor may not even read."""
    leads = {occ.scheduled_coach_id, occ.actual_coach_id, occ.substitute_coach_id}
    is_lead = actor.user_id in leads and not actor.is_assistant_only
    listed = actor.user_id in leads or actor.user_id in occ.assistant_coach_ids
    if not (actor.is_owner or actor.is_supervisor or listed):
        raise RecapNotAllowed("class not found", occurrence_id=occ.occurrence_id)
    return actor.is_owner or is_lead


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _writable_occurrence(
    occurrences: OccurrenceLookup,
    occurrence_id: str,
    class_starts_at: datetime,
    actor: RecapActor,
    now: datetime,
) -> OccurrenceDetails:
    occ = await occurrences.get(occurrence_id)
    if occ is None:
        raise RecapNotAllowed("class not found", occurrence_id=occurrence_id)
    if not _can_edit(occ, actor):
        raise RecapWriteForbidden(
            "only the class's coach or the owner can record what was taught",
            occurrence_id=occurrence_id,
        )
    if occ.status == "cancelled":
        raise SessionCancelled("this class was cancelled", occurrence_id=occurrence_id)
    # The caller names the dated class it means: a rescheduled or mismatched
    # occurrence is refused instead of recorded against the wrong day.
    if _utc(class_starts_at) != _utc(occ.starts_at):
        raise RecapConflict(
            "this class's date or time changed; reload it and try again",
            occurrence_id=occurrence_id,
        )
    ensure_occurrence_started(occ.starts_at, now, occurrence_id=occurrence_id)
    return occ


def _attendance_map(rows: list[Attendance]) -> dict[str, str]:
    return {row.student_id: row.status for row in rows}


# --- save (the one guarded writer) -----------------------------------------


class SaveClassRecapCommand(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    class_starts_at: datetime
    mutation_id: str = Field(min_length=1, max_length=64)
    expected_revision: int = Field(ge=0)
    taught_skill_ids: list[str] = Field(default_factory=list, max_length=MAX_TAUGHT_SKILLS)
    practice: list[ChildPractice] = Field(default_factory=list, max_length=MAX_PARTICIPANTS)
    source: RecapSource = "direct"
    source_report_id: str | None = None


class SaveClassRecap:
    def __init__(
        self,
        *,
        recaps: ClassRecapRepository,
        occurrences: OccurrenceLookup,
        attendance: OccurrenceAttendanceReader,
        skills: RecapSkillCatalog,
        academy_id: Callable[[], str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._recaps = recaps
        self._occurrences = occurrences
        self._attendance = attendance
        self._skills = skills
        self._academy_id = academy_id
        self._now = clock

    async def execute(self, cmd: SaveClassRecapCommand, actor: RecapActor) -> ClassRecap:
        now = self._now()
        occ = await _writable_occurrence(
            self._occurrences, cmd.occurrence_id, cmd.class_starts_at, actor, now
        )
        current = await self._recaps.get(cmd.occurrence_id)
        if current is not None and current.last_mutation_id == cmd.mutation_id:
            return current  # replay of the write that produced this revision
        revision = current.revision if current is not None else 0
        if cmd.expected_revision != revision:
            raise RecapConflict(
                "this recap changed since you opened it; reload and try again",
                occurrence_id=cmd.occurrence_id,
                revision=revision,
            )

        taught = list(dict.fromkeys(cmd.taught_skill_ids))
        # Skills this recap already records were checked when added; one since
        # archived stays on edit. Only newly added skills must be active now.
        recorded = set(current.taught_skill_ids) if current is not None else set()
        fresh = [sid for sid in taught if sid not in recorded]
        known = await self._skills.names(fresh, active_only=True)
        unknown = [sid for sid in fresh if sid not in known]
        if unknown:
            raise RecapInvalid("unknown curriculum skill", skill_ids=unknown)
        practice = merge_practice((), tuple(cmd.practice))
        untaught = sorted({s for row in practice for s in row.skill_ids} - set(taught))
        if untaught:
            raise RecapInvalid("practised skills must be taught in this class", skill_ids=untaught)
        marks = _attendance_map(await self._attendance.list_for_occurrence(cmd.occurrence_id))
        not_present = [
            row.student_id for row in practice if marks.get(row.student_id) not in CONFIRMED_PRESENT
        ]
        if not_present:
            raise RecapInvalid(
                "only students marked present can be credited with practice",
                student_ids=not_present,
            )

        recap = ClassRecap(
            recap_id=current.recap_id if current is not None else str(new_ulid()),
            academy_id=self._academy_id(),
            occurrence_id=occ.occurrence_id,
            session_id=occ.session_id,
            class_starts_at=occ.starts_at,
            taught_skill_ids=tuple(taught),
            practice=practice,
            revision=revision + 1,
            last_mutation_id=cmd.mutation_id,
            source=cmd.source,
            source_report_id=cmd.source_report_id,
            updated_by=actor.user_id,
            updated_at=now,
        )
        if not await self._recaps.save(recap, expected_revision=revision):
            raise RecapConflict(
                "this recap changed since you opened it; reload and try again",
                occurrence_id=cmd.occurrence_id,
            )
        return recap


# --- read ------------------------------------------------------------------


class RecapRosterEntry(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    name: str
    attendance: str


class ClassRecapState(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    class_starts_at: datetime
    can_edit: bool
    recap: ClassRecap | None
    roster: list[RecapRosterEntry]
    skill_options: list[SkillOption]
    #: Taught skills that left the curriculum still need a name to render.
    skill_names: dict[str, str]
    reports: list[ClassReport]


class GetClassRecap:
    def __init__(
        self,
        *,
        recaps: ClassRecapRepository,
        reports: ClassReportRepository,
        occurrences: OccurrenceLookup,
        attendance: OccurrenceAttendanceReader,
        skills: RecapSkillCatalog,
        names: StudentNames,
    ) -> None:
        self._recaps = recaps
        self._reports = reports
        self._occurrences = occurrences
        self._attendance = attendance
        self._skills = skills
        self._names = names

    async def execute(self, occurrence_id: str, actor: RecapActor) -> ClassRecapState:
        occ = await self._occurrences.get(occurrence_id)
        if occ is None:
            raise RecapNotAllowed("class not found", occurrence_id=occurrence_id)
        can_edit = _can_edit(occ, actor)
        recap = await self._recaps.get(occurrence_id)
        marks = _attendance_map(await self._attendance.list_for_occurrence(occurrence_id))
        names = await self._names.full_names(list(marks))
        roster = [
            RecapRosterEntry(student_id=sid, name=names.get(sid, "Student"), attendance=mark)
            for sid, mark in marks.items()
            if mark != "voided"
        ]
        taught = list(recap.taught_skill_ids) if recap is not None else []
        reports = await self._reports.list_for_occurrence(occurrence_id)
        if not actor.is_owner:
            reports = [r for r in reports if r.author_id == actor.user_id]
        return ClassRecapState(
            occurrence_id=occurrence_id,
            class_starts_at=occ.starts_at,
            can_edit=can_edit,
            recap=recap,
            roster=sorted(roster, key=lambda r: r.name.lower()),
            skill_options=await self._skills.options() if can_edit else [],
            skill_names=await self._skills.names(taught, active_only=False),
            reports=reports,
        )


# --- after-class report ----------------------------------------------------


class SubmitClassReportCommand(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    class_starts_at: datetime
    report_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=REPORT_MAX_CHARS)
    #: The coach's per-submit permission to send the (aliased) report to AI.
    use_ai: bool = False


class SubmitClassReport:
    def __init__(
        self,
        *,
        reports: ClassReportRepository,
        recaps: ClassRecapRepository,
        occurrences: OccurrenceLookup,
        attendance: OccurrenceAttendanceReader,
        skills: RecapSkillCatalog,
        names: StudentNames,
        interpreter: ClassReportInterpreter,
        save: SaveClassRecap,
        academy_id: Callable[[], str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._reports = reports
        self._recaps = recaps
        self._occurrences = occurrences
        self._attendance = attendance
        self._skills = skills
        self._names = names
        self._interpreter = interpreter
        self._save = save
        self._academy_id = academy_id
        self._now = clock

    async def execute(self, cmd: SubmitClassReportCommand, actor: RecapActor) -> ClassReport:
        now = self._now()
        occ = await _writable_occurrence(
            self._occurrences, cmd.occurrence_id, cmd.class_starts_at, actor, now
        )
        existing = await self._reports.get(cmd.report_id)
        if existing is not None:
            return self._replay(existing, cmd, actor)

        report = ClassReport(
            report_id=cmd.report_id,
            academy_id=self._academy_id(),
            occurrence_id=cmd.occurrence_id,
            class_starts_at=occ.starts_at,
            author_id=actor.user_id,
            text=cmd.text,
            submitted_at=now,
            outcome="sent_to_owner",
        )
        if cmd.use_ai:
            report = await self._read_and_apply(report, cmd, actor)
        if not await self._reports.insert(report):
            # A concurrent submit of the same id won; its apply used the same
            # mutation id, so the recap converged either way.
            stored = await self._reports.get(cmd.report_id)
            if stored is not None:
                return self._replay(stored, cmd, actor)
        return report

    async def _read_and_apply(
        self, report: ClassReport, cmd: SubmitClassReportCommand, actor: RecapActor
    ) -> ClassReport:
        current = await self._recaps.get(cmd.occurrence_id)
        marks = _attendance_map(await self._attendance.list_for_occurrence(cmd.occurrence_id))
        marks = {sid: mark for sid, mark in marks.items() if mark != "voided"}
        full = await self._names.full_names(list(marks))
        roster = [RosterName(student_id=sid, full_name=full.get(sid, "")) for sid in marks]
        options = await self._skills.options()
        aliased = alias_report(cmd.text, roster, [(o.skill_id, o.name) for o in options])
        firsts = {sid: first_name(name) for sid, name in full.items()}
        if aliased.questions:
            # Settled locally: the report never leaves the app.
            return report.model_copy(
                update={"outcome": "needs_clarification", "questions": aliased.questions}
            )
        facts = await self._interpreter.interpret(
            text=aliased.text,
            student_aliases=list(aliased.student_aliases),
            skills=list(aliased.skills),
            approver=actor.user_id,
        )
        if facts is None:
            return report
        resolved = resolve_report(
            facts, aliased=aliased, attendance=marks, first_names=firsts, existing=current
        )
        update: dict[str, object] = {"ai_used": True, "pass_claims": resolved.pass_claims}
        if resolved.questions:
            return report.model_copy(
                update={**update, "outcome": "needs_clarification", "questions": resolved.questions}
            )
        base_taught = current.taught_skill_ids if current is not None else ()
        taught = tuple(dict.fromkeys((*base_taught, *resolved.taught_skill_ids)))
        practice = merge_practice(
            current.practice if current is not None else (), resolved.practice
        )
        if current is not None and (taught, practice) == (
            current.taught_skill_ids,
            current.practice,
        ):
            # Nothing new: the recap already says all of this.
            return report.model_copy(
                update={**update, "outcome": "applied", "applied_revision": current.revision}
            )
        try:
            saved = await self._save.execute(
                SaveClassRecapCommand(
                    occurrence_id=cmd.occurrence_id,
                    class_starts_at=cmd.class_starts_at,
                    mutation_id=report.report_id,
                    expected_revision=current.revision if current is not None else 0,
                    taught_skill_ids=list(taught),
                    practice=list(practice),
                    source="report",
                    source_report_id=report.report_id,
                ),
                actor,
            )
        except (RecapConflict, RecapInvalid) as exc:
            return report.model_copy(
                update={**update, "outcome": "needs_clarification", "questions": (exc.message,)}
            )
        return report.model_copy(
            update={**update, "outcome": "applied", "applied_revision": saved.revision}
        )

    @staticmethod
    def _replay(
        existing: ClassReport, cmd: SubmitClassReportCommand, actor: RecapActor
    ) -> ClassReport:
        if (
            existing.author_id != actor.user_id
            or existing.occurrence_id != cmd.occurrence_id
            or existing.text != cmd.text
        ):
            raise RecapConflict("this report id was already used", report_id=cmd.report_id)
        return existing


# --- owner handoff ---------------------------------------------------------


class ListOpenClassReportHandoffs:
    """Owner-only: reports waiting for the owner (no AI, or AI unavailable)."""

    def __init__(self, *, reports: ClassReportRepository) -> None:
        self._reports = reports

    async def execute(self) -> list[ClassReport]:
        return await self._reports.list_open_handoffs(limit=HANDOFF_LIMIT)


class ResolveClassReport:
    def __init__(
        self,
        *,
        reports: ClassReportRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._reports = reports
        self._now = clock

    async def execute(self, occurrence_id: str, report_id: str, actor: RecapActor) -> ClassReport:
        if not actor.is_owner:
            raise RecapWriteForbidden("only the owner closes a handed-off report")
        report = await self._reports.get(report_id)
        if report is None or report.occurrence_id != occurrence_id:
            raise RecapNotAllowed("report not found", report_id=report_id)
        if report.resolved_at is not None:
            return report
        resolved = await self._reports.resolve(report_id, by=actor.user_id, at=self._now())
        return resolved or report


# --- parent: own child -----------------------------------------------------


class ChildClassRecap(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    class_starts_at: datetime
    taught_skills: list[str]
    practiced_skills: list[str]
    passed_skills: list[str]


class ListChildClassRecaps:
    """Recent classes this child is marked present for that have a recap.
    The route guards child ownership. Practice is the child's own row only;
    passes come from the pass pipeline, never from a report. No report text,
    no other children."""

    def __init__(
        self,
        *,
        recaps: ClassRecapRepository,
        attendance: StudentAttendanceReader,
        skills: RecapSkillCatalog,
        passes: PassedSkills,
    ) -> None:
        self._recaps = recaps
        self._attendance = attendance
        self._skills = skills
        self._passes = passes

    async def execute(self, student_id: str) -> list[ChildClassRecap]:
        attended = await self._attendance.confirmed_occurrence_ids(
            student_id, limit=CHILD_RECAP_LIMIT * 2
        )
        recaps = await self._recaps.list_for_occurrences(attended)
        recaps.sort(key=lambda r: _utc(r.class_starts_at), reverse=True)
        rows: list[ChildClassRecap] = []
        for recap in recaps[:CHILD_RECAP_LIMIT]:
            practiced = recap.practiced_by(student_id)
            ids = list(dict.fromkeys((*recap.taught_skill_ids, *practiced)))
            names = await self._skills.names(ids, active_only=False)
            passed = await self._passes.passed(student_id, ids)
            rows.append(
                ChildClassRecap(
                    occurrence_id=recap.occurrence_id,
                    class_starts_at=recap.class_starts_at,
                    taught_skills=[names[s] for s in recap.taught_skill_ids if s in names],
                    practiced_skills=[names[s] for s in practiced if s in names],
                    passed_skills=[names[s] for s in ids if s in names and s in passed],
                )
            )
        return rows
