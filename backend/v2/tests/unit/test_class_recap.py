"""Class recap invariants: per-child practice, the deterministic report gate
(aliases, redaction, quoted evidence, group wording, merge-only) and the use
cases around the one guarded writer. Fakes copy the real store's refusals
(insert-only, revision compare-and-set), per the #664 lesson."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.coaching.application.ports import OccurrenceDetails
from backend.v2.contexts.coaching.application.use_cases.class_recap import (
    GetClassRecap,
    ListChildClassRecaps,
    ListOpenClassReportHandoffs,
    RecapActor,
    ResolveClassReport,
    SaveClassRecap,
    SaveClassRecapCommand,
    SkillOption,
    SubmitClassReport,
    SubmitClassReportCommand,
)
from backend.v2.contexts.coaching.domain.class_recap import (
    ChildPractice,
    ClassRecap,
    ClassReport,
    PassClaim,
    PassStatement,
    PracticeClaim,
    ReportFacts,
    RosterName,
    TaughtClaim,
    alias_report,
    merge_practice,
    resolve_report,
)
from backend.v2.contexts.coaching.domain.errors import (
    OccurrenceNotStarted,
    RecapConflict,
    RecapInvalid,
    RecapNotAllowed,
    RecapWriteForbidden,
    SessionCancelled,
)
from backend.v2.contexts.coaching.domain.models import Attendance

NOW = datetime(2026, 11, 18, 20, 0, tzinfo=UTC)
STARTS = NOW - timedelta(hours=2)
OCC, SESSION, ACADEMY = "occ-1", "sess-1", "acad-1"
LEAD, ASSIST, OWNER, OTHER = "coach-1", "assist-1", "owner-1", "coach-9"
GRIP, SMASH, OLD = "skill-l1", "skill-l3", "skill-old"
# GRIP is on the class's level, SMASH two levels up: both real curriculum.
SKILLS = {GRIP: "Forehand grip", SMASH: "Jump smash"}
RETIRED = {OLD: "Old drill"}
MARKS = {"maya": "present", "leo": "present", "sam": "late", "ana": "absent", "vic": "voided"}
FULL = {
    "maya": "Maya Lopez",
    "leo": "Leo Park",
    "sam": "Sam Lee",
    "ana": "Ana Diaz",
    "vic": "Vic Void",
    "zoe": "Zoe Ng",
}
# alias_report sorts the (non-voided) roster by full name.
ALIAS = {"ana": "S1", "leo": "S2", "maya": "S3", "sam": "S4"}

LEAD_ACTOR = RecapActor(user_id=LEAD)
OWNER_ACTOR = RecapActor(user_id=OWNER, is_owner=True, is_supervisor=True)
ADMIN_ACTOR = RecapActor(user_id="admin-1", is_supervisor=True)
ASSIST_ACTOR = RecapActor(user_id=ASSIST, is_assistant_only=True)


# --- fakes -----------------------------------------------------------------


class Occurrences:
    def __init__(self, **overrides: Any) -> None:
        base: dict[str, Any] = {
            "occurrence_id": OCC,
            "session_id": SESSION,
            "starts_at": STARTS,
            "status": "scheduled",
            "scheduled_coach_id": LEAD,
            "assistant_coach_ids": (ASSIST,),
        }
        self.occ = OccurrenceDetails(**{**base, **overrides})

    async def get(self, occurrence_id: str) -> OccurrenceDetails | None:
        return self.occ if occurrence_id == OCC else None


class AttendanceRows:
    def __init__(self, marks: dict[str, str] | None = None) -> None:
        self.marks = dict(MARKS if marks is None else marks)

    async def list_for_occurrence(self, occurrence_id: str) -> list[Attendance]:
        if occurrence_id != OCC:
            return []
        return [
            Attendance(
                attendance_id=f"a-{sid}",
                academy_id=ACADEMY,
                occurrence_id=OCC,
                session_id=SESSION,
                student_id=sid,
                marked_by=LEAD,
                marked_at=NOW,
                status=mark,  # type: ignore[arg-type]
            )
            for sid, mark in self.marks.items()
        ]

    async def confirmed_occurrence_ids(self, student_id: str, *, limit: int) -> list[str]:
        return [OCC] if self.marks.get(student_id) in {"present", "late"} else []


class Catalog:
    async def options(self) -> list[SkillOption]:
        return [
            SkillOption(skill_id=GRIP, name="Forehand grip", level_name="Level 1"),
            SkillOption(skill_id=SMASH, name="Jump smash", level_name="Level 3"),
        ]

    async def names(self, skill_ids: list[str], *, active_only: bool) -> dict[str, str]:
        pool = SKILLS if active_only else {**SKILLS, **RETIRED}
        return {sid: pool[sid] for sid in skill_ids if sid in pool}


class Names:
    def __init__(self, full: dict[str, str] | None = None) -> None:
        self.full = FULL if full is None else full

    async def full_names(self, student_ids: list[str]) -> dict[str, str]:
        return {sid: self.full[sid] for sid in student_ids if sid in self.full}


class Roster:
    """The register's roster: every child on the class, marked or not (Zoe is
    enrolled but unmarked, Vic's mark is voided)."""

    def __init__(self, full: dict[str, str] | None = None) -> None:
        self.full = FULL if full is None else full
        self.asked: list[str] = []

    async def full_names(self, *, session_id: str, occurrence_id: str) -> dict[str, str]:
        self.asked.append(session_id)
        return dict(self.full) if occurrence_id == OCC else {}


