"""RecordClassDemonstration: a pass recorded against one dated class.

The gate is the recap's (lead, substitute or owner; started, uncancelled,
dated as read) plus present/late attendance for THIS class. The pass rules
themselves live in student_progress and are covered over real Mongo in
``tests/contract/test_class_demonstration_real_mongo.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.contexts.coaching.application.use_cases.class_recap import (
    DemonstrationOutcome,
    RecapActor,
    RecordClassDemonstration,
    RecordClassDemonstrationCommand,
)
from backend.v2.contexts.coaching.domain.errors import (
    RecapConflict,
    RecapInvalid,
    RecapNotAllowed,
    RecapWriteForbidden,
)
from backend.v2.tests.unit.test_class_recap import (
    ASSIST_ACTOR,
    GRIP,
    LEAD,
    NOW,
    OCC,
    OLD,
    OTHER,
    OWNER_ACTOR,
    SESSION,
    SMASH,
    STARTS,
    AttendanceRows,
    Catalog,
    Occurrences,
)

pytestmark = pytest.mark.asyncio

SUB = "coach-sub"


class Writer:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def record(self, **kw: Any) -> list[DemonstrationOutcome]:
        self.calls.append(kw)
        return [DemonstrationOutcome(student_id=s, outcome="mastered") for s in kw["student_ids"]]


def _use_case(writer: Writer, **occ: Any) -> RecordClassDemonstration:
    return RecordClassDemonstration(
        occurrences=Occurrences(**occ),
        attendance=AttendanceRows(),
        skills=Catalog(),
        writer=writer,
        clock=lambda: NOW,
    )


def _cmd(**kw: Any) -> RecordClassDemonstrationCommand:
    base: dict[str, Any] = {
        "occurrence_id": OCC,
        "class_starts_at": STARTS,
        "mutation_id": "m-1",
        "skill_id": SMASH,
        "student_ids": ["maya"],
    }
    return RecordClassDemonstrationCommand(**{**base, **kw})


async def test_substitute_records_a_present_child_dated_by_the_class() -> None:
    writer = Writer()
    out = await _use_case(writer, substitute_coach_id=SUB).execute(
        _cmd(student_ids=["maya", "sam", "maya"]), RecapActor(user_id=SUB)
    )
    assert [o.student_id for o in out] == ["maya", "sam"]  # late counts, duplicates once
    (call,) = writer.calls
    assert call["coach_id"] == SUB and call["can_sign_off"] is True
    # Observed on the class's own date, not whenever the entry was typed.
    assert call["observed_at"] == STARTS and call["occurrence_id"] == OCC
    assert call["session_id"] == SESSION and call["mutation_id"] == "m-1"


async def test_owner_may_record_any_class() -> None:
    writer = Writer()
    await _use_case(writer).execute(_cmd(), OWNER_ACTOR)
    assert writer.calls[0]["can_sign_off"] is True


async def test_unrelated_coach_and_unknown_class_get_nothing() -> None:
    writer = Writer()
    with pytest.raises(RecapNotAllowed):
        await _use_case(writer).execute(_cmd(), RecapActor(user_id=OTHER))
    with pytest.raises(RecapNotAllowed):
        await _use_case(writer).execute(_cmd(occurrence_id="occ-x"), OWNER_ACTOR)
    assert writer.calls == []


async def test_assistant_cannot_record_a_pass() -> None:
    writer = Writer()
    with pytest.raises(RecapWriteForbidden):
        await _use_case(writer).execute(_cmd(), ASSIST_ACTOR)
    assert writer.calls == []


@pytest.mark.parametrize("student", ["ana", "vic", "zoe"])
async def test_absent_voided_or_unmarked_children_cannot_be_credited(student: str) -> None:
    writer = Writer()
    with pytest.raises(RecapInvalid) as exc:
        await _use_case(writer).execute(
            _cmd(student_ids=["maya", student]), RecapActor(user_id=LEAD)
        )
    assert exc.value.details["student_ids"] == [student]
    assert writer.calls == []


@pytest.mark.parametrize("skill", ["skill-made-up", OLD])
async def test_unknown_or_retired_skill_is_refused(skill: str) -> None:
    writer = Writer()
    with pytest.raises(RecapInvalid):
        await _use_case(writer).execute(_cmd(skill_id=skill), RecapActor(user_id=LEAD))
    assert writer.calls == []


async def test_wrong_date_and_cancelled_class_are_refused() -> None:
    writer = Writer()
    with pytest.raises(RecapConflict):
        await _use_case(writer).execute(_cmd(class_starts_at=NOW), RecapActor(user_id=LEAD))
    with pytest.raises(Exception, match="cancelled"):
        await _use_case(writer, status="cancelled").execute(_cmd(), RecapActor(user_id=LEAD))
    assert writer.calls == []


async def test_on_level_skill_goes_through_the_same_writer() -> None:
    writer = Writer()
    await _use_case(writer).execute(_cmd(skill_id=GRIP), RecapActor(user_id=LEAD))
    assert writer.calls[0]["skill_id"] == GRIP
