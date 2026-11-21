"""Review regressions for the report gate: name aliasing, negation and
taught-only wording, missed group exclusions, skill grounding, model
question limits, and archived skills kept on later saves."""

from __future__ import annotations

import pytest

from backend.v2.contexts.ai.application.use_cases.interpret_class_report import (
    MAX_QUESTIONS,
    UNMATCHED,
    ClassReportInput,
    ClassReportReading,
    ReadPass,
    ReportSkillRow,
    ground,
)
from backend.v2.contexts.coaching.domain.class_recap import (
    PassStatement,
    PracticeClaim,
    ReportFacts,
    RosterName,
    TaughtClaim,
    _grounded_skill,
    alias_report,
    first_name,
)
from backend.v2.contexts.coaching.domain.errors import RecapInvalid
from backend.v2.tests.unit.test_class_recap import (
    GRIP,
    LEAD_ACTOR,
    OCC,
    OLD,
    World,
    _cmd,
    _recap,
    _resolve,
)

SKILLS = [(GRIP, "Forehand grip")]


def _ids(resolved) -> list[str]:
    return [row.student_id for row in resolved.practice]


def _roster(**names: str) -> list[RosterName]:
    return [RosterName(student_id=sid, full_name=name) for sid, name in names.items()]


# --- aliasing --------------------------------------------------------------


def test_identical_full_names_are_asked_and_never_aliased() -> None:
    roster = _roster(m1="Maya Lopez", m2="maya  lopez")
    aliased = alias_report("Maya Lopez did grips.", roster, SKILLS)
    assert aliased.questions == (
        "More than one student is named Maya Lopez. Record them on the recap form instead.",
    )
    assert "S1" not in aliased.text and "S2" not in aliased.text and "Maya" not in aliased.text


def test_hyphenated_first_name_is_not_split_by_a_shorter_name() -> None:
    roster = _roster(mj="Mary-Jane Smith", m="Mary Smith")
    aliased = alias_report("Mary-Jane did grips.", roster, SKILLS)
    assert aliased.questions == ()
    assert aliased.text == "S2 did grips." and aliased.student_aliases["S2"] == "mj"


def test_nameless_student_has_no_stand_in_alias_word() -> None:
    assert first_name("  ") == ""
    roster = _roster(x="", m="Maya Lopez")
    aliased = alias_report("Every student did grips.", roster, SKILLS)
    assert aliased.text == "Every student did grips." and aliased.questions == ()


@pytest.mark.parametrize("text", ["S1 did grips.", "Maya did k2 today."])
def test_coach_typed_alias_codes_are_refused(text: str) -> None:
    roster = _roster(m="Maya Lopez")
    assert alias_report(text, roster, SKILLS).questions == (
        "Write students' and skills' names, not codes like S1.",
    )


# --- negation, taught-only, exclusions -------------------------------------


def test_taught_only_wording_never_becomes_practice() -> None:
    claim = "showed everyone the jump smash"
    facts = ReportFacts(
        taught=(TaughtClaim(skills=("K2",), evidence=claim),),
        practice=(PracticeClaim(who="group", skills=("K2",), evidence=claim),),
    )
    resolved = _resolve("Today I showed everyone the jump smash.", facts)
    assert resolved.practice == () and resolved.taught_skill_ids == ()
    assert any("only taught" in q for q in resolved.questions)


def _group(evidence: str) -> ReportFacts:
    return ReportFacts(practice=(PracticeClaim(who="group", skills=("K1",), evidence=evidence),))


def _listed(alias: str, evidence: str) -> PracticeClaim:
    return PracticeClaim(who="listed", students=(alias,), skills=("K1",), evidence=evidence)


@pytest.mark.parametrize(
    ("text", "facts"),
    [
        (
            "We did not get to grips.",
            ReportFacts(taught=(TaughtClaim(skills=("K1",), evidence="get to grips"),)),
        ),
        ("Everyone will do grips next week.", _group("Everyone will do grips")),
        ("Not everyone practised grips.", _group("everyone practised grips")),
    ],
)
def test_negated_sentences_are_questions_not_records(text: str, facts: ReportFacts) -> None:
    resolved = _resolve(text, facts)
    assert resolved.questions and resolved.taught_skill_ids == () and resolved.practice == ()


@pytest.mark.parametrize(
    ("text", "evidence"),
    [
        ("Everyone except Leo did grips.", "Everyone except S2 did grips"),
        ("Leo sat out. Everyone did grips.", "Everyone did grips"),
    ],
)
def test_group_claim_never_credits_an_excluded_child_the_reading_forgot(
    text: str, evidence: str
) -> None:
    resolved = _resolve(text, _group(evidence))
    assert resolved.questions == ()
    assert _ids(resolved) == ["maya", "sam"]  # leo held back; ana absent