class Passes:
    """The pass pipeline's word, independent of anything a report said."""

    def __init__(self, passed: dict[str, set[str]] | None = None) -> None:
        self.passed_by = passed or {}

    async def passed(self, student_id: str, skill_ids: list[str]) -> set[str]:
        return self.passed_by.get(student_id, set()) & set(skill_ids)


class Recaps:
    """Mirrors MongoClassRecapRepository: unique per occurrence, CAS on revision."""

    def __init__(self) -> None:
        self.rows: dict[str, ClassRecap] = {}
        self.saves = 0

    async def get(self, occurrence_id: str) -> ClassRecap | None:
        return self.rows.get(occurrence_id)

    async def save(self, recap: ClassRecap, *, expected_revision: int) -> bool:
        current = self.rows.get(recap.occurrence_id)
        if (current.revision if current else 0) != expected_revision:
            return False
        self.rows[recap.occurrence_id] = recap
        self.saves += 1
        return True

    async def list_for_occurrences(self, occurrence_ids: list[str]) -> list[ClassRecap]:
        return [r for oid, r in self.rows.items() if oid in occurrence_ids]


class Reports:
    """Insert-only, like MongoClassReportRepository."""

    def __init__(self) -> None:
        self.rows: dict[str, ClassReport] = {}

    async def get(self, report_id: str) -> ClassReport | None:
        return self.rows.get(report_id)

    async def insert(self, report: ClassReport) -> bool:
        if report.report_id in self.rows:
            return False
        self.rows[report.report_id] = report
        return True

    async def finish(self, report: ClassReport) -> bool:
        row = self.rows.get(report.report_id)
        if row is None or row.processing_until is None:
            return False
        fields = ("outcome", "ai_used", "questions", "pass_claims", "applied_revision")
        self.rows[report.report_id] = row.model_copy(
            update={**{k: getattr(report, k) for k in fields}, "processing_until": None}
        )
        return True

    async def list_for_occurrence(self, occurrence_id: str) -> list[ClassReport]:
        return [r for r in self.rows.values() if r.occurrence_id == occurrence_id]

    async def list_open_handoffs(self, *, limit: int) -> list[ClassReport]:
        return [
            r
            for r in self.rows.values()
            if r.outcome == "sent_to_owner"
            and r.resolved_at is None
            and (r.processing_until is None or r.processing_until <= NOW)
        ][:limit]

    async def resolve(self, report_id: str, *, by: str, at: datetime) -> ClassReport | None:
        row = self.rows.get(report_id)
        if row is None or row.resolved_at is not None:
            return None
        self.rows[report_id] = row.model_copy(update={"resolved_by": by, "resolved_at": at})
        return self.rows[report_id]


class Interpreter:
    def __init__(self, facts: ReportFacts | None) -> None:
        self.facts = facts
        self.calls: list[dict[str, Any]] = []

    async def interpret(self, **kwargs: Any) -> ReportFacts | None:
        self.calls.append(kwargs)
        return self.facts


class World:
    def __init__(self, *, marks: dict[str, str] | None = None, **occ: Any) -> None:
        self.recaps, self.reports = Recaps(), Reports()
        self.occurrences, self.attendance = Occurrences(**occ), AttendanceRows(marks)
        self.save = SaveClassRecap(
            recaps=self.recaps,
            occurrences=self.occurrences,
            attendance=self.attendance,
            skills=Catalog(),
            academy_id=lambda: ACADEMY,
            clock=lambda: NOW,
        )

    def get(self) -> GetClassRecap:
        return GetClassRecap(
            recaps=self.recaps,
            reports=self.reports,
            occurrences=self.occurrences,
            attendance=self.attendance,
            skills=Catalog(),
            names=Names(),
        )

    def submit(
        self, interpreter: Interpreter, roster: Roster | None = None, *, now: datetime = NOW
    ) -> SubmitClassReport:
        return SubmitClassReport(
            reports=self.reports,
            recaps=self.recaps,
            occurrences=self.occurrences,
            attendance=self.attendance,
            skills=Catalog(),
            roster=roster or Roster(),
            interpreter=interpreter,
            save=self.save,
            academy_id=lambda: ACADEMY,
            clock=lambda: now,
        )

    def child(self, passes: Passes | None = None) -> ListChildClassRecaps:
        return ListChildClassRecaps(
            recaps=self.recaps,
            attendance=self.attendance,
            skills=Catalog(),
            passes=passes or Passes(),
        )


def _practice(**rows: list[str]) -> list[ChildPractice]:
    return [ChildPractice(student_id=sid, skill_ids=tuple(ids)) for sid, ids in rows.items()]


