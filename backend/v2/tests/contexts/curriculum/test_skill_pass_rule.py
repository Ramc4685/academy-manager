"""Per-skill pass rule on the curriculum Skill (lane L5, slice A2)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from backend.v2.contexts.curriculum.application.use_cases.manage_skills import (
    UpdateSkill,
    UpdateSkillCommand,
)
from backend.v2.contexts.curriculum.domain.models import Skill
from pydantic import ValidationError

AT = datetime(2026, 11, 2, tzinfo=UTC)


def _skill(**kw: Any) -> Skill:
    base: dict[str, Any] = {
        "skill_id": "s1",
        "level_id": "L1",
        "program_id": "p",
        "academy_id": "a",
        "sequence": 1,
        "name": "Grip",
        "created_at": AT,
        "updated_at": AT,
        "created_by": "owner",
    }
    return Skill(**{**base, **kw})


def test_rule_defaults_and_tries_follow_the_rule() -> None:
    assert (_skill().pass_rule, _skill().pass_tries) == ("ONE_TAP", None)
    assert _skill(pass_rule="N_TRIES").pass_tries == 3
    assert _skill(pass_rule="LEAD_COACH", pass_tries=5).pass_tries is None
    with pytest.raises(ValidationError):
        _skill(pass_rule="N_TRIES", pass_tries=11)


class _Skills:
    def __init__(self, skill: Skill) -> None:
        self.skill = skill

    async def get(self, skill_id: str) -> Skill | None:
        return self.skill

    async def update(self, skill: Skill) -> None:
        self.skill = skill


@pytest.mark.asyncio
async def test_update_revalidates_the_merged_skill() -> None:
    repo = _Skills(_skill(pass_rule="N_TRIES", pass_tries=4))
    use_case = UpdateSkill(skills=repo)  # type: ignore[arg-type]

    back_to_one = await use_case.execute(
        UpdateSkillCommand(skill_id="s1", pass_rule="ONE_TAP", updated_by="owner")
    )
    assert back_to_one.pass_tries is None
    n = await use_case.execute(
        UpdateSkillCommand(skill_id="s1", pass_rule="N_TRIES", updated_by="owner")
    )
    assert n.pass_tries == 3
