"""B4 parent progress narrative: gate order, what the model sees, strict
parse, the coach-review switch, approval stamping and the evening wins swap."""

from __future__ import annotations

import importlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import mongomock_motor
import pytest

from backend.v2.composition.ai import PlatformAiEntitlement
from backend.v2.composition.ai_narratives import AcademyCoachReviewSwitch, _StudentNarrativeFacts
from backend.v2.composition.evening_wins import _ParentWinsProvider
from backend.v2.contexts.ai.application.use_cases.draft_progress_narrative import (
    DraftProgressNarrative,
    ProgressNarrativeInput,
    SkillMasteredToday,
    parse_narrative,
)
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.application.use_cases.student_narratives import (
    DraftStudentNarrative,
    ReviewNarratives,
)
from backend.v2.contexts.ai.domain.errors import (
    AiDisabled,
    AiMonthlyCapReached,
    AiNotEntitled,
    AiProviderError,
)
from backend.v2.contexts.ai.domain.models import DEFAULT_MODEL, AiCallRecord, LlmResult
from backend.v2.contexts.ai.domain.narrative import (
    COACH_REVIEW_OFF,
    AiNarrative,
    NoWinsToday,
    source_fingerprint,
)
from backend.v2.contexts.ai.domain.prompts import PROMPTS
from backend.v2.contexts.ai.infrastructure.disabled_llm_port import DisabledLlmPort
from backend.v2.contexts.communications.application.parent_wins import (
    ChildWins,
    FamilyWins,
    SkillWins,
    render_parent_wins,
)
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.fixtures.ai_counters import counters_at

NOW = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)
START = datetime(2026, 11, 4, 0, 0, tzinfo=UTC)
END = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
INPUT = ProgressNarrativeInput(
    child_first_name="Aarav",
    level_name="Level 2",
    program_name="Badminton Pathway",
    skills_mastered_today=[
        SkillMasteredToday(
            skill_name="Forecourt movement",
            criteria=["Split step before moving", "Racket up on the way in"],
            coach_words="Nailed it today: split step before moving.",
        )
    ],
    passed_in_level=3,
    total_in_level=6,
    finished_level=False,
)
GOOD = json.dumps(
    {
        "text": "Aarav mastered Forecourt movement today, with a split step before every "
        "move. That is 3 of 6 skills in Level 2.",
        "skills_mentioned": ["Forecourt movement"],
    }
)


def _result(text: str) -> LlmResult:
    return LlmResult(
        text=text, input_tokens=50, output_tokens=40, cost_cents=1, model=DEFAULT_MODEL
    )


class FakeLlm:
    def __init__(self, text: str = GOOD) -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    async def complete(self, *, prompt_version: str, system: str, user: str, max_tokens: int):
        self.calls.append(
            {"prompt_version": prompt_version, "system": system, "user": user, "max": max_tokens}
        )
        return _result(self.text)


class FakeCalls:
    def __init__(self, used: int = 0) -> None:
        self.used = used
        self.recorded: list[AiCallRecord] = []
        self.approvers: list[tuple[str, str]] = []

    async def count_since(self, since: datetime) -> int:
        return self.used

    async def record(self, call: AiCallRecord) -> None:
        self.recorded.append(call)

    async def set_approver(self, call_id: str, approver: str) -> bool:
        self.approvers.append((call_id, approver))
        return True


class FakeCap:
    async def monthly_cap(self) -> int:
        return 2


class FakeEntitlement:
    def __init__(self, has: bool) -> None:
        self.has = has

    async def has_ai(self) -> bool:
        return self.has


def _drafter(llm: Any, calls: FakeCalls, *, entitled: bool = True) -> DraftProgressNarrative:
    return DraftProgressNarrative(
        llm=llm,
        record_ai_call=RecordAiCall(
            calls=calls,
            counters=counters_at(calls.used, NOW),
            cap_source=FakeCap(),
            clock=lambda: NOW,
        ),
        entitlement=FakeEntitlement(entitled),
    )