def _cmd(**kw: Any) -> SaveClassRecapCommand:
    base: dict[str, Any] = {
        "occurrence_id": OCC,
        "class_starts_at": STARTS,
        "mutation_id": "m-1",
        "expected_revision": 0,
        "taught_skill_ids": [GRIP],
        "practice": _practice(maya=[GRIP]),
    }
    return SaveClassRecapCommand(**{**base, **kw})


def _report(text: str, rid: str = "r-1", *, use_ai: bool = True) -> SubmitClassReportCommand:
    return SubmitClassReportCommand(
        occurrence_id=OCC, class_starts_at=STARTS, report_id=rid, text=text, use_ai=use_ai
    )


def _aliased(text: str):
    roster = [
        RosterName(student_id=sid, full_name=FULL[sid]) for sid, m in MARKS.items() if m != "voided"
    ]
    return alias_report(text, roster, [(GRIP, "Forehand grip"), (SMASH, "Jump smash")])


FIRSTS = {sid: name.split()[0] for sid, name in FULL.items()}


def _resolve(text: str, facts: ReportFacts, existing: ClassRecap | None = None):
    return resolve_report(
        facts,
        aliased=_aliased(text),
        attendance={k: v for k, v in MARKS.items() if v != "voided"},
        first_names=FIRSTS,
        existing=existing,
    )


# --- aliasing --------------------------------------------------------------


def test_aliases_hide_names_ids_and_contact_details() -> None:
    aliased = _aliased(
        "Maya Lopez and Leo worked hard. Sam's mum (sam.mum@example.com, 309 555 0100) called."
    )
    assert aliased.text == "S3 and S2 worked hard. S4's mum ([email], [number]) called."
    assert aliased.questions == ()
    assert aliased.student_aliases == {"S1": "ana", "S2": "leo", "S3": "maya", "S4": "sam"}
    for secret in ("Maya", "Lopez", "maya", "example.com", "555"):
        assert secret not in aliased.text


def test_duplicate_first_names_are_asked_locally_unless_full_name_used() -> None:
    roster = [
        RosterName(student_id="m1", full_name="Maya Lopez"),
        RosterName(student_id="m2", full_name="Maya Chen"),
    ]
    ambiguous = alias_report("Maya did grips.", roster, [(GRIP, "Forehand grip")])
    assert ambiguous.questions == ("More than one student is named Maya. Use their full name.",)
    clear = alias_report("Maya Chen did grips.", roster, [(GRIP, "Forehand grip")])
    assert clear.questions == () and clear.text == "S1 did grips."


# --- resolve_report --------------------------------------------------------


def test_split_drills_credit_each_child_only_their_own_skill() -> None:
    text = "Maya did grip drills. Leo worked on smashes."
    facts = ReportFacts(
        practice=(
            PracticeClaim(who="listed", students=("S3",), skills=("K1",), evidence="S3 did grip"),
            PracticeClaim(
                who="listed", students=("S2",), skills=("K2",), evidence="S2 worked on smashes"
            ),
        )
    )
    resolved = _resolve(text, facts)
    assert resolved.questions == ()
    assert resolved.practice == (
        ChildPractice(student_id="maya", skill_ids=(GRIP,)),
        ChildPractice(student_id="leo", skill_ids=(SMASH,)),
    )
    assert resolved.taught_skill_ids == (GRIP, SMASH)


def test_taught_only_report_writes_taught_without_any_practice() -> None:
    text = "Today we introduced the jump smash."
    facts = ReportFacts(taught=(TaughtClaim(skills=("K2",), evidence="introduced the jump smash"),))
    resolved = _resolve(text, facts)
    assert resolved.taught_skill_ids == (SMASH,) and resolved.practice == ()


def test_group_needs_group_words_in_the_quote() -> None:
    text = "We drilled grips. Everyone except Sam joined in on grips."
    vague = ReportFacts(
        practice=(PracticeClaim(who="group", skills=("K1",), evidence="We drilled grips"),)
    )
    assert _resolve(text, vague).questions == (
        "Who took part? Say everyone, or name the students.",
    )
    explicit = ReportFacts(
        practice=(
            PracticeClaim(
                who="group",
                except_students=("S4",),
                skills=("K1",),
                evidence="Everyone except S4 joined in on grips",
            ),
        )
    )
    resolved = _resolve(text, explicit)
    # Present maya and leo; late sam excluded individually; absent ana never.
    assert [row.student_id for row in resolved.practice] == ["maya", "leo"]


def test_absent_child_named_in_report_needs_correction() -> None:
    text = "Ana did grips."
    facts = ReportFacts(
        practice=(
            PracticeClaim(who="listed", students=("S1",), skills=("K1",), evidence="S1 did grips"),
        )
    )
    assert _resolve(text, facts).questions == (
        "Ana is not marked present. Correct attendance or the report first.",
    )


def test_unquoted_or_ungrounded_claims_are_questions() -> None:
    text = "Maya did grips."
    invented = ReportFacts(
        practice=(
            PracticeClaim(who="listed", students=("S3",), skills=("K1",), evidence="S3 smashed"),
        )
    )
    assert "did not match the report" in _resolve(text, invented).questions[0]
    wrong_skill = ReportFacts(
        practice=(
            PracticeClaim(who="listed", students=("S3",), skills=("K2",), evidence="S3 did grips"),
        )
    )
    assert _resolve(text, wrong_skill).questions == (
        "I could not find Jump smash in the report. Which skill was it?",
    )


