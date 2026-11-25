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

from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

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
from backend.v2.contexts.coaching.domain.class_recap import MAX_PASSES as MAX_PASSES
from backend.v2.contexts.coaching.domain.class_recap import (
    MAX_TAUGHT_SKILLS as MAX_TAUGHT_SKILLS,
)
from backend.v2.contexts.coaching.domain.class_recap import ChildPass as ChildPass
from backend.v2.contexts.coaching.domain.class_recap import ChildPractice as ChildPractice
from backend.v2.contexts.coaching.domain.class_recap import ClassReport as ClassReport
from backend.v2.contexts.coaching.domain.class_recap import PassClaim as PassClaim
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
#: How long a submit owns the reading of its report; after that a replay
#: settles it (applied or the owner's) without another model call.
REPORT_PROCESSING_LEASE = timedelta(minutes=5)
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

    async def finish(self, report: ClassReport) -> bool:
        """Store the reading's outcome and clear ``processing_until``, only
        while it is still set (the read is finished once). False otherwise."""
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

    async def passed(self, student_id: str, skill_ids: list[str]) -> set[str]:
        """Ids among ``skill_ids`` this child genuinely passed (silent
        placement credits excluded, like every parent-facing pass read)."""
        ...


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


class OccurrenceRosterNames(Protocol):
    async def full_names(self, *, session_id: str, occurrence_id: str) -> dict[str, str]:
        """Everyone on this dated class's roster (enrolled, make-up, trial,
        and anyone already marked, voided included): student id -> full name."""
        ...


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


# --- passes: the pass pipeline, per class ----------------------------------


class DemonstrationOutcome(BaseModel):
    """One child's result, as the pass pipeline decided it."""

    model_config = {"frozen": True}

    student_id: str
    #: mastered, already_mastered, try_recorded, needs_lead, not_on_level, not_placed
    outcome: str
    off_level: bool = False
    level_up_queued: bool = False
    tries: int = 0


#: recorded: every effect landed and the skill is passed; counted: it landed
#: as a try short of N (or the pass was since taken back); in_progress: an
#: earlier save stopped part way (saving again finishes it); earned_before:
#: already passed elsewhere; not_recorded: the pipeline refused it (not
#: placed, retired skill) or it has not run yet.
PassReceipt = Literal["recorded", "counted", "in_progress", "earned_before", "not_recorded"]


class ClassDemonstrationWriter(Protocol):
    """The pass pipeline (student_progress), written for one dated class. It
    resolves the program and level from the skill and applies the skill's
    pass rule once per class, child and skill: a retry, a second writer or a
    resumed save converges on one contribution. A skill of another level
    counts there and never moves the child's active level."""

    async def record(
        self,
        *,
        skill_id: str,
        student_ids: list[str],
        coach_id: str,
        can_sign_off: bool,
        session_id: str,
        occurrence_id: str,
        observed_at: datetime,
    ) -> list[DemonstrationOutcome]: ...

    async def receipts(
        self, occurrence_id: str, passes: list[tuple[str, str]]
    ) -> dict[tuple[str, str], PassReceipt]:
        """State of each ``(student_id, skill_id)`` pass of this class."""
        ...


# --- save (the one guarded writer) -----------------------------------------