# --- entitlement port -------------------------------------------------------


async def test_platform_entitlement_is_false_without_has_feature_and_reads_it_when_wired():
    assert await PlatformAiEntitlement(None).has_ai() is False

    class HasFeature:
        async def execute(self, academy_id: str, feature: str) -> bool:
            assert (academy_id, feature) == ("acad-a", "ai")
            return True

    with tenant_scope("acad-a"):
        assert await PlatformAiEntitlement(HasFeature()).has_ai() is True


# --- the model call ---------------------------------------------------------


def test_prompt_entry_is_versioned_and_warns_about_untrusted_text():
    prompt = PROMPTS["progress_narrative"]
    assert prompt.version == "progress-narrative-v1"
    assert "JSON" in prompt.system_text and "untrusted" in prompt.system_text


async def test_not_entitled_is_403_before_the_cap_or_any_call():
    llm, calls = FakeLlm(), FakeCalls(used=99)
    with pytest.raises(AiNotEntitled):
        await _drafter(llm, calls, entitled=False).execute(INPUT)
    assert llm.calls == [] and calls.recorded == []


async def test_cap_reached_is_429_before_any_call():
    llm, calls = FakeLlm(), FakeCalls(used=2)
    with pytest.raises(AiMonthlyCapReached):
        await _drafter(llm, calls).execute(INPUT)
    assert llm.calls == [] and calls.recorded == []


async def test_disabled_port_passes_through_as_ai_disabled():
    calls = FakeCalls()
    with pytest.raises(AiDisabled):
        await _drafter(DisabledLlmPort(), calls).execute(INPUT)
    assert calls.recorded == []


async def test_happy_path_sends_exactly_the_input_and_records_before_returning():
    llm, calls = FakeLlm(), FakeCalls()
    draft, call = await _drafter(llm, calls).execute(INPUT)

    (sent,) = llm.calls
    assert sent["prompt_version"] == "progress-narrative-v1" and sent["max"] == 400
    assert json.loads(sent["user"]) == INPUT.model_dump()
    assert draft.text.startswith("Aarav mastered Forecourt movement")
    assert [c.feature for c in calls.recorded] == ["progress_narrative"]
    assert call.approver is None and call.call_id == calls.recorded[0].call_id


async def test_a_malformed_answer_is_still_recorded_then_502():
    llm, calls = FakeLlm("I cannot do that"), FakeCalls()
    with pytest.raises(AiProviderError):
        await _drafter(llm, calls).execute(INPUT)
    assert len(calls.recorded) == 1


@pytest.mark.parametrize(
    "raw",
    [
        # a number that is not one of the two counts
        '{"text": "Aarav did 4 drills.", "skills_mentioned": []}',
        # a skill the input never named
        '{"text": "Aarav mastered Serve today.", "skills_mentioned": ["Serve"]}',
        # claims to cite a real skill the text does not contain
        '{"text": "Great day.", "skills_mentioned": ["Forecourt movement"]}',
        # too long
        json.dumps({"text": "word " * 71, "skills_mentioned": []}),
        # extra key
        '{"text": "Great day.", "skills_mentioned": [], "mood": "x"}',
        "",
    ],
)
def test_parse_refuses_invented_numbers_skills_length_and_shape(raw: str):
    with pytest.raises(AiProviderError):
        parse_narrative(raw, INPUT)


def test_parse_strips_a_json_fence_and_collapses_whitespace():
    draft = parse_narrative(f"```json\n{GOOD}\n```", INPUT)
    assert draft.text.startswith("Aarav mastered Forecourt movement today")
    assert "  " not in draft.text


# --- what the model sees: the facts provider ------------------------------


def _row(skill_id: str, student_id: str = "s-aarav", note: str | None = None) -> Any:
    return SimpleNamespace(
        student_id=student_id, skill_id=skill_id, level_id="L2", program_id="prog", coach_note=note
    )