def test_excluding_a_child_who_already_practised_asks_instead_of_deleting() -> None:
    existing = _recap(practice=(ChildPractice(student_id="sam", skill_ids=(GRIP,)),))
    text = "Everyone except Sam did grips."
    facts = ReportFacts(
        practice=(
            PracticeClaim(
                who="group",
                except_students=("S4",),
                skills=("K1",),
                evidence="Everyone except S4 did grips",
            ),
        )
    )
    resolved = _resolve(text, facts, existing)
    assert resolved.questions == (
        "Sam is already recorded as practising Forehand grip. "
        "Correct the recap form if that was wrong.",
    )


def test_pass_claims_are_kept_only_when_quoted_and_never_become_practice() -> None:
    text = "We worked on grips. Maya passed her grip!"
    facts = ReportFacts(
        taught=(TaughtClaim(skills=("K1",), evidence="worked on grips"),),
        passes=(
            PassStatement(student="S3", skill="K1", evidence="S3 passed her grip"),
            PassStatement(student="S2", skill="K1", evidence="S2 passed his grip"),  # not quoted
        ),
    )
    resolved = _resolve(text, facts)
    assert resolved.pass_claims == (PassClaim(student_id="maya", skill_id=GRIP),)
    assert resolved.practice == ()


def test_model_questions_are_shown_with_names_not_aliases() -> None:
    facts = ReportFacts(questions=("Did S3 do the smash too?",))
    assert _resolve("Maya worked.", facts).questions[0] == "Did Maya do the smash too?"


def test_merge_keeps_everyone_already_recorded() -> None:
    base = (ChildPractice(student_id="maya", skill_ids=(GRIP,)),)
    added = (
        ChildPractice(student_id="maya", skill_ids=(SMASH,)),
        ChildPractice(student_id="leo", skill_ids=(SMASH,)),
    )
    assert merge_practice(base, added) == (
        ChildPractice(student_id="maya", skill_ids=(GRIP, SMASH)),
        ChildPractice(student_id="leo", skill_ids=(SMASH,)),
    )


def _recap(**kw: Any) -> ClassRecap:
    base: dict[str, Any] = {
        "recap_id": "rc-1",
        "academy_id": ACADEMY,
        "occurrence_id": OCC,
        "session_id": SESSION,
        "class_starts_at": STARTS,
        "taught_skill_ids": (GRIP,),
        "revision": 1,
        "updated_by": LEAD,
        "updated_at": NOW,
    }
    return ClassRecap(**{**base, **kw})


# --- SaveClassRecap --------------------------------------------------------


async def test_direct_entry_records_split_practice_and_other_level_skill() -> None:
    w = World()
    recap = await w.save.execute(
        _cmd(taught_skill_ids=[GRIP, SMASH, GRIP], practice=_practice(maya=[GRIP], leo=[SMASH])),
        LEAD_ACTOR,
    )
    assert recap.revision == 1 and recap.taught_skill_ids == (GRIP, SMASH)
    assert recap.practiced_by("maya") == (GRIP,) and recap.practiced_by("leo") == (SMASH,)


async def test_taught_with_nobody_practising_is_kept() -> None:
    recap = await World().save.execute(_cmd(practice=[]), LEAD_ACTOR)
    assert recap.taught_skill_ids == (GRIP,) and recap.practice == ()


async def test_practised_skill_must_be_taught() -> None:
    with pytest.raises(RecapInvalid):
        await World().save.execute(_cmd(practice=_practice(maya=[SMASH])), LEAD_ACTOR)


async def test_owner_may_write_any_class() -> None:
    assert (await World().save.execute(_cmd(), OWNER_ACTOR)).updated_by == OWNER


@pytest.mark.parametrize(
    "actor", [ASSIST_ACTOR, ADMIN_ACTOR, RecapActor(user_id=LEAD, is_assistant_only=True)]
)
async def test_assistants_and_covering_admins_cannot_write(actor: RecapActor) -> None:
    w = World()
    with pytest.raises(RecapWriteForbidden):
        await w.save.execute(_cmd(), actor)
    assert w.recaps.saves == 0


async def test_unlisted_coach_and_unknown_class_are_404() -> None:
    w = World()
    with pytest.raises(RecapNotAllowed):
        await w.save.execute(_cmd(), RecapActor(user_id=OTHER))
    with pytest.raises(RecapNotAllowed):
        await w.save.execute(_cmd(occurrence_id="occ-x"), OWNER_ACTOR)


@pytest.mark.parametrize("student", ["ana", "vic", "zoe"])
async def test_only_confirmed_present_students_get_practice(student: str) -> None:
    w = World()
    with pytest.raises(RecapInvalid) as exc:
        await w.save.execute(_cmd(practice=_practice(maya=[GRIP], **{student: [GRIP]})), LEAD_ACTOR)
    assert exc.value.details["student_ids"] == [student]
    assert w.recaps.saves == 0


