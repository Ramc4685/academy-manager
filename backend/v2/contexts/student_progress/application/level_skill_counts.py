"""Project earned progress onto the current curriculum for coach and parent views."""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from backend.v2.contexts.student_progress.domain.models import SkillStatus


class LevelSkillCounts(BaseModel):
    model_config = {"frozen": True}
    required_passed: int
    required_total: int
    optional_passed: int
    optional_total: int

    @property
    def required_complete(self) -> bool:
        return self.required_total > 0 and self.required_passed == self.required_total


def count_level_skills(
    skills: Sequence[object], statuses: Mapping[str, SkillStatus]
) -> LevelSkillCounts:
    required = {str(getattr(s, "skill_id", "")) for s in skills if getattr(s, "is_required", True)}
    optional = {
        str(getattr(s, "skill_id", "")) for s in skills if not getattr(s, "is_required", True)
    }
    passed = {skill_id for skill_id, status in statuses.items() if status == "PASSED"}
    return LevelSkillCounts(
        required_passed=len(required & passed),
        required_total=len(required),
        optional_passed=len(optional & passed),
        optional_total=len(optional),
    )