class _FakeProgress:
    def __init__(self, today: list[Any], done: list[Any]) -> None:
        self.today, self.done = today, done

    async def list_passed_between(self, start: datetime, end: datetime) -> list[Any]:
        return self.today

    async def list_passed_for_student_level(self, student_id: str, level_id: str) -> list[Any]:
        return self.done


class _One:
    def __init__(self, **items: Any) -> None:
        self.items = items

    async def get(self, key: str) -> Any:
        return self.items.get(key)

    async def get_by_id(self, key: str) -> Any:
        return self.items.get(key)

    async def list_for_level(self, level_id: str) -> list[Any]:
        return list(self.items.values())

    async def list_for_skill(self, skill_id: str) -> list[Any]:
        return self.items.get(skill_id, [])


FORBIDDEN = ("Raj", "raj@example.test", "555-0100", "12 Court St", "4242", "Diya", "absent")


def _facts() -> _StudentNarrativeFacts:
    student = SimpleNamespace(
        full_name="Aarav Raj",
        parent_email="raj@example.test",
        phone="555-0100",
        address="12 Court St",
        card_last4="4242",
        siblings=["Diya"],
        attendance="absent",
    )
    return _StudentNarrativeFacts(
        skill_progress=_FakeProgress(
            today=[_row("L2-3", note="Nailed it today: split step."), _row("L2-1", "s-diya")],
            done=[_row("L2-1"), _row("L2-2"), _row("L2-3")],
        ),
        skills=_One(
            **{
                f"L2-{i}": SimpleNamespace(skill_id=f"L2-{i}", name=n, is_required=True)
                for i, n in enumerate(["Grip", "Ready stance", "Forecourt movement", "Serve"], 1)
            }
        ),
        criteria=_One(**{"L2-3": [SimpleNamespace(description="Split step before moving")]}),
        levels=_One(L2=SimpleNamespace(name="Level 2")),
        programs=_One(prog=SimpleNamespace(name="Badminton Pathway")),
        students=_One(**{"s-aarav": student}),
    )


async def test_facts_carry_only_the_allowed_fields_and_the_model_message_leaks_nothing():
    facts = await _facts().facts_for("s-aarav", START, END)
    assert facts == ProgressNarrativeInput(
        child_first_name="Aarav",
        level_name="Level 2",
        program_name="Badminton Pathway",
        skills_mastered_today=[
            SkillMasteredToday(
                skill_name="Forecourt movement",
                criteria=["Split step before moving"],
                coach_words="Nailed it today: split step.",
            )
        ],
        passed_in_level=3,
        total_in_level=4,
        finished_level=False,
    )
    llm, calls = FakeLlm(GOOD.replace("3 of 6", "3 of 4")), FakeCalls()
    await _drafter(llm, calls).execute(facts)
    user = llm.calls[0]["user"]
    for fact in ("Aarav", "Level 2", "Badminton Pathway", "Forecourt movement", "Split step"):
        assert fact in user
    for secret in FORBIDDEN:
        assert secret not in user, secret
    assert set(json.loads(user)) == set(ProgressNarrativeInput.model_fields)


async def test_facts_are_none_when_the_student_mastered_nothing_that_day():
    assert await _facts().facts_for("s-kim", START, END) is None


# --- storing the draft: the coach-review switch -----------------------------