async def test_unknown_or_retired_skill_is_refused() -> None:
    w = World()
    for skill in ("skill-made-up", OLD):
        with pytest.raises(RecapInvalid):
            await w.save.execute(_cmd(taught_skill_ids=[skill], practice=[]), LEAD_ACTOR)


async def test_wrong_dated_class_is_refused() -> None:
    with pytest.raises(RecapConflict):
        await World().save.execute(_cmd(class_starts_at=STARTS + timedelta(days=7)), LEAD_ACTOR)


async def test_replay_returns_the_saved_recap_and_stale_correction_conflicts() -> None:
    w = World()
    first = await w.save.execute(_cmd(), LEAD_ACTOR)
    assert await w.save.execute(_cmd(), LEAD_ACTOR) == first
    assert w.recaps.saves == 1
    with pytest.raises(RecapConflict):
        await w.save.execute(_cmd(mutation_id="m-2", expected_revision=0), LEAD_ACTOR)
    corrected = await w.save.execute(
        _cmd(mutation_id="m-2", expected_revision=1, practice=[]), OWNER_ACTOR
    )
    assert corrected.revision == 2 and corrected.practice == ()
    assert corrected.recap_id == first.recap_id


async def test_cancelled_or_future_class_cannot_be_recapped() -> None:
    with pytest.raises(SessionCancelled):
        await World(status="cancelled").save.execute(_cmd(), LEAD_ACTOR)
    later = NOW + timedelta(days=2)
    with pytest.raises(OccurrenceNotStarted):
        await World(starts_at=later).save.execute(_cmd(class_starts_at=later), LEAD_ACTOR)


# --- GetClassRecap ---------------------------------------------------------


async def test_reports_are_private_to_author_and_owner() -> None:
    w = World()
    await w.submit(Interpreter(None)).execute(_report("Grips.", use_ai=False), LEAD_ACTOR)
    lead = await w.get().execute(OCC, LEAD_ACTOR)
    owner = await w.get().execute(OCC, OWNER_ACTOR)
    assistant = await w.get().execute(OCC, ASSIST_ACTOR)
    admin = await w.get().execute(OCC, ADMIN_ACTOR)
    assert [r.report_id for r in lead.reports] == ["r-1"]
    assert [r.report_id for r in owner.reports] == ["r-1"]
    assert assistant.reports == [] and admin.reports == []
    assert [s.can_edit for s in (lead, owner, assistant, admin)] == [True, True, False, False]
    assert assistant.skill_options == []
    assert [r.student_id for r in lead.roster] == ["ana", "leo", "maya", "sam"]  # vic voided


async def test_unlisted_coach_cannot_read() -> None:
    with pytest.raises(RecapNotAllowed):
        await World().get().execute(OCC, RecapActor(user_id=OTHER))


# --- SubmitClassReport -----------------------------------------------------

SPLIT_TEXT = "Maya did grip drills. Leo worked on smashes. Maya passed her grip!"
SPLIT = ReportFacts(
    practice=(
        PracticeClaim(who="listed", students=("S3",), skills=("K1",), evidence="S3 did grip"),
        PracticeClaim(
            who="listed", students=("S2",), skills=("K2",), evidence="S2 worked on smashes"
        ),
    ),
    passes=(PassStatement(student="S3", skill="K1", evidence="S3 passed her grip"),),
)


async def test_split_report_applies_per_child_and_keeps_the_pass_as_follow_up() -> None:
    w = World()
    interpreter = Interpreter(SPLIT)
    report = await w.submit(interpreter).execute(_report(SPLIT_TEXT), LEAD_ACTOR)
    assert report.outcome == "applied" and report.ai_used and report.applied_revision == 1
    recap = w.recaps.rows[OCC]
    assert recap.practiced_by("maya") == (GRIP,) and recap.practiced_by("leo") == (SMASH,)
    assert recap.practiced_by("sam") == () and recap.source_report_id == "r-1"
    assert report.pass_claims == (PassClaim(student_id="maya", skill_id=GRIP),)
    # The model saw aliases only: no names, ids, attendance or roster details.
    seen = interpreter.calls[0]
    assert seen["text"] == "S3 did grip drills. S2 worked on smashes. S3 passed her grip!"
    # The whole roster is aliased: unmarked Zoe and voided Vic too.
    assert seen["student_aliases"] == ["S1", "S2", "S3", "S4", "S5", "S6"]
    assert all(s.alias.startswith("K") for s in seen["skills"])
    assert "maya" not in repr(seen) and "Lopez" not in repr(seen)


async def test_partial_report_never_removes_existing_participants() -> None:
    w = World()
    await w.save.execute(
        _cmd(taught_skill_ids=[GRIP], practice=_practice(sam=[GRIP], maya=[GRIP])), LEAD_ACTOR
    )
    report = await w.submit(Interpreter(SPLIT)).execute(_report(SPLIT_TEXT), LEAD_ACTOR)
    assert report.outcome == "applied" and report.applied_revision == 2
    recap = w.recaps.rows[OCC]
    assert recap.taught_skill_ids == (GRIP, SMASH)
    assert recap.practiced_by("sam") == (GRIP,)  # omitted by the report, still there
    assert recap.practiced_by("maya") == (GRIP,)
    assert recap.practiced_by("leo") == (SMASH,)


