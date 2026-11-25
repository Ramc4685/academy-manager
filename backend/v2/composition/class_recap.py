"""Class recap wiring, attached at ``app.state.class_recap``.

Adapters reshape other contexts for Coaching's recap ports (ADR-0005 rule 5):
the curriculum skill catalog (any level of the academy's default program),
student names from Enrollment, passes from student_progress (the authoritative
pass pipeline, read only), and the AI report reader. The reader turns every
AI refusal or failure (not entitled, capped, disabled, unreadable) into
``None``, so the report goes to the owner and the recap is entered by hand.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.v2.composition.ai import AiComposition
from backend.v2.composition.coaching_lookups import EnrollmentOccurrenceLookup
from backend.v2.contexts.ai.application.use_cases.interpret_class_report import (
    ClassReportInput,
    InterpretClassReport,
    ReportSkillRow,
)
from backend.v2.contexts.ai.infrastructure.disabled_llm_port import DisabledLlmPort
from backend.v2.contexts.coaching.application.use_cases.class_recap import (
    DemonstrationOutcome,
    GetClassRecap,
    ListChildClassRecaps,
    ListOpenClassReportHandoffs,
    RecordClassDemonstration,
    ResolveClassReport,
    SaveClassRecap,
    SkillOption,
    SubmitClassReport,
)
from backend.v2.contexts.coaching.domain.class_recap import (
    AliasedSkill,
    PassStatement,
    PracticeClaim,
    ReportFacts,
    TaughtClaim,
)
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoAttendanceRepository,
)
from backend.v2.contexts.coaching.infrastructure.mongo_class_recap_repo import (
    MongoClassRecapRepository,
    MongoClassReportRepository,
    StudentConfirmedAttendance,
)
from backend.v2.contexts.curriculum.application.use_cases.manage_program import (
    ResolveDefaultActiveProgram,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_program_repo import MongoProgramRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository
from backend.v2.contexts.enrollment.application.use_cases.get_occurrence_roster import (
    GetOccurrenceRoster,
)
from backend.v2.contexts.enrollment.application.use_cases.get_session_roster import (
    GetSessionRoster,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_absence_notice_repo import (
    MongoAbsenceNoticeRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_roster_repo import (
    MongoOccurrenceRosterRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.student_progress.application.use_cases.mark_skill_mastered import (
    MarkSkillMastered,
    MarkSkillMasteredCommand,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_skill_progress_repo import (
    MongoStudentSkillProgressRepository,
)
from backend.v2.shared.events import Outbox
from backend.v2.shared.http.errors import DomainError
from backend.v2.shared.idempotency import IdempotencyStore
from backend.v2.shared.tenancy import current_academy_id

log = logging.getLogger(__name__)

# Bounds the model's candidate list and the coach's picker.
MAX_SKILL_OPTIONS = 200


class CurriculumRecapSkills:
    """``RecapSkillCatalog`` over the curriculum repos: every active skill of
    the default program, with its level name, so other-level practice can be
    recorded against real curriculum."""

    def __init__(self, *, skills: Any, levels: Any, resolve_default_program: Any) -> None:
        self._skills = skills
        self._levels = levels
        self._resolve_default_program = resolve_default_program

    async def options(self) -> list[SkillOption]:
        try:
            program = await self._resolve_default_program.execute()
        except DomainError:
            return []  # no curriculum yet: nothing to pick
        program_id = str(program.program_id)
        levels = await self._levels.list_for_program(program_id)
        order = {str(lvl.level_id): (lvl.sequence, str(lvl.name)) for lvl in levels}
        rows = [
            (order[str(s.level_id)][0], s.sequence, s)
            for s in await self._skills.list_for_program(program_id)
            if str(s.level_id) in order
        ]
        rows.sort(key=lambda r: (r[0], r[1]))
        return [
            SkillOption(
                skill_id=str(s.skill_id), name=str(s.name), level_name=order[str(s.level_id)][1]
            )
            for _, _, s in rows[:MAX_SKILL_OPTIONS]
        ]

    async def names(self, skill_ids: list[str], *, active_only: bool) -> dict[str, str]:
        return {
            str(s.skill_id): str(s.name)
            for s in await self._skills.list_by_ids(skill_ids)
            if s.is_active or not active_only
        }


class EnrollmentStudentNames:
    def __init__(self, students: Any) -> None:
        self._students = students

    async def full_names(self, student_ids: list[str]) -> dict[str, str]:
        if not student_ids:
            return {}
        return {
            str(s.student_id): str(getattr(s, "full_name", "") or "Student")
            for s in await self._students.by_ids(student_ids)
        }


class EnrollmentOccurrenceRosterNames:
    """``OccurrenceRosterNames`` over the register's own roster read, so the
    report aliases every child the coach could have written about."""

    def __init__(self, roster: GetOccurrenceRoster) -> None:
        self._roster = roster

    async def full_names(self, *, session_id: str, occurrence_id: str) -> dict[str, str]:
        rows = await self._roster.execute(session_id=session_id, occurrence_id=occurrence_id)
        return {row.student_id: row.full_name for row in rows}


class SkillProgressPasses:
    """``PassedSkills``: a skill counts as passed only when the pass pipeline
    has written a non-silent ``PASSED`` for this child (one read)."""

    def __init__(self, progress: Any) -> None:
        self._progress = progress

    async def passed(self, student_id: str, skill_ids: list[str]) -> set[str]:
        wanted = set(skill_ids)
        return {
            str(row.skill_id)
            for row in await self._progress.list_passed_for_student(student_id)
            if str(row.skill_id) in wanted
        }


class ProgressClassDemonstrations:
    """``ClassDemonstrationWriter`` over student_progress's one pass writer
    (MarkSkillMastered -> RecordTestAttempt), with the program read from the
    skill itself rather than trusted from the client."""

    def __init__(self, *, skills: Any, mark_mastered: MarkSkillMastered) -> None:
        self._skills = skills
        self._mark = mark_mastered

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
        mutation_id: str,
    ) -> list[DemonstrationOutcome]:
        skill = await self._skills.get(skill_id)
        if skill is None:
            return [
                DemonstrationOutcome(student_id=sid, outcome="not_on_level") for sid in student_ids
            ]
        outcomes = await self._mark.execute(
            MarkSkillMasteredCommand(
                skill_id=skill_id,
                program_id=str(skill.program_id),
                student_ids=student_ids,
                coach_id=coach_id,
                session_id=session_id,
                can_sign_off=can_sign_off,
                off_level_ok=True,
                occurrence_id=occurrence_id,
                observed_at=observed_at,
                mutation_id=mutation_id,
            )
        )
        return [DemonstrationOutcome(**o.model_dump()) for o in outcomes]


class AiClassReportInterpreter:
    """``ClassReportInterpreter`` over the AI context's use case."""

    def __init__(self, interpret: InterpretClassReport | None) -> None:
        self._interpret = interpret

    async def interpret(
        self,
        *,
        text: str,
        student_aliases: list[str],
        skills: list[AliasedSkill],
        approver: str,
    ) -> ReportFacts | None:
        if self._interpret is None or not skills:
            return None
        try:
            reading = await self._interpret.execute(
                ClassReportInput(
                    report=text,
                    students=student_aliases[:100],
                    skills=[ReportSkillRow(alias=s.alias, name=s.name[:120]) for s in skills],
                ),
                approver=approver,
            )
        except (DomainError, ValueError) as exc:
            # Not entitled, capped, disabled, unreadable or out of bounds
            # (pydantic's ValidationError is a ValueError): owner handoff.
            log.info("class report handed to the owner: %s", getattr(exc, "code", "invalid"))
            return None
        return ReportFacts(
            taught=tuple(
                TaughtClaim(skills=tuple(c.skills), evidence=c.evidence) for c in reading.taught
            ),
            practice=tuple(
                PracticeClaim(
                    who=c.who,
                    students=tuple(c.students),
                    except_students=tuple(c.except_students),
                    skills=tuple(c.skills),
                    evidence=c.evidence,
                )
                for c in reading.practice
            ),
            passes=tuple(
                PassStatement(student=p.student, skill=p.skill, evidence=p.evidence)
                for p in reading.passes
            ),
            questions=tuple(reading.questions),
        )