class FakeNarratives:
    def __init__(self) -> None:
        self.rows: dict[str, AiNarrative] = {}

    async def upsert_draft(self, row: AiNarrative) -> AiNarrative:
        self.rows = {
            k: v
            for k, v in self.rows.items()
            if (v.student_id, v.for_date, v.kind) != (row.student_id, row.for_date, row.kind)
        }
        self.rows[row.narrative_id] = row
        return row

    async def get(self, narrative_id: str) -> AiNarrative | None:
        return self.rows.get(narrative_id)

    async def get_for(self, student_id: str, for_date: str, kind: str) -> AiNarrative | None:
        return next(
            (
                r
                for r in self.rows.values()
                if (r.student_id, r.for_date, r.kind) == (student_id, for_date, kind)
            ),
            None,
        )

    async def list_pending(self, for_date: str, created_by: str | None) -> list[AiNarrative]:
        return [
            r
            for r in self.rows.values()
            if r.status == "pending_review"
            and r.for_date == for_date
            and (created_by is None or r.created_by == created_by)
        ]

    async def decide(self, narrative_id, *, status, text, approver, decided_at):
        row = self.rows.get(narrative_id)
        if row is None or row.status != "pending_review":
            return None
        row = row.model_copy(
            update={
                "status": status,
                "approver": approver,
                "decided_at": decided_at,
                "text": text or row.text,
            }
        )
        self.rows[narrative_id] = row
        return row


class FakeFacts:
    def __init__(self, facts: ProgressNarrativeInput | None) -> None:
        self.facts = facts

    async def facts_for(self, student_id, start, end):
        return self.facts


class FakeReview:
    def __init__(self, required: bool) -> None:
        self.required = required

    async def coach_review_required(self) -> bool:
        return self.required


def _student_drafter(review: bool, facts=INPUT):
    calls, repo = FakeCalls(), FakeNarratives()
    use_case = DraftStudentNarrative(
        facts=FakeFacts(facts),
        drafter=_drafter(FakeLlm(), calls),
        review=FakeReview(review),
        narratives=repo,
        calls=calls,
        clock=lambda: NOW,
    )
    return use_case, calls, repo


async def _draft(use_case: DraftStudentNarrative) -> AiNarrative:
    return await use_case.execute(
        student_id="s-aarav", for_date=date(2026, 11, 4), start=START, end=END, coach_id="coach-1"
    )


async def test_review_on_stores_pending_with_no_approver():
    use_case, calls, repo = _student_drafter(review=True)
    row = await _draft(use_case)
    assert (row.status, row.approver, row.decided_at) == ("pending_review", None, None)
    assert (row.for_date, row.kind, row.call_id, row.created_by) == (
        "2026-11-04",
        "evening_wins",
        calls.recorded[0].call_id,
        "coach-1",
    )
    assert calls.approvers == [] and list(repo.rows.values()) == [row]


async def test_review_off_stores_approved_and_stamps_coach_review_off_on_both_rows():
    use_case, calls, _repo = _student_drafter(review=False)
    row = await _draft(use_case)
    assert (row.status, row.approver, row.decided_at) == ("approved", COACH_REVIEW_OFF, NOW)
    assert calls.approvers == [(row.call_id, COACH_REVIEW_OFF)]
    assert row.call_id == calls.recorded[0].call_id


async def test_no_wins_that_day_is_409_without_a_model_call():
    use_case, calls, _ = _student_drafter(review=True, facts=None)
    with pytest.raises(NoWinsToday):
        await _draft(use_case)
    assert calls.recorded == []


async def test_a_second_draft_replaces_the_day_s_row():
    use_case, _, repo = _student_drafter(review=True)
    first = await _draft(use_case)
    second = await _draft(use_case)
    assert first.narrative_id != second.narrative_id and list(repo.rows) == [second.narrative_id]


# --- the coach's decision ----------------------------------------------------


async def test_approving_with_edits_stamps_the_coach_on_the_row_and_the_ai_call():
    use_case, calls, repo = _student_drafter(review=True)
    row = await _draft(use_case)
    review = ReviewNarratives(narratives=repo, calls=calls, clock=lambda: NOW)

    decided = await review.decide(
        row.narrative_id, status="approved", text="Aarav moved so well today.", approver="coach-1"
    )

    assert decided is not None
    assert (decided.status, decided.approver, decided.text, decided.decided_at) == (
        "approved",
        "coach-1",
        "Aarav moved so well today.",
        NOW,
    )
    assert calls.approvers == [(row.call_id, "coach-1")]
    assert await review.pending(date(2026, 11, 4), "coach-1") == []
    # Already decided: nothing to decide again.
    assert await review.decide(row.narrative_id, status="rejected", text=None, approver="x") is None


