"""Curriculum use cases: external lesson reference management.

IMPORTANT: References map skills to external curriculum sources (e.g. BWF Shuttle Time).
They store only metadata — source name, module, lesson range, short title, page hint,
and an internal note. They must NEVER contain copied lesson body text or drill descriptions.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from backend.v2.contexts.curriculum.application.ports import ExternalRefRepository, SkillRepository
from backend.v2.contexts.curriculum.domain.errors import SkillNotFound
from backend.v2.contexts.curriculum.domain.models import ExternalLessonReference, ExternalSource
from backend.v2.shared.ids import new_ulid


class AddExternalReferenceCommand(BaseModel):
    model_config = {"frozen": True}
    skill_id: str
    source: ExternalSource
    source_title: str
    module_name: str
    lesson_range: str
    reference_title: str
    page_hint: str | None = None
    internal_note: str = ""
    created_by: str


class AddExternalReference:
    def __init__(self, *, skills: SkillRepository, refs: ExternalRefRepository) -> None:
        self._skills = skills
        self._refs = refs

    async def execute(self, cmd: AddExternalReferenceCommand) -> ExternalLessonReference:
        skill = await self._skills.get(cmd.skill_id)
        if skill is None:
            raise SkillNotFound("skill not found", skill_id=cmd.skill_id)
        ref = ExternalLessonReference(
            ref_id=str(new_ulid()),
            skill_id=cmd.skill_id,
            academy_id="",  # injected by repo
            source=cmd.source,
            source_title=cmd.source_title,
            module_name=cmd.module_name,
            lesson_range=cmd.lesson_range,
            reference_title=cmd.reference_title,
            page_hint=cmd.page_hint,
            internal_note=cmd.internal_note,
            created_at=datetime.now(UTC),
            created_by=cmd.created_by,
        )
        await self._refs.save(ref)
        return ref