async def test_taught_only_report_adds_taught_and_credits_nobody() -> None:
    w = World()
    facts = ReportFacts(taught=(TaughtClaim(skills=("K2",), evidence="introduced the jump smash"),))
    report = await w.submit(Interpreter(facts)).execute(
        _report("Today we introduced the jump smash."), LEAD_ACTOR
    )
    assert report.outcome == "applied"
    assert w.recaps.rows[OCC].taught_skill_ids == (SMASH,)
    assert w.recaps.rows[OCC].practice == ()


async def test_unclear_report_asks_and_writes_nothing() -> None:
    w = World()
    facts = ReportFacts(practice=(PracticeClaim(who="group", skills=("K1",), evidence="grips"),))
    report = await w.submit(Interpreter(facts)).execute(_report("We did grips."), LEAD_ACTOR)
    assert report.outcome == "needs_clarification" and report.questions
    assert w.recaps.saves == 0


async def test_duplicate_names_are_settled_locally_without_calling_ai() -> None:
    w = World()
    interpreter = Interpreter(SPLIT)
    roster = Roster({**FULL, "leo": "Maya Park"})
    report = await w.submit(interpreter, roster).execute(_report("Maya did grips."), LEAD_ACTOR)
    assert report.outcome == "needs_clarification" and not report.ai_used
    assert interpreter.calls == [] and w.recaps.saves == 0


async def test_without_ai_permission_the_report_goes_to_the_owner() -> None:
    w = World()
    interpreter = Interpreter(SPLIT)
    report = await w.submit(interpreter).execute(_report(SPLIT_TEXT, use_ai=False), LEAD_ACTOR)
    assert report.outcome == "sent_to_owner" and interpreter.calls == []
    unavailable = await w.submit(Interpreter(None)).execute(_report(SPLIT_TEXT, "r-2"), LEAD_ACTOR)
    assert unavailable.outcome == "sent_to_owner" and not unavailable.ai_used
    assert w.recaps.saves == 0


async def test_report_replay_never_calls_the_model_twice() -> None:
    w = World()
    interpreter = Interpreter(SPLIT)
    first = await w.submit(interpreter).execute(_report(SPLIT_TEXT), LEAD_ACTOR)
    again = await w.submit(interpreter).execute(_report(SPLIT_TEXT), LEAD_ACTOR)
    assert again == first and len(interpreter.calls) == 1 and w.recaps.saves == 1
    with pytest.raises(RecapConflict):
        await w.submit(interpreter).execute(_report("different"), LEAD_ACTOR)


async def test_assistant_cannot_submit_a_report() -> None:
    w = World()
    interpreter = Interpreter(SPLIT)
    with pytest.raises(RecapWriteForbidden):
        await w.submit(interpreter).execute(_report(SPLIT_TEXT), ASSIST_ACTOR)
    assert interpreter.calls == []


async def test_practice_kept_after_an_attendance_correction_but_no_new_credit() -> None:
    w = World()
    await w.save.execute(_cmd(practice=_practice(maya=[GRIP])), LEAD_ACTOR)
    w.attendance.marks["maya"] = "absent"
    # The coach's form still sends Maya's hidden row: the save goes through.
    kept = await w.save.execute(
        _cmd(mutation_id="m-2", expected_revision=1, practice=_practice(maya=[GRIP], leo=[GRIP])),
        LEAD_ACTOR,
    )
    assert kept.practiced_by("maya") == (GRIP,) and kept.practiced_by("leo") == (GRIP,)
    with pytest.raises(RecapInvalid):
        await w.save.execute(
            _cmd(
                mutation_id="m-3",
                expected_revision=2,
                taught_skill_ids=[GRIP, SMASH],
                practice=_practice(maya=[GRIP, SMASH]),
            ),
            LEAD_ACTOR,
        )
    # A report on the class still applies, carrying Maya's row along.
    facts = ReportFacts(
        practice=(
            PracticeClaim(who="listed", students=("S4",), skills=("K1",), evidence="S4 did grip"),
        )
    )
    report = await w.submit(Interpreter(facts)).execute(_report("Sam did grip drills."), LEAD_ACTOR)
    assert report.outcome == "applied"
    assert w.recaps.rows[OCC].practiced_by("maya") == (GRIP,)


async def test_unmarked_and_voided_children_are_aliased_from_the_class_roster() -> None:
    w = World(template_session_id="tmpl-1")
    interpreter = Interpreter(None)
    roster = Roster()
    await w.submit(interpreter, roster).execute(
        _report("Zoe Ng and Vic did grip drills with Leo."), LEAD_ACTOR
    )
    assert interpreter.calls[0]["text"] == "S6 and S5 did grip drills with S2."
    assert roster.asked == ["tmpl-1"]  # enrollments live on the recurring template