async def test_rejecting_leaves_the_ai_call_unapproved():
    use_case, calls, repo = _student_drafter(review=True)
    row = await _draft(use_case)
    review = ReviewNarratives(narratives=repo, calls=calls, clock=lambda: NOW)
    decided = await review.decide(
        row.narrative_id, status="rejected", text=None, approver="coach-1"
    )
    assert decided is not None and (decided.status, decided.approver) == ("rejected", None)
    assert calls.approvers == []


class FakeAcademies:
    def __init__(self, doc: dict | None) -> None:
        self.doc = doc

    async def find_by_id(self, academy_id: str) -> dict | None:
        return self.doc


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        (None, True),
        ({"ai": {}}, True),
        ({"ai": {"coach_review_narratives": "no"}}, True),
        ({"ai": {"coach_review_narratives": False}}, False),
        ({"ai": {"coach_review_narratives": True}}, True),
    ],
)
async def test_coach_review_switch_defaults_on(doc: dict | None, expected: bool):
    with tenant_scope("acad-a"):
        assert (
            await AcademyCoachReviewSwitch(FakeAcademies(doc)).coach_review_required() is expected
        )


# --- migration 0224 ----------------------------------------------------------


_M0224 = importlib.import_module("backend.v2.migrations.0224_ai_narratives")


async def test_migration_0224_builds_the_indexes_and_rerun_is_a_no_op():
    assert _M0224.version == "0224_ai_narratives"
    db: Any = mongomock_motor.AsyncMongoMockClient()["test"]
    await _M0224.up(db)
    await _M0224.up(db)
    info = await db["ai_narratives"].index_information()
    unique = info["ai_narratives_academy_student_date_kind_unique"]
    assert unique["key"] == [("academy_id", 1), ("student_id", 1), ("for_date", 1), ("kind", 1)]
    assert unique["unique"] is True
    assert info["ai_narratives_academy_status"]["key"] == [("academy_id", 1), ("status", 1)]
    calls = await db["ai_calls"].index_information()
    assert calls["ai_calls_academy_call_id"]["key"] == [("academy_id", 1), ("call_id", 1)]
    for _collection, _name, keys, _options in _M0224.INDEXES:
        assert keys[0] == ("academy_id", 1)


# --- the evening wins email ----------------------------------------------------


def _family(narrative: str) -> FamilyWins:
    return FamilyWins(
        parent_id="p1",
        children=(
            ChildWins(
                first_name="Aarav",
                progress_url="https://x/parent/progress?child=s",
                skill_wins=(
                    SkillWins(
                        level_name="Level 2",
                        skill_names=("Forecourt movement",),
                        passed_in_level=3,
                        total_in_level=6,
                        coach_notes=("Split step every time.",),
                    ),
                ),
                narrative=narrative,
            ),
        ),
    )


def test_render_uses_an_approved_narrative_instead_of_the_templated_sentence():
    subject, body = render_parent_wins(_family("Aarav moved so well today, 3 of 6 done."))
    assert subject == "Aarav mastered Forecourt movement today"
    assert "Aarav moved so well today, 3 of 6 done." in body
    assert "Aarav mastered Forecourt movement today. That" not in body
    assert "Coach: “Split step every time.”" in body
    assert "See Aarav" in body


def test_render_without_a_narrative_keeps_the_templated_sentence():
    _, body = render_parent_wins(_family(""))
    assert "Aarav mastered Forecourt movement today. That&#x27;s 3 of 6 skills in Level 2" in body


