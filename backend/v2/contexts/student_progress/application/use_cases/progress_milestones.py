"""Progress settings (Settings > Curriculum) and the milestone records (L5B).

``UpdateProgressSettings`` is the owner/admin save: validated through the
model, written as one targeted ``$set``, audited when something changed. A
threshold that was already configured keeps its ``since``; a new one starts
now, so a change only ever applies going forward.

``RecordReachedMilestones`` evaluates one student against the settings and
records each milestone reached (insert-once per student and key) before
returning that student's records. With milestones off it reads nothing and
returns nothing, so every consumer (the parent journey, the evening email)
stays silent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.student_progress.application.ports import (
    MilestoneRepository,
    ProgressAuditLog,
    ProgressSettingsStore,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.milestones import (
    MAX_MILESTONE_COUNT,
    MAX_MILESTONES,
    MilestoneThreshold,
    ProgressSettings,
    StudentMilestone,
    milestone_key,
    reached_milestones,
)

__all__ = [
    "MAX_MILESTONES",
    "MAX_MILESTONE_COUNT",
    "GetProgressSettings",
    "ProgressSettings",
    "RecordReachedMilestones",
    "UpdateProgressSettings",
    "UpdateProgressSettingsCommand",
]


def _audit_view(settings: ProgressSettings) -> dict[str, Any]:
    return {
        "milestones_enabled": settings.milestones_enabled,
        "milestones": [m.key for m in settings.milestones],
        "share_name": settings.share_name,
    }


class GetProgressSettings:
    def __init__(self, *, settings: ProgressSettingsStore) -> None:
        self._settings = settings

    async def execute(self) -> ProgressSettings:
        return await self._settings.get()


@dataclass(frozen=True)
class UpdateProgressSettingsCommand:
    actor_id: str
    milestones_enabled: bool
    #: ``(kind, count)`` pairs as the form sends them.
    milestones: list[tuple[str, int]]
    share_name: str


class UpdateProgressSettings:
    def __init__(
        self,
        *,
        settings: ProgressSettingsStore,
        audit: ProgressAuditLog,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._audit = audit
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(self, cmd: UpdateProgressSettingsCommand) -> ProgressSettings:
        current = await self._settings.get()
        now = self._now()
        kept = {m.key: m.since for m in current.milestones}
        # Raises pydantic ValidationError on a bad kind, count, duplicate or size.
        updated = ProgressSettings(
            milestones_enabled=cmd.milestones_enabled,
            milestones=[
                MilestoneThreshold(
                    kind=kind,
                    count=count,
                    since=kept.get(milestone_key(kind, count), now),
                )
                for kind, count in cmd.milestones
            ],
            share_name=cmd.share_name,
        )
        before, after = _audit_view(current), _audit_view(updated)
        if before == after:
            return current
        await self._settings.set(updated)
        await self._audit.record(
            audit_id=f"progress_settings.changed:{now.isoformat()}",
            action="progress_settings.changed",
            actor_id=cmd.actor_id,
            entity_type="progress_settings",
            entity_id="progress_settings",
            before=before,
            after=after,
            at=now,
        )
        return updated


class RecordReachedMilestones:
    def __init__(
        self,
        *,
        settings: ProgressSettingsStore,
        skill_progress: StudentSkillProgressRepository,
        level_progress: StudentLevelProgressRepository,
        milestones: MilestoneRepository,
    ) -> None:
        self._settings = settings
        self._skills = skill_progress
        self._levels = level_progress
        self._milestones = milestones

    async def execute(self, student_id: str) -> list[StudentMilestone]:
        settings = await self._settings.get()
        if not settings.milestones_enabled or not settings.milestones:
            return []
        passed = await self._skills.list_passed_for_student(student_id)
        levels = await self._levels.list_for_student(student_id)
        for milestone in reached_milestones(
            settings,
            student_id=student_id,
            passed_at=[row.last_updated_at for row in passed],
            completed_at=[
                lvl.completed_at
                for lvl in levels
                if lvl.status == "completed" and lvl.completed_at is not None
            ],
        ):
            await self._milestones.record(milestone)
        return await self._milestones.list_for_student(student_id)