@pytest.mark.parametrize(
    "roster",
    [
        Roster({**FULL, "zoe": " "}),  # a roster child with no name on file
        Roster({k: v for k, v in FULL.items() if k != "sam"}),  # a marked child off the roster
    ],
)
async def test_report_stays_with_the_owner_when_a_child_cannot_be_aliased(roster: Roster) -> None:
    w = World()
    interpreter = Interpreter(SPLIT)
    report = await w.submit(interpreter, roster).execute(_report(SPLIT_TEXT), LEAD_ACTOR)
    assert report.outcome == "sent_to_owner" and interpreter.calls == []
    assert [
        r.report_id for r in await ListOpenClassReportHandoffs(reports=w.reports).execute()
    ] == ["r-1"]


async def test_lower_case_first_name_is_asked_not_guessed() -> None:
    w = World()
    interpreter = Interpreter(SPLIT)
    roster = Roster({**FULL, "zoe": "Will Ng"})
    report = await w.submit(interpreter, roster).execute(
        _report("Leo will drill smashes next week."), LEAD_ACTOR
    )
    assert report.outcome == "needs_clarification" and interpreter.calls == []
    assert any('"will"' in q for q in report.questions)
    capital = await w.submit(interpreter, roster).execute(
        _report("Will did grip drills.", "r-2"), LEAD_ACTOR
    )
    assert capital.ai_used and interpreter.calls[0]["text"] == "S6 did grip drills."


class BlockingInterpreter(Interpreter):
    def __init__(self, facts: ReportFacts | None) -> None:
        super().__init__(facts)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def interpret(self, **kwargs: Any) -> ReportFacts | None:
        self.calls.append(kwargs)
        self.entered.set()
        await self.release.wait()
        return self.facts


async def test_concurrent_submits_of_one_report_call_the_model_once() -> None:
    w = World()
    interpreter = BlockingInterpreter(SPLIT)
    first = asyncio.create_task(w.submit(interpreter).execute(_report(SPLIT_TEXT), LEAD_ACTOR))
    await interpreter.entered.wait()
    with pytest.raises(RecapConflict) as busy:
        await w.submit(interpreter).execute(_report(SPLIT_TEXT), LEAD_ACTOR)
    assert busy.value.details.get("processing") is True
    # Still being read: not an owner handoff yet.
    assert await ListOpenClassReportHandoffs(reports=w.reports).execute() == []
    interpreter.release.set()
    done = await first
    assert done.outcome == "applied" and len(interpreter.calls) == 1
    assert w.reports.rows["r-1"].processing_until is None
    assert await w.submit(interpreter).execute(_report(SPLIT_TEXT), LEAD_ACTOR) == done


class FailingInterpreter(Interpreter):
    async def interpret(self, **kwargs: Any) -> ReportFacts | None:
        self.calls.append(kwargs)
        raise RuntimeError("provider dropped the connection")


async def test_a_failed_read_leaves_the_report_with_the_owner_and_replays_without_ai() -> None:
    w = World()
    interpreter = FailingInterpreter(None)
    with pytest.raises(RuntimeError):
        await w.submit(interpreter).execute(_report(SPLIT_TEXT), LEAD_ACTOR)
    stored = w.reports.rows["r-1"]
    assert stored.outcome == "sent_to_owner" and stored.processing_until is None
    assert stored.text == SPLIT_TEXT  # the coach's words are kept
    again = await w.submit(interpreter).execute(_report(SPLIT_TEXT), LEAD_ACTOR)
    assert again == stored and len(interpreter.calls) == 1


async def test_an_interrupted_read_is_settled_on_replay_without_calling_the_model() -> None:
    w = World()
    interpreter = Interpreter(SPLIT)
    # A crash after the recap was saved but before the report was finished.
    await w.submit(interpreter).execute(_report(SPLIT_TEXT), LEAD_ACTOR)
    w.reports.rows["r-1"] = w.reports.rows["r-1"].model_copy(
        update={"outcome": "sent_to_owner", "applied_revision": None, "processing_until": NOW}
    )
    later = NOW + timedelta(minutes=10)
    applied = await w.submit(interpreter, now=later).execute(_report(SPLIT_TEXT), LEAD_ACTOR)
    assert applied.outcome == "applied" and applied.applied_revision == 1
    assert len(interpreter.calls) == 1
    # A crash before anything was applied: the owner has it.
    await w.reports.insert(
        w.reports.rows["r-1"].model_copy(
            update={"report_id": "r-2", "outcome": "sent_to_owner", "processing_until": NOW}
        )
    )
    owned = await w.submit(interpreter, now=later).execute(_report(SPLIT_TEXT, "r-2"), LEAD_ACTOR)
    assert owned.outcome == "sent_to_owner" and owned.processing_until is None
    assert len(interpreter.calls) == 1


# --- owner handoff ---------------------------------------------------------