@dataclass(frozen=True)
class ClassRecapComposition:
    get: GetClassRecap
    save: SaveClassRecap
    submit_report: SubmitClassReport
    list_handoffs: ListOpenClassReportHandoffs
    resolve_report: ResolveClassReport
    list_for_child: ListChildClassRecaps
    record_demonstration: RecordClassDemonstration
    #: A model is wired; otherwise every report goes to the owner.
    ai_enabled: bool


def compose_class_recap(
    db: Any,
    ai: AiComposition,
    outbox: Outbox | None = None,
    idempotency_store: IdempotencyStore | None = None,
) -> ClassRecapComposition:
    from backend.v2.composition.pathway import compose_student_progress

    recaps = MongoClassRecapRepository(db)
    reports = MongoClassReportRepository(db)
    occurrence_rows = MongoSessionOccurrenceRepository(db)
    occurrences = EnrollmentOccurrenceLookup(occurrence_rows)
    attendance = MongoAttendanceRepository(db)
    skills = CurriculumRecapSkills(
        skills=MongoSkillRepository(db),
        levels=MongoLevelRepository(db),
        resolve_default_program=ResolveDefaultActiveProgram(programs=MongoProgramRepository(db)),
    )
    students = MongoStudentRepository(db)
    names = EnrollmentStudentNames(students)
    roster = EnrollmentOccurrenceRosterNames(
        GetOccurrenceRoster(
            get_roster=GetSessionRoster(
                enrollments=MongoEnrollmentRepository(db), students=students
            ),
            absence_notices=MongoAbsenceNoticeRepository(db),
            occurrence_roster=MongoOccurrenceRosterRepository(db),
            students=students,
            occurrences=occurrence_rows,
            marks=attendance,
        )
    )
    ai_enabled = not isinstance(ai.llm, DisabledLlmPort)
    interpreter = AiClassReportInterpreter(
        InterpretClassReport(
            llm=ai.llm, record_ai_call=ai.record_ai_call, entitlement=ai.entitlement
        )
        if ai_enabled
        else None
    )
    save = SaveClassRecap(
        recaps=recaps,
        occurrences=occurrences,
        attendance=attendance,
        skills=skills,
        academy_id=current_academy_id,
    )
    return ClassRecapComposition(
        get=GetClassRecap(
            recaps=recaps,
            reports=reports,
            occurrences=occurrences,
            attendance=attendance,
            skills=skills,
            names=names,
        ),
        save=save,
        submit_report=SubmitClassReport(
            reports=reports,
            recaps=recaps,
            occurrences=occurrences,
            attendance=attendance,
            skills=skills,
            roster=roster,
            interpreter=interpreter,
            save=save,
            academy_id=current_academy_id,
        ),
        list_handoffs=ListOpenClassReportHandoffs(reports=reports),
        resolve_report=ResolveClassReport(reports=reports),
        list_for_child=ListChildClassRecaps(
            recaps=recaps,
            attendance=StudentConfirmedAttendance(db),
            skills=skills,
            passes=SkillProgressPasses(MongoStudentSkillProgressRepository(db)),
        ),
        record_demonstration=RecordClassDemonstration(
            occurrences=occurrences,
            attendance=attendance,
            skills=skills,
            writer=ProgressClassDemonstrations(
                skills=MongoSkillRepository(db),
                mark_mastered=compose_student_progress(
                    db, outbox, idempotency_store=idempotency_store
                ).mark_skill_mastered,
            ),
        ),
        ai_enabled=ai_enabled,
    )