class SaveClassRecapCommand(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    class_starts_at: datetime
    mutation_id: str = Field(min_length=1, max_length=64)
    expected_revision: int = Field(ge=0)
    taught_skill_ids: list[str] = Field(default_factory=list, max_length=MAX_TAUGHT_SKILLS)
    practice: list[ChildPractice] = Field(default_factory=list, max_length=MAX_PARTICIPANTS)
    #: The class's passes, all of them; None keeps the current ones (a report).
    passes: list[PassClaim] | None = Field(default=None, max_length=MAX_PASSES)
    source: RecapSource = "direct"
    source_report_id: str | None = None


class SaveClassRecap:
    """Saves the recap, then applies its passes. The passes ride in the
    recap write (durable intent) and each is applied idempotently, so a save
    that stops part way is finished by saving again, and the receipt on
    :class:`GetClassRecap` shows what landed."""

    def __init__(
        self,
        *,
        recaps: ClassRecapRepository,
        occurrences: OccurrenceLookup,
        attendance: OccurrenceAttendanceReader,
        skills: RecapSkillCatalog,
        academy_id: Callable[[], str],
        writer: ClassDemonstrationWriter | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._recaps = recaps
        self._occurrences = occurrences
        self._attendance = attendance
        self._skills = skills
        self._academy_id = academy_id
        self._writer = writer
        self._now = clock

    async def execute(self, cmd: SaveClassRecapCommand, actor: RecapActor) -> ClassRecap:
        now = self._now()
        occ = await _writable_occurrence(
            self._occurrences, cmd.occurrence_id, cmd.class_starts_at, actor, now
        )
        current = await self._recaps.get(cmd.occurrence_id)
        if current is not None and current.last_mutation_id == cmd.mutation_id:
            # Replay of the write that produced this revision: finish its passes.
            await self._apply_passes(occ, current, actor)
            return current
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
        # Practice recorded before an attendance correction rides along
        # unchanged (the coach can no longer see that child to remove it);
        # only new credit needs a present mark now.
        had = {row.student_id: set(row.skill_ids) for row in current.practice} if current else {}
        not_present = [
            row.student_id
            for row in practice
            if marks.get(row.student_id) not in CONFIRMED_PRESENT
            and not set(row.skill_ids) <= had.get(row.student_id, set())
        ]
        if not_present:
            raise RecapInvalid(
                "only students marked present can be credited with practice",
                student_ids=not_present,
            )
        # A pass the pipeline never counted may be taken off (a mis-tap).
        uncounted: set[tuple[str, str]] = set()
        if self._writer is not None and current is not None and current.passes:
            pairs = [(p.student_id, p.skill_id) for p in current.passes]
            receipts = await self._writer.receipts(occ.occurrence_id, pairs)
            uncounted = {pair for pair, r in receipts.items() if r == "not_recorded"}
        passes = self._passes(cmd, current, taught, marks, revision + 1, uncounted)

        recap = ClassRecap(
            recap_id=current.recap_id if current is not None else str(new_ulid()),
            academy_id=self._academy_id(),
            occurrence_id=occ.occurrence_id,
            session_id=occ.session_id,
            class_starts_at=occ.starts_at,
            taught_skill_ids=tuple(taught),
            practice=practice,
            passes=passes,
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
        await self._apply_passes(occ, recap, actor)
        return recap

    def _passes(
        self,
        cmd: SaveClassRecapCommand,
        current: ClassRecap | None,
        taught: list[str],
        marks: dict[str, str],
        revision: int,
        uncounted: set[tuple[str, str]],
    ) -> tuple[ChildPass, ...]:
        kept = current.passes if current is not None else ()
        if cmd.passes is None:
            return kept
        if (kept or cmd.passes) and self._writer is None:
            raise RecapInvalid("passes cannot be recorded here")
        wanted = list(dict.fromkeys((p.student_id, p.skill_id) for p in cmd.passes))
        kept = tuple(
            p
            for p in kept
            if (p.student_id, p.skill_id) in wanted or (p.student_id, p.skill_id) not in uncounted
        )
        had = {(p.student_id, p.skill_id) for p in kept}
        dropped = sorted(had - set(wanted))
        if dropped:
            # A recorded pass stands: taking it back is a formal reassessment.
            raise RecapInvalid(
                "a recorded pass can only be taken back by a formal reassessment",
                student_ids=sorted({sid for sid, _ in dropped}),
            )
        new = [pair for pair in wanted if pair not in had]
        untaught = sorted({skill for _, skill in new} - set(taught))
        if untaught:
            raise RecapInvalid("passed skills must be taught in this class", skill_ids=untaught)
        absent = sorted({sid for sid, _ in new if marks.get(sid) not in CONFIRMED_PRESENT})
        if absent:
            raise RecapInvalid(
                "only students marked present can be credited with a pass", student_ids=absent
            )
        return kept + tuple(
            ChildPass(student_id=sid, skill_id=skill, added_revision=revision) for sid, skill in new
        )

    async def _apply_passes(
        self, occ: OccurrenceDetails, recap: ClassRecap, actor: RecapActor
    ) -> None:
        if self._writer is None or not recap.passes:
            return
        pairs = [(row.student_id, row.skill_id) for row in recap.passes]
        receipts = await self._writer.receipts(occ.occurrence_id, pairs)
        by_skill: dict[str, list[str]] = {}
        for row in recap.passes:
            receipt = receipts.get((row.student_id, row.skill_id))
            # Landed passes are left alone, so a later edit never re-runs
            # their side effects (a level-up the owner since rejected). An
            # uncounted pass runs only in the save that added it: an old one
            # (earned before, then reassessed) must not come back on an edit.
            if receipt == "in_progress" or (
                receipt == "not_recorded" and row.added_revision == recap.revision
            ):
                by_skill.setdefault(row.skill_id, []).append(row.student_id)
        # Each is applied once per class, child and skill: a resumed one
        # picks up where it stopped.
        for skill_id, student_ids in by_skill.items():
            await self._writer.record(
                skill_id=skill_id,
                student_ids=student_ids,
                coach_id=actor.user_id,
                can_sign_off=not actor.is_assistant_only,
                session_id=occ.session_id,
                occurrence_id=occ.occurrence_id,
                observed_at=occ.starts_at,
            )


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
    #: ``(student_id, skill_id) -> receipt`` for each of the recap's passes.
    pass_receipts: dict[tuple[str, str], PassReceipt] = Field(default_factory=dict)


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
        writer: ClassDemonstrationWriter | None = None,
    ) -> None:
        self._recaps = recaps
        self._reports = reports
        self._occurrences = occurrences
        self._attendance = attendance
        self._skills = skills
        self._names = names
        self._writer = writer

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
            pass_receipts=(
                await self._writer.receipts(
                    occurrence_id, [(p.student_id, p.skill_id) for p in recap.passes]
                )
                if self._writer is not None and recap is not None and recap.passes
                else {}
            ),
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
        roster: OccurrenceRosterNames,
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
        self._roster = roster
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
            return await self._replay(existing, cmd, actor, now)

        # Stored before any model call: the unique report id makes this submit
        # the only one that reads it, and until it finishes the report is
        # already the owner's (``sent_to_owner``), so a crash or an error
        # mid-read never loses the coach's words.
        report = ClassReport(
            report_id=cmd.report_id,
            academy_id=self._academy_id(),
            occurrence_id=cmd.occurrence_id,
            class_starts_at=occ.starts_at,
            author_id=actor.user_id,
            text=cmd.text,
            submitted_at=now,
            outcome="sent_to_owner",
            processing_until=now + REPORT_PROCESSING_LEASE if cmd.use_ai else None,
        )
        if not await self._reports.insert(report):
            stored = await self._reports.get(cmd.report_id)
            if stored is None:
                raise RecapConflict("this report id was already used", report_id=cmd.report_id)
            return await self._replay(stored, cmd, actor, now)
        if not cmd.use_ai:
            return report
        try:
            # Enrollments live on the recurring template, as on the register.
            roster_session_id = occ.template_session_id or occ.session_id
            done = await self._read_and_apply(report, roster_session_id, cmd, actor)
        except Exception:
            # Best effort: settle it now instead of waiting out the lease.
            with suppress(Exception):
                await self._recover(report)
            raise
        return await self._finish(done.model_copy(update={"processing_until": None}))

    async def _finish(self, done: ClassReport) -> ClassReport:
        if await self._reports.finish(done):
            return done
        # Someone else settled it first (a recovery): theirs is the record.
        return await self._reports.get(done.report_id) or done

    async def _recover(self, report: ClassReport) -> ClassReport:
        """Settle a read that never finished, without calling the model again:
        applied when the recap's last write is this report, else the owner's."""
        current = await self._recaps.get(report.occurrence_id)
        update: dict[str, object] = {"processing_until": None}
        if current is not None and current.source_report_id == report.report_id:
            update |= {"outcome": "applied", "ai_used": True, "applied_revision": current.revision}
        return await self._finish(report.model_copy(update=update))

    async def _read_and_apply(
        self,
        report: ClassReport,
        session_id: str,
        cmd: SubmitClassReportCommand,
        actor: RecapActor,
    ) -> ClassReport:
        current = await self._recaps.get(cmd.occurrence_id)
        marks = _attendance_map(await self._attendance.list_for_occurrence(cmd.occurrence_id))
        # Alias everyone on the class, marked or not (voided included), so no
        # roster child's name reaches the model.
        full = await self._roster.full_names(session_id=session_id, occurrence_id=cmd.occurrence_id)
        ids = list(dict.fromkeys([*full, *marks]))
        if any(not full.get(sid, "").strip() for sid in ids):
            # A child we cannot name cannot be swapped for a code: the report
            # stays with the owner and never leaves the app.
            return report
        roster = [RosterName(student_id=sid, full_name=full[sid]) for sid in ids]
        options = await self._skills.options()
        aliased = alias_report(cmd.text, roster, [(o.skill_id, o.name) for o in options])
        firsts = {sid: first_name(full[sid]) for sid in ids}
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

    async def _replay(
        self,
        existing: ClassReport,
        cmd: SubmitClassReportCommand,
        actor: RecapActor,
        now: datetime,
    ) -> ClassReport:
        if (
            existing.author_id != actor.user_id
            or existing.occurrence_id != cmd.occurrence_id
            or existing.text != cmd.text
        ):
            raise RecapConflict("this report id was already used", report_id=cmd.report_id)
        if existing.processing_until is None:
            return existing
        if _utc(existing.processing_until) > _utc(now):
            # The first submit is still reading it: never a second model call.
            raise RecapConflict(
                "this report is still being read; try again in a moment",
                report_id=cmd.report_id,
                processing=True,
            )
        return await self._recover(existing)


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


class ChildRecapSkill(BaseModel):
    """Keyed by id: two levels may hold skills with the same name."""

    model_config = {"frozen": True}

    skill_id: str
    name: str
    #: Passed as of today by the pass pipeline (placement credits excluded).
    passed: bool


class ChildClassRecap(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    class_starts_at: datetime
    taught_skills: list[ChildRecapSkill]
    practiced_skills: list[ChildRecapSkill]


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
        recaps = recaps[:CHILD_RECAP_LIMIT]
        # One names read and one passes read for the whole list, not per recap.
        ids = list(
            dict.fromkeys(
                s for r in recaps for s in (*r.taught_skill_ids, *r.practiced_by(student_id))
            )
        )
        names = await self._skills.names(ids, active_only=False) if ids else {}
        passed = await self._passes.passed(student_id, ids) if ids else set()

        def skills(skill_ids: Sequence[str]) -> list[ChildRecapSkill]:
            return [
                ChildRecapSkill(skill_id=s, name=names[s], passed=s in passed)
                for s in skill_ids
                if s in names
            ]

        return [
            ChildClassRecap(
                occurrence_id=r.occurrence_id,
                class_starts_at=r.class_starts_at,
                taught_skills=skills(r.taught_skill_ids),
                practiced_skills=skills(r.practiced_by(student_id)),
            )
            for r in recaps
        ]
