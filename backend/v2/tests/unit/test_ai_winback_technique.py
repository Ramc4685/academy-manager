"""B6: win-back wording and text-only technique observations.

Pins the Track B rules for both paid features: entitlement -> cap -> model ->
record -> strict parse, the exact facts the model sees, the owner's standing
approval on the win-back notifier, and the composition reads behind them.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.v2.composition.ai import PlatformAiEntitlement
from backend.v2.composition.ai_technique import StudentProgressTechniqueCandidates
from backend.v2.composition.ai_win_back import AcademyAiWinBackSetting, StudentProgressWinBackFacts
from backend.v2.composition.win_back import WinBackNotificationAdapter
from backend.v2.contexts.ai.application.use_cases.draft_technique_observation import (
    DraftTechniqueObservation,
    DraftTechniqueObservationForStudent,
    TechniqueCandidate,
    TechniqueFacts,
    TechniqueNoCandidates,
    TechniqueObservationInput,
)
from backend.v2.contexts.ai.application.use_cases.draft_win_back_note import (
    DraftWinBackNote,
    PersonaliseWinBackParagraph,
    WinBackNoteInput,
    WinBackRecentWin,
)
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import (
    AiDisabled,
    AiMonthlyCapReached,
    AiNotEntitled,
    AiProviderError,
)
from backend.v2.contexts.ai.domain.models import DEFAULT_MODEL, AiCallRecord, LlmResult
from backend.v2.contexts.ai.domain.prompts import PROMPTS
from backend.v2.contexts.communications.application.ports import ResolvedRecipient, SendOutcome
from backend.v2.contexts.identity.domain.errors import AcademyNotFound
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.fixtures.ai_counters import counters_at

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
OWNER = "owner-ulid"
SURNAME = "Vasquez-Okonkwo"
PARENT_EMAIL = "pat.vasquez@example.test"
PHONE = "+1 309 555 0100"
DEPARTURE_REASON = "moved to the rival club after a billing dispute"
SIBLING = "Theo"


def _result(text: str) -> LlmResult:
    return LlmResult(text=text, input_tokens=10, output_tokens=5, cost_cents=1, model=DEFAULT_MODEL)


class FakeLlm:
    def __init__(self, answer: str | Exception) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    async def complete(self, *, prompt_version: str, system: str, user: str, max_tokens: int):
        self.calls.append(
            {"prompt_version": prompt_version, "system": system, "user": user, "max": max_tokens}
        )
        if isinstance(self.answer, Exception):
            raise self.answer
        return _result(self.answer)


class FakeCalls:
    def __init__(self, used: int = 0) -> None:
        self.used = used
        self.recorded: list[AiCallRecord] = []
        self.counted = 0

    async def count_since(self, since: datetime) -> int:
        self.counted += 1
        return self.used

    async def record(self, call: AiCallRecord) -> None:
        self.recorded.append(call)


class FakeCap:
    async def monthly_cap(self) -> int:
        return 2


class Entitled:
    def __init__(self, value: bool = True) -> None:
        self.value = value

    async def has_ai(self) -> bool:
        return self.value


def _record(calls: FakeCalls) -> RecordAiCall:
    return RecordAiCall(
        calls=calls, counters=counters_at(calls.used, NOW), cap_source=FakeCap(), clock=lambda: NOW
    )


WIN_BACK_INPUT = WinBackNoteInput(
    child_first_name="Maya",
    milestone_days=30,
    level_name="Shuttle Starter",
    recent_wins=[WinBackRecentWin(skill_name="Forehand serve", when="2026-09")],
    academy_name="Alpha Shuttle Club",
)
GOOD_PARAGRAPH = (
    "Maya was flying through Shuttle Starter, and her forehand serve was a real win. "
    "Thirty days on, the court at Alpha Shuttle Club still has her spot."
)


# ---------------------------------------------------------------------------
# Entitlement port (step 0)
# ---------------------------------------------------------------------------


async def test_platform_entitlement_without_has_feature_is_false() -> None:
    assert await PlatformAiEntitlement(None).has_ai() is False


async def test_platform_entitlement_asks_has_feature_for_the_scoped_academy() -> None:
    seen: list[tuple[str, str]] = []

    class HasFeature:
        async def execute(self, academy_id: str, feature: str) -> bool:
            seen.append((academy_id, feature))
            return True

    with tenant_scope("acad-a"):
        assert await PlatformAiEntitlement(HasFeature()).has_ai() is True
    assert seen == [("acad-a", "ai")]


# ---------------------------------------------------------------------------
# DraftWinBackNote
# ---------------------------------------------------------------------------


async def test_win_back_not_entitled_is_403_before_cap_or_model() -> None:
    llm, calls = FakeLlm(json.dumps({"paragraph": GOOD_PARAGRAPH})), FakeCalls()
    use_case = DraftWinBackNote(llm=llm, record_ai_call=_record(calls), entitlement=Entitled(False))
    with pytest.raises(AiNotEntitled) as exc:
        await use_case.execute(WIN_BACK_INPUT, approver=OWNER)
    assert exc.value.status_code == 403 and exc.value.code == "Ai.NotEntitled"
    assert calls.counted == 0 and llm.calls == [] and calls.recorded == []


async def test_win_back_cap_refuses_before_the_model_is_called() -> None:
    llm, calls = FakeLlm(json.dumps({"paragraph": GOOD_PARAGRAPH})), FakeCalls(used=2)
    use_case = DraftWinBackNote(llm=llm, record_ai_call=_record(calls), entitlement=Entitled())
    with pytest.raises(AiMonthlyCapReached):
        await use_case.execute(WIN_BACK_INPUT, approver=OWNER)
    assert llm.calls == [] and calls.recorded == []


async def test_win_back_disabled_port_propagates_and_records_nothing() -> None:
    calls = FakeCalls()
    use_case = DraftWinBackNote(
        llm=FakeLlm(AiDisabled("off")), record_ai_call=_record(calls), entitlement=Entitled()
    )
    with pytest.raises(AiDisabled):
        await use_case.execute(WIN_BACK_INPUT, approver=OWNER)
    assert calls.recorded == []


async def test_win_back_success_records_the_call_with_the_owner_as_approver() -> None:
    llm, calls = FakeLlm(f"```json\n{json.dumps({'paragraph': GOOD_PARAGRAPH})}\n```"), FakeCalls()
    use_case = DraftWinBackNote(llm=llm, record_ai_call=_record(calls), entitlement=Entitled())
    draft = await use_case.execute(WIN_BACK_INPUT, approver=OWNER)
    assert draft.paragraph == GOOD_PARAGRAPH
    assert llm.calls[0]["prompt_version"] == PROMPTS["win_back_note"].version == "win-back-note-v1"
    assert llm.calls[0]["system"] == PROMPTS["win_back_note"].system_text
    assert llm.calls[0]["max"] == 400
    record = calls.recorded[0]
    assert (record.feature, record.prompt_version, record.approver) == (
        "win_back_note",
        "win-back-note-v1",
        OWNER,
    )


@pytest.mark.parametrize(
    "answer",
    [
        "not json at all",
        json.dumps({"paragraph": GOOD_PARAGRAPH, "extra": 1}),
        json.dumps({"paragraph": " ".join(["Maya"] * 81)}),
        json.dumps({"paragraph": "Come back soon, we miss you in class."}),  # no first name
        json.dumps(
            {"paragraph": "Maya left 30 days ago; classes cost 45 dollars."}
        ),  # stray digits
        json.dumps({"paragraph": "Maya, see https://example.test for the schedule."}),
        json.dumps({"paragraph": "Maya, visit www.example.test to re-enroll."}),
        json.dumps({"paragraph": "Maya, write to coach@example.test any time."}),
        json.dumps({"paragraph": "Maya, visit example.com to re-enroll."}),  # bare domain
    ],
)
async def test_win_back_malformed_answer_is_502_after_recording(answer: str) -> None:
    calls = FakeCalls()
    use_case = DraftWinBackNote(
        llm=FakeLlm(answer), record_ai_call=_record(calls), entitlement=Entitled()
    )
    with pytest.raises(AiProviderError) as exc:
        await use_case.execute(WIN_BACK_INPUT, approver=OWNER)
    assert exc.value.status_code == 502
    assert len(calls.recorded) == 1  # tokens were spent, so the row exists


async def test_win_back_model_sees_exactly_the_allowed_facts() -> None:
    llm = FakeLlm(json.dumps({"paragraph": GOOD_PARAGRAPH}))
    use_case = DraftWinBackNote(
        llm=llm, record_ai_call=_record(FakeCalls()), entitlement=Entitled()
    )
    await use_case.execute(WIN_BACK_INPUT, approver=OWNER)
    assert json.loads(llm.calls[0]["user"]) == {
        "child_first_name": "Maya",
        "milestone_days": 30,
        "level_name": "Shuttle Starter",
        "recent_wins": [{"skill_name": "Forehand serve", "when": "2026-09"}],
        "academy_name": "Alpha Shuttle Club",
    }


def test_win_back_input_refuses_anything_beyond_the_allowed_facts() -> None:
    with pytest.raises(ValueError):
        WinBackNoteInput(**WIN_BACK_INPUT.model_dump(), parent_email=PARENT_EMAIL)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        WinBackNoteInput(**{**WIN_BACK_INPUT.model_dump(), "milestone_days": 45})
    with pytest.raises(ValueError):
        WinBackNoteInput(
            **{
                **WIN_BACK_INPUT.model_dump(),
                "recent_wins": [{"skill_name": "x", "when": "2026-09"}] * 4,
            }
        )


# ---------------------------------------------------------------------------
# PersonaliseWinBackParagraph + the notifier (the standing approval)
# ---------------------------------------------------------------------------


class Setting:
    def __init__(self, enabled: bool, by: str | None = OWNER) -> None:
        self.value = (enabled, by if enabled else None)

    async def get(self) -> tuple[bool, str | None]:
        return self.value


class Facts:
    async def facts(self, student_id: str) -> tuple[str | None, list[WinBackRecentWin]]:
        return "Shuttle Starter", [WinBackRecentWin(skill_name="Forehand serve", when="2026-09")]


class Academies:
    """Seeded with everything the model must never see."""

    async def get_academy_name(self, academy_id: str) -> str | None:
        return "Alpha Shuttle Club"

    async def find_by_id(self, academy_id: str) -> dict[str, Any]:
        return {
            "academy_id": academy_id,
            "display_name": "Alpha Shuttle Club",
            "email_reply_to": PARENT_EMAIL,
            "phone": PHONE,
        }


class Students:
    async def by_ids(self, ids: list[str]) -> list[Any]:
        return [
            SimpleNamespace(
                full_name=f"Maya {SURNAME}",
                parent_email=PARENT_EMAIL,
                phone=PHONE,
                departure_reason=DEPARTURE_REASON,
                siblings=[SIBLING],
            )
        ]


class OneParentAudience:
    async def resolve_selected_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return [
            ResolvedRecipient(user_id="parent-1", email=PARENT_EMAIL, display_name=f"Pat {SURNAME}")
        ]


class SpySender:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> SendOutcome:
        self.calls.append(kwargs)
        return SendOutcome(ok=True, provider_message_id="m-1", failed_reason=None)


def _personaliser(*, enabled: bool, llm: FakeLlm, calls: FakeCalls, entitled: bool = True):
    return PersonaliseWinBackParagraph(
        setting=Setting(enabled),
        facts=Facts(),
        academies=Academies(),
        draft=DraftWinBackNote(
            llm=llm, record_ai_call=_record(calls), entitlement=Entitled(entitled)
        ),
        academy_id=lambda: "acad-a",
    )


def _adapter(personaliser: Any) -> tuple[WinBackNotificationAdapter, SpySender]:
    sender = SpySender()
    adapter = WinBackNotificationAdapter(
        audiences=OneParentAudience(),
        students=Students(),
        sender=sender,  # type: ignore[arg-type]
        academies=Academies(),
        personaliser=personaliser,
    )
    return adapter, sender


async def _send(adapter: WinBackNotificationAdapter, days: int = 30) -> None:
    with tenant_scope("acad-a"):
        await adapter.win_back(
            student_id="stu-1", parent_id="parent-1", milestone_days=days, dropped_at=NOW
        )


def _paragraphs(body: str) -> list[str]:
    return [p.split(">", 1)[1].rsplit("</p>", 1)[0] for p in body.split("<p ") if p]


TEMPLATE_SECOND = "We would love to have them back whenever you're ready to re-enroll."


async def test_setting_off_sends_the_template_and_never_calls_the_model() -> None:
    llm, calls = FakeLlm(json.dumps({"paragraph": GOOD_PARAGRAPH})), FakeCalls()
    adapter, sender = _adapter(_personaliser(enabled=False, llm=llm, calls=calls))
    await _send(adapter)
    assert llm.calls == [] and calls.recorded == []
    paragraphs = _paragraphs(sender.calls[0]["body"])
    assert paragraphs[1] == TEMPLATE_SECOND
    assert len(paragraphs) == 3


async def test_setting_on_puts_the_ai_paragraph_second_with_the_owner_as_approver() -> None:
    llm, calls = FakeLlm(json.dumps({"paragraph": GOOD_PARAGRAPH})), FakeCalls()
    adapter, sender = _adapter(_personaliser(enabled=True, llm=llm, calls=calls))
    await _send(adapter)
    body = sender.calls[0]["body"]
    paragraphs = _paragraphs(body)
    assert paragraphs[0].startswith("It's been 30 days since <strong>Maya")
    assert paragraphs[1] == GOOD_PARAGRAPH
    assert paragraphs[2] == "If this no longer applies, you can safely ignore this message."
    assert sender.calls[0]["subject"] == f"We miss having Maya {SURNAME} in class"
    assert calls.recorded[0].approver == OWNER


async def test_model_never_sees_the_family_beyond_the_allowed_facts() -> None:
    llm = FakeLlm(json.dumps({"paragraph": GOOD_PARAGRAPH}))
    adapter, _sender = _adapter(_personaliser(enabled=True, llm=llm, calls=FakeCalls()))
    await _send(adapter, days=60)
    sent = llm.calls[0]["user"] + llm.calls[0]["system"]
    assert json.loads(llm.calls[0]["user"]) == {
        "child_first_name": "Maya",
        "milestone_days": 60,
        "level_name": "Shuttle Starter",
        "recent_wins": [{"skill_name": "Forehand serve", "when": "2026-09"}],
        "academy_name": "Alpha Shuttle Club",
    }
    for forbidden in (SURNAME, PARENT_EMAIL, PHONE, DEPARTURE_REASON, SIBLING, "parent-1", "stu-1"):
        assert forbidden not in sent


@pytest.mark.parametrize(
    ("llm", "entitled"),
    [
        (FakeLlm(AiDisabled("off")), True),
        (FakeLlm(json.dumps({"paragraph": GOOD_PARAGRAPH})), False),
        (FakeLlm(AiProviderError("down")), True),
        (FakeLlm("garbage"), True),
    ],
)
async def test_any_ai_error_falls_back_to_the_template_and_still_sends(
    llm: FakeLlm, entitled: bool, caplog: pytest.LogCaptureFixture
) -> None:
    adapter, sender = _adapter(
        _personaliser(enabled=True, llm=llm, calls=FakeCalls(), entitled=entitled)
    )
    with caplog.at_level(logging.WARNING, logger="backend.v2.composition.win_back"):
        await _send(adapter)
    assert len(sender.calls) == 1
    assert _paragraphs(sender.calls[0]["body"])[1] == TEMPLATE_SECOND
    warnings = [r for r in caplog.records if r.getMessage() == "win_back_ai_paragraph_failed"]
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING
    assert "Maya" not in caplog.text and "Shuttle Starter" not in caplog.text


async def test_wrong_schema_answer_never_reaches_the_log(caplog: pytest.LogCaptureFixture) -> None:
    marker = "MARKER-maya-forehand-serve"
    llm = FakeLlm(json.dumps({"note": marker, "level": "Shuttle Starter"}))
    adapter, sender = _adapter(_personaliser(enabled=True, llm=llm, calls=FakeCalls()))
    with caplog.at_level(logging.WARNING, logger="backend.v2.composition.win_back"):
        await _send(adapter)
    assert _paragraphs(sender.calls[0]["body"])[1] == TEMPLATE_SECOND
    [record] = [r for r in caplog.records if r.getMessage() == "win_back_ai_paragraph_failed"]
    assert record.exc_info is None
    assert record.error_type == "AiProviderError"  # type: ignore[attr-defined]
    assert record.error_code == "Ai.ProviderError"  # type: ignore[attr-defined]
    assert marker not in caplog.text and "Shuttle Starter" not in caplog.text


async def test_cap_reached_also_falls_back(caplog: pytest.LogCaptureFixture) -> None:
    llm = FakeLlm(json.dumps({"paragraph": GOOD_PARAGRAPH}))
    adapter, sender = _adapter(_personaliser(enabled=True, llm=llm, calls=FakeCalls(used=2)))
    with caplog.at_level(logging.WARNING, logger="backend.v2.composition.win_back"):
        await _send(adapter)
    assert llm.calls == []
    assert _paragraphs(sender.calls[0]["body"])[1] == TEMPLATE_SECOND
    assert "win_back_ai_paragraph_failed" in caplog.text


async def test_adapter_without_a_personaliser_is_unchanged() -> None:
    adapter, sender = _adapter(None)
    await _send(adapter)
    assert _paragraphs(sender.calls[0]["body"])[1] == TEMPLATE_SECOND


# ---------------------------------------------------------------------------
# Composition reads behind the win-back personaliser
# ---------------------------------------------------------------------------


async def test_setting_reads_and_writes_only_the_scoped_academy_document() -> None:
    db = AsyncMongoMockClient()["test_db"]
    await db["academies"].insert_many(
        [{"academy_id": "acad-a", "name": "A"}, {"academy_id": "acad-b", "name": "B"}]
    )
    setting = AcademyAiWinBackSetting(MongoAcademyRepository(db))
    with tenant_scope("acad-a"):
        assert await setting.get() == (False, None)
        assert await setting.set(enabled=True, user_id=OWNER) is True
        assert await setting.get() == (True, OWNER)
    with tenant_scope("acad-b"):
        assert await setting.get() == (False, None)
    a = await db["academies"].find_one({"academy_id": "acad-a"})
    b = await db["academies"].find_one({"academy_id": "acad-b"})
    assert a["ai"] == {"win_back_personalised": True, "win_back_personalised_by": OWNER}
    assert "ai" not in b
    with tenant_scope("acad-a"):
        await setting.set(enabled=False, user_id="someone-else")
        assert await setting.get() == (False, None)
    with tenant_scope("acad-missing"), pytest.raises(AcademyNotFound) as exc:
        await setting.set(enabled=True, user_id=OWNER)
    assert exc.value.status_code == 404
    assert await db["academies"].count_documents({}) == 2


def test_technique_composition_reports_whether_a_model_is_wired() -> None:
    from backend.v2.composition.ai import compose_ai
    from backend.v2.composition.ai_technique import compose_ai_technique

    db = AsyncMongoMockClient()["test_db"]
    off = SimpleNamespace(ai_enabled=False, anthropic_api_key=None)
    assert compose_ai_technique(db, compose_ai(db, off)).enabled is False
    key = SimpleNamespace(get_secret_value=lambda: "sk-test")
    on = SimpleNamespace(ai_enabled=True, anthropic_api_key=key)
    assert compose_ai_technique(db, compose_ai(db, on)).enabled is True


async def test_win_back_facts_use_the_active_level_and_three_passed_skills() -> None:
    def progress(skill_id: str, status: str, when: datetime) -> SimpleNamespace:
        return SimpleNamespace(skill_id=skill_id, status=status, last_updated_at=when)

    class LevelProgress:
        async def list_for_student(self, student_id: str) -> list[Any]:
            return [
                SimpleNamespace(level_id="lvl-old", status="completed"),
                SimpleNamespace(level_id="lvl-now", status="active"),
            ]

    class SkillProgress:
        async def list_recent_for_student(self, student_id: str, limit: int = 10) -> list[Any]:
            return [
                progress("s1", "PASSED", datetime(2026, 10, 2, tzinfo=UTC)),
                progress("s2", "PRACTICING", datetime(2026, 10, 1, tzinfo=UTC)),
                progress("s3", "PASSED", datetime(2026, 9, 9, tzinfo=UTC)),
                progress("s4", "PASSED", datetime(2026, 8, 9, tzinfo=UTC)),
                progress("s5", "PASSED", datetime(2026, 7, 9, tzinfo=UTC)),
            ]

    class Lookup:
        async def get_level(self, level_id: str) -> Any:
            return SimpleNamespace(name={"lvl-now": "Shuttle Starter"}[level_id])

        async def get_skill(self, skill_id: str) -> Any:
            return SimpleNamespace(name=f"Skill {skill_id}")

    facts = StudentProgressWinBackFacts(
        level_progress=LevelProgress(), skill_progress=SkillProgress(), skill_lookup=Lookup()
    )
    level_name, wins = await facts.facts("stu-1")
    assert level_name == "Shuttle Starter"
    assert [(w.skill_name, w.when) for w in wins] == [
        ("Skill s1", "2026-10"),
        ("Skill s3", "2026-09"),
        ("Skill s4", "2026-08"),
    ]


# ---------------------------------------------------------------------------
# DraftTechniqueObservation
# ---------------------------------------------------------------------------

CANDIDATES = [
    TechniqueCandidate(
        criterion_id="c-1",
        skill_id="sk-grip",
        skill_name="Forehand grip",
        description="Thumb is flat on back of handle",
    ),
    TechniqueCandidate(
        criterion_id="c-2",
        skill_id="sk-grip",
        skill_name="Forehand grip",
        description="V shape between thumb and forefinger",
    ),
    TechniqueCandidate(
        criterion_id="c-3",
        skill_id="sk-serve",
        skill_name="Low serve",
        description="Shuttle skims the net tape",
    ),
]
OBSERVATION = "Maya kept her thumb flat along the handle on every forehand today"
TECH_INPUT = TechniqueObservationInput(
    child_first_name="Maya", observation=OBSERVATION, candidate_criteria=CANDIDATES
)
GOOD_TECH = {
    "criterion_id": "c-1",
    "skill_id": "sk-grip",
    "parent_sentence": "Maya is holding the racket with a flat thumb on every forehand now.",
    "coach_summary": "Flat thumb on forehand grip, consistent.",
}


async def test_technique_gate_order_entitlement_then_cap_then_model() -> None:
    llm, calls = FakeLlm(json.dumps(GOOD_TECH)), FakeCalls()
    with pytest.raises(AiNotEntitled):
        await DraftTechniqueObservation(
            llm=llm, record_ai_call=_record(calls), entitlement=Entitled(False)
        ).execute(TECH_INPUT, approver="coach-1")
    assert calls.counted == 0 and llm.calls == []
    calls = FakeCalls(used=2)
    with pytest.raises(AiMonthlyCapReached):
        await DraftTechniqueObservation(
            llm=llm, record_ai_call=_record(calls), entitlement=Entitled()
        ).execute(TECH_INPUT, approver="coach-1")
    assert llm.calls == [] and calls.recorded == []


async def test_technique_success_records_the_coach_as_approver() -> None:
    llm, calls = FakeLlm(json.dumps(GOOD_TECH)), FakeCalls()
    draft = await DraftTechniqueObservation(
        llm=llm, record_ai_call=_record(calls), entitlement=Entitled()
    ).execute(TECH_INPUT, approver="coach-1")
    assert draft.model_dump() == GOOD_TECH
    assert llm.calls[0]["prompt_version"] == "technique-observation-v1"
    assert llm.calls[0]["max"] == 400
    assert (calls.recorded[0].feature, calls.recorded[0].approver) == (
        "technique_observation",
        "coach-1",
    )


@pytest.mark.parametrize(
    "answer",
    [
        {**GOOD_TECH, "criterion_id": "c-99"},  # not a candidate
        {**GOOD_TECH, "skill_id": "sk-serve"},  # candidate's skill does not match
        {**GOOD_TECH, "parent_sentence": "Maya did it 3 times."},  # digits
        {**GOOD_TECH, "parent_sentence": " ".join(["well"] * 41)},
        {**GOOD_TECH, "coach_summary": " ".join(["ok"] * 21)},
        {**GOOD_TECH, "extra": True},
    ],
)
async def test_technique_bad_answer_is_502_after_recording(answer: dict[str, Any]) -> None:
    calls = FakeCalls()
    with pytest.raises(AiProviderError) as exc:
        await DraftTechniqueObservation(
            llm=FakeLlm(json.dumps(answer)), record_ai_call=_record(calls), entitlement=Entitled()
        ).execute(TECH_INPUT, approver="coach-1")
    assert exc.value.status_code == 502 and len(calls.recorded) == 1


async def test_technique_model_sees_only_first_name_observation_and_candidates() -> None:
    llm = FakeLlm(json.dumps(GOOD_TECH))
    await DraftTechniqueObservation(
        llm=llm, record_ai_call=_record(FakeCalls()), entitlement=Entitled()
    ).execute(TECH_INPUT, approver="coach-1")
    assert json.loads(llm.calls[0]["user"]) == {
        "child_first_name": "Maya",
        "observation": OBSERVATION,
        "candidate_criteria": [c.model_dump() for c in CANDIDATES],
    }
    for forbidden in (SURNAME, PARENT_EMAIL, PHONE, DEPARTURE_REASON, SIBLING, "coach-1"):
        assert forbidden not in llm.calls[0]["user"]
    assert "untrusted" in llm.calls[0]["system"]
    assert "injury" in llm.calls[0]["system"]


def test_technique_input_refuses_extras_and_long_text() -> None:
    with pytest.raises(ValueError):
        TechniqueObservationInput(**TECH_INPUT.model_dump(), student_id="stu-1")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        TechniqueObservationInput(**{**TECH_INPUT.model_dump(), "observation": "x" * 501})


async def test_technique_for_student_joins_the_skill_name_and_409s_without_candidates() -> None:
    class Source:
        def __init__(self, rows: list[TechniqueCandidate]) -> None:
            self.rows = rows

        async def candidates(self, student_id: str) -> TechniqueFacts:
            return TechniqueFacts(child_first_name="Maya", candidates=self.rows)

    draft = DraftTechniqueObservation(
        llm=FakeLlm(json.dumps(GOOD_TECH)),
        record_ai_call=_record(FakeCalls()),
        entitlement=Entitled(),
    )
    suggestion = await DraftTechniqueObservationForStudent(
        source=Source(CANDIDATES), draft=draft
    ).execute(student_id="stu-1", observation=OBSERVATION, approver="coach-1")
    assert suggestion.skill_name == "Forehand grip"
    assert suggestion.criterion_id == "c-1"
    with pytest.raises(TechniqueNoCandidates) as exc:
        await DraftTechniqueObservationForStudent(source=Source([]), draft=draft).execute(
            student_id="stu-1", observation=OBSERVATION, approver="coach-1"
        )
    assert exc.value.status_code == 409


async def test_technique_candidates_strip_the_surname_and_read_the_current_level() -> None:
    class Students:
        async def by_ids(self, ids: list[str]) -> list[Any]:
            return [SimpleNamespace(full_name=f"Maya {SURNAME}", parent_email=PARENT_EMAIL)]

    class Program:
        async def execute(self) -> Any:
            return SimpleNamespace(program_id="prog-1")

    class LevelProgress:
        def __init__(self) -> None:
            self.asked: list[tuple[str, str]] = []

        async def get_active(self, student_id: str, program_id: str) -> Any:
            self.asked.append((student_id, program_id))
            return SimpleNamespace(level_id="lvl-now")

    class Lookup:
        async def list_skills_for_level(self, level_id: str) -> list[Any]:
            assert level_id == "lvl-now"
            return [SimpleNamespace(skill_id="sk-grip", name="Forehand grip")]

    class Criteria:
        async def list_for_skill(self, skill_id: str) -> list[Any]:
            return [
                SimpleNamespace(criterion_id="c-1", description="Thumb is flat on back of handle"),
                SimpleNamespace(criterion_id="c-blank", description=""),
            ]

    level_progress = LevelProgress()
    facts = await StudentProgressTechniqueCandidates(
        students=Students(),
        resolve_default_program=Program(),
        level_progress=level_progress,
        skill_lookup=Lookup(),
        criteria=Criteria(),
    ).candidates("stu-1")
    assert facts.child_first_name == "Maya"
    assert level_progress.asked == [("stu-1", "prog-1")]
    assert [c.model_dump() for c in facts.candidates] == [
        {
            "criterion_id": "c-1",
            "skill_id": "sk-grip",
            "skill_name": "Forehand grip",
            "description": "Thumb is flat on back of handle",
        }
    ]
    assert SURNAME not in json.dumps(facts.model_dump())