async def test_owner_finds_and_closes_handoffs() -> None:
    w = World()
    await w.submit(Interpreter(None)).execute(_report("Grips.", use_ai=False), LEAD_ACTOR)
    handoffs = ListOpenClassReportHandoffs(reports=w.reports)
    assert [r.report_id for r in await handoffs.execute()] == ["r-1"]
    resolve = ResolveClassReport(reports=w.reports, clock=lambda: NOW)
    with pytest.raises(RecapWriteForbidden):
        await resolve.execute(OCC, "r-1", LEAD_ACTOR)
    with pytest.raises(RecapNotAllowed):
        await resolve.execute("occ-other", "r-1", OWNER_ACTOR)
    closed = await resolve.execute(OCC, "r-1", OWNER_ACTOR)
    assert closed.resolved_by == OWNER and await handoffs.execute() == []
    assert (await resolve.execute(OCC, "r-1", OWNER_ACTOR)).resolved_at == NOW


# --- ListChildClassRecaps ---------------------------------------------------


async def test_parent_view_is_own_child_only_with_passes_from_the_pipeline() -> None:
    w = World()
    await w.save.execute(
        _cmd(taught_skill_ids=[GRIP, SMASH], practice=_practice(maya=[GRIP], leo=[SMASH])),
        LEAD_ACTOR,
    )
    passes = Passes({"maya": {GRIP}, "leo": {SMASH}})
    maya = await w.child(passes).execute("maya")
    assert [_skills(r.taught_skills) for r in maya] == [
        [(GRIP, "Forehand grip", True), (SMASH, "Jump smash", False)]
    ]
    assert _skills(maya[0].practiced_skills) == [(GRIP, "Forehand grip", True)]
    leo = await w.child(passes).execute("leo")
    assert _skills(leo[0].practiced_skills) == [(SMASH, "Jump smash", True)]
    # Present but credited with nothing: sees the class, no practice.
    sam = await w.child(passes).execute("sam")
    assert sam[0].practiced_skills == [] and not any(s.passed for s in sam[0].taught_skills)
    assert await w.child(passes).execute("ana") == []  # absent: not their class


async def test_a_report_pass_claim_is_never_a_parent_visible_pass() -> None:
    w = World()
    await w.submit(Interpreter(SPLIT)).execute(_report(SPLIT_TEXT), LEAD_ACTOR)
    row = (await w.child(Passes()).execute("maya"))[0]
    assert not any(s.passed for s in (*row.taught_skills, *row.practiced_skills))


def _skills(rows: Any) -> list[tuple[str, str, bool]]:
    return [(s.skill_id, s.name, s.passed) for s in rows]


def _store(
    w: World, occ: str, *, taught: tuple[str, ...], practice: tuple[ChildPractice, ...] = ()
) -> None:
    w.recaps.rows[occ] = ClassRecap(
        recap_id=f"rc-{occ}",
        academy_id=ACADEMY,
        occurrence_id=occ,
        session_id=SESSION,
        class_starts_at=NOW,
        taught_skill_ids=taught,
        practice=practice,
        revision=1,
        updated_by=LEAD,
        updated_at=NOW,
    )


async def test_parent_pass_mark_follows_the_skill_id_not_a_shared_name() -> None:
    """Two levels can each hold a 'Forehand grip'; passing one must not mark the other."""
    w = World()
    twin = "skill-l2-grip"
    _store(w, OCC, taught=(twin,), practice=tuple(_practice(maya=[twin])))

    class TwinCatalog(Catalog):
        async def names(self, skill_ids: list[str], *, active_only: bool) -> dict[str, str]:
            return {sid: "Forehand grip" for sid in skill_ids if sid in {GRIP, twin}}

    listing = ListChildClassRecaps(
        recaps=w.recaps,
        attendance=w.attendance,
        skills=TwinCatalog(),
        passes=Passes({"maya": {GRIP}}),
    )
    row = (await listing.execute("maya"))[0]
    assert _skills(row.taught_skills) == [(twin, "Forehand grip", False)]


async def test_parent_list_reads_names_and_passes_once_for_all_recaps() -> None:
    w = World()
    for occ in ("occ-a", "occ-b", "occ-c"):
        _store(w, occ, taught=(GRIP, SMASH))
    calls: list[str] = []

    class CountingCatalog(Catalog):
        async def names(self, skill_ids: list[str], *, active_only: bool) -> dict[str, str]:
            calls.append("names")
            return await super().names(skill_ids, active_only=active_only)

    class CountingPasses(Passes):
        async def passed(self, student_id: str, skill_ids: list[str]) -> set[str]:
            calls.append("passed")
            return await super().passed(student_id, skill_ids)

    class AllPresent:
        async def confirmed_occurrence_ids(self, student_id: str, *, limit: int) -> list[str]:
            return ["occ-a", "occ-b", "occ-c"]

    rows = await ListChildClassRecaps(
        recaps=w.recaps, attendance=AllPresent(), skills=CountingCatalog(), passes=CountingPasses()
    ).execute("maya")
    assert len(rows) == 3 and sorted(calls) == ["names", "passed"]


async def test_attendance_correction_withdraws_the_class_from_the_parent() -> None:
    w = World()
    await w.save.execute(_cmd(), LEAD_ACTOR)
    assert len(await w.child().execute("maya")) == 1
    w.attendance.marks["maya"] = "absent"
    assert await w.child().execute("maya") == []