def test_listing_a_child_who_sat_out_elsewhere_is_a_question() -> None:
    facts = ReportFacts(practice=(_listed("S2", "Later S2 did grips"),))
    resolved = _resolve("Leo sat out the warm-up. Later Leo did grips.", facts)
    assert resolved.questions and resolved.practice == ()


def test_including_and_excluding_the_same_child_is_a_question() -> None:
    facts = ReportFacts(
        practice=(
            PracticeClaim(
                who="group",
                except_students=("S2",),
                skills=("K1",),
                evidence="Everyone except S2 did grips",
            ),
            _listed("S2", "S2 did grips too"),
        )
    )
    resolved = _resolve("Everyone except Leo did grips. Leo did grips too.", facts)
    assert resolved.questions == (
        "The report both includes and leaves out Leo for Forehand grip. Which is right?",
    )
    assert resolved.practice == ()


def test_negated_pass_is_dropped() -> None:
    facts = ReportFacts(
        practice=(PracticeClaim(who="group", skills=("K1",), evidence="Everyone did grips"),),
        passes=(PassStatement(student="S3", skill="K1", evidence="S3 did not pass her grip"),),
    )
    resolved = _resolve("Maya did not pass her grip. Everyone did grips.", facts)
    assert resolved.questions == () and resolved.pass_claims == ()
    assert _ids(resolved) == ["leo", "sam"]  # maya is in a negated sentence


# --- skill grounding -------------------------------------------------------

CATALOG: list[str] = [
    "Low serve",
    "Kick serve",
    "Follow through",
    "Forehand clear",
    "Backhand clear",
    "Scissor jump",
    "Jump smash",
    "Smash",
]


@pytest.mark.parametrize(
    ("name", "evidence", "grounded"),
    [
        ("Low serve", "nice follow through", False),  # "low" inside "follow"
        ("Low serve", "I observed the grips", False),  # "serve" inside "observed"
        ("Low serve", "low serves", True),
        ("Forehand clear", "forehand clears", True),
        ("Backhand clear", "forehand clears", False),  # adjacent skill
        ("Forehand clear", "lots of clears", False),  # shared word: ambiguous
        ("Scissor jump", "scissor kicks", True),
        ("Kick serve", "scissor kicks", False),
        ("Jump smash", "scissor kick", False),
        ("Jump smash", "jump smashes", True),
        ("Smash", "jump smashes", False),  # part of the longer skill
        ("Smash", "smashes", True),
    ],
)
def test_skill_grounding_uses_whole_words_and_unambiguous_phrases(
    name: str, evidence: str, grounded: bool
) -> None:
    assert _grounded_skill(name, evidence, CATALOG) is grounded


# --- model questions -------------------------------------------------------


def test_model_questions_are_capped_and_never_show_codes() -> None:
    data = ClassReportInput(
        report="S1 did grips.",
        students=["S1"],
        skills=[ReportSkillRow(alias="K1", name="Forehand grip")],
    )
    reading = ClassReportReading(
        passes=[ReadPass(student="S9", skill="K1", evidence="S9 passed")],
        questions=["Was K1 done\nby S9?", "Did S1 do K1?", "q3", "q4", "q5", "q6", "q7"],
    )
    grounded = ground(reading, data)
    assert len(grounded.questions) == MAX_QUESTIONS
    assert grounded.questions[:3] == [
        UNMATCHED,
        "Was Forehand grip done by a student?",
        "Did S1 do Forehand grip?",
    ]


# --- save keeps history ----------------------------------------------------


async def test_save_keeps_an_archived_skill_already_on_the_recap() -> None:
    w = World()
    w.recaps.rows[OCC] = _recap(taught_skill_ids=(GRIP, OLD))
    saved = await w.save.execute(
        _cmd(mutation_id="m-2", expected_revision=1, taught_skill_ids=[GRIP, OLD]), LEAD_ACTOR
    )
    assert saved.taught_skill_ids == (GRIP, OLD) and saved.revision == 2
    # Newly adding an archived skill is still refused.
    w.recaps.rows[OCC] = _recap(taught_skill_ids=(GRIP,))
    with pytest.raises(RecapInvalid):
        await w.save.execute(
            _cmd(mutation_id="m-3", expected_revision=1, taught_skill_ids=[GRIP, OLD]), LEAD_ACTOR
        )