def test_render_keeps_every_level_s_templated_lines_when_wins_span_two_levels():
    family = _family("Aarav moved so well today, 3 of 6 done.")
    child = family.children[0]
    other = SkillWins(
        level_name="Level 3",
        skill_names=("Smash",),
        passed_in_level=1,
        total_in_level=5,
        coach_notes=(),
    )
    two = replace(family, children=(replace(child, skill_wins=(*child.skill_wins, other)),))
    _, body = render_parent_wins(two)
    assert "Aarav moved so well today" not in body
    assert "Aarav mastered Forecourt movement today." in body
    assert "Aarav mastered Smash today." in body


# --- the fingerprint: an approved paragraph only while the wins still match ----


def test_fingerprint_is_order_free_and_moves_with_the_wins():
    skills = [("Serve", None), ("Forecourt movement", "Split step.")]
    same = source_fingerprint(reversed(skills), 3, 6)
    assert source_fingerprint(skills, 3, 6) == same
    assert source_fingerprint([("Serve", "")], 3, 6) == source_fingerprint([("Serve", None)], 3, 6)
    assert source_fingerprint(skills[1:], 2, 6) != same
    assert source_fingerprint(skills, 3, 7) != same


async def test_draft_stores_the_fingerprint_of_the_facts_it_was_built_from():
    use_case, _, _ = _student_drafter(review=True)
    row = await _draft(use_case)
    assert row.source_fingerprint == source_fingerprint(
        [("Forecourt movement", "Nailed it today: split step before moving.")], 3, 6
    )


class _ApprovedNarratives:
    def __init__(self, row: AiNarrative) -> None:
        self.row = row

    async def approved_for(self, student_ids, for_date, kind):
        return {self.row.student_id: self.row}


class _Empty:
    async def list_issued_between(self, start, end):
        return []

    async def find_by_id(self, key):
        return {}


def _provider(today: list[Any], narrative: AiNarrative) -> _ParentWinsProvider:
    skills = {
        f"L2-{i}": SimpleNamespace(skill_id=f"L2-{i}", name=n, is_required=True)
        for i, n in enumerate(["Grip", "Ready stance", "Forecourt movement", "Serve"], 1)
    }
    student = SimpleNamespace(student_id="s-aarav", full_name="Aarav Raj", parent_id="p1")

    class _Students:
        async def by_ids(self, ids):
            return [student]

    return _ParentWinsProvider(
        skill_progress=_FakeProgress(today=today, done=[_row("L2-1"), *today]),
        certificates=_Empty(),
        students=_Students(),
        skills=_One(**skills),
        levels=_One(L2=SimpleNamespace(name="Level 2")),
        academies=_Empty(),
        narratives=_ApprovedNarratives(narrative),
    )


async def test_evening_wins_use_the_approved_paragraph_only_while_its_wins_still_stand():
    today = [_row("L2-3", note="Split step."), _row("L2-4")]
    approved = AiNarrative(
        narrative_id="n1",
        student_id="s-aarav",
        for_date="2026-11-04",
        kind="evening_wins",
        text="Aarav flew across the court today.",
        status="approved",
        approver="coach-1",
        prompt_version="progress-narrative-v1",
        created_by="coach-1",
        created_at=NOW,
        source_fingerprint=source_fingerprint(
            [("Forecourt movement", "Split step."), ("Serve", None)], 3, 4
        ),
    )
    with tenant_scope("acad-a"):
        [family] = await _provider(today, approved).families_with_wins(START, END)
        assert family.children[0].narrative == "Aarav flew across the court today."
        # The coach undid the Serve tap after approving: the paragraph is stale.
        [family] = await _provider(today[:1], approved).families_with_wins(START, END)
    child = family.children[0]
    assert child.narrative == ""
    assert child.skill_wins[0].skill_names == ("Forecourt movement",)
    assert "mastered Forecourt movement today" in render_parent_wins(family)[1]
