"""Progress settings (Settings > Curriculum) and the milestone records (L5B).

``UpdateProgressSettings`` is the owner/admin save: validated through the
model, written as one targeted ``$set``, audited when something changed. A
threshold that was already configured keeps its ``since``; a new one starts
now, and turning milestones back on restarts every ``since``, so a change only
ever applies going forward.

``RecordReachedMilestones`` evaluates one student against the settings and
records each milestone reached (insert-once per student and key) before
returning that student's records for the thresholds still configured. With
milestones off it reads nothing and returns nothing, so every consumer (the
parent journey, the evening email) stays silent. Skills count only real
passes (silent placement credits are left out) and levels count issued
certificates, so a placement that closes a level never counts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.student_progress.application.ports import (
    CertificateRepository,
    MilestoneRepository,
    ProgressAuditLog,
    ProgressSettingsStore,
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
        # Re-enabling restarts the clock: nothing reached while off is celebrated.
        restart = cmd.milestones_enabled and not current.milestones_enabled
        kept = {} if restart else {m.key: m.since for m in current.milestones}
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
        certificates: CertificateRepository,
        milestones: MilestoneRepository,
    ) -> None:
        self._settings = settings
        self._skills = skill_progress
        self._certs = certificates
        self._milestones = milestones

    async def execute(self, student_id: str) -> list[StudentMilestone]:
        settings = await self._settings.get()
        if not settings.milestones_enabled or not settings.milestones:
            return []
        passed = await self._skills.list_passed_for_student(student_id)
        # Issued certificates only: one per level earned through a level-up.
        certs = await self._certs.list_for_student(student_id)
        for milestone in reached_milestones(
            settings,
            student_id=student_id,
            passed_at=[row.last_updated_at for row in passed],
            completed_at=[cert.completed_at for cert in certs],
        ):
            await self._milestones.record(milestone)
        # A removed threshold's records stay on file but are not shown.
        configured = {m.key for m in settings.milestones}
        return [
            m
            for m in await self._milestones.list_for_student(student_id)
            if m.milestone_key in configured
        ]
