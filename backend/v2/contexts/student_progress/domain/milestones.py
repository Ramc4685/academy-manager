"""Progress settings: celebration milestones and the share-page name rule (L5B).

Every value here is the academy's own: the owner sets thresholds in
Settings > Curriculum. The model defaults are "off, nothing configured";
the admin form carries its own starting values for a new row.

A milestone is reached on a deterministic instant: the time the Nth skill was
passed (or the Nth level completed), read from progress state. A threshold
only celebrates a milestone reached on or after the moment that threshold was
added (``since``), so switching one on never floods families with old news.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.v2.shared.time.mongo import ensure_utc

MilestoneKind = Literal["skills_passed", "levels_completed"]
#: How the public share page names the child: "Maya" or "M.".
ShareName = Literal["first_name", "initial"]

MAX_MILESTONES = 20
MAX_MILESTONE_COUNT = 1000


class MilestoneThreshold(BaseModel):
    model_config = {"frozen": True}

    kind: MilestoneKind
    count: int = Field(ge=1, le=MAX_MILESTONE_COUNT)
    #: When this threshold was added. Milestones reached before it are not celebrated.
    since: datetime

    @property
    def key(self) -> str:
        return milestone_key(self.kind, self.count)


class ProgressSettings(BaseModel):
    model_config = {"frozen": True}

    milestones_enabled: bool = False
    milestones: list[MilestoneThreshold] = Field(default_factory=list, max_length=MAX_MILESTONES)
    share_name: ShareName = "first_name"

    @field_validator("milestones")
    @classmethod
    def _unique(cls, value: list[MilestoneThreshold]) -> list[MilestoneThreshold]:
        keys = [m.key for m in value]
        if len(keys) != len(set(keys)):
            raise ValueError("each milestone may appear once")
        return sorted(value, key=lambda m: (m.kind, m.count))


class StudentMilestone(BaseModel):
    """One celebration a student reached; at most one row per student and key."""

    model_config = {"frozen": True}

    student_id: str
    milestone_key: str
    kind: MilestoneKind
    count: int
    reached_at: datetime


def milestone_key(kind: str, count: int) -> str:
    return f"{kind}:{count}"


def reached_milestones(
    settings: ProgressSettings,
    *,
    student_id: str,
    passed_at: list[datetime],
    completed_at: list[datetime],
) -> list[StudentMilestone]:
    """The milestones these progress timestamps reach under ``settings``."""
    if not settings.milestones_enabled:
        return []
    times = {
        "skills_passed": sorted(map(ensure_utc, passed_at)),
        "levels_completed": sorted(map(ensure_utc, completed_at)),
    }
    reached: list[StudentMilestone] = []
    for threshold in settings.milestones:
        series = times[threshold.kind]
        if len(series) < threshold.count:
            continue
        at = series[threshold.count - 1]
        if at < ensure_utc(threshold.since):
            continue
        reached.append(
            StudentMilestone(
                student_id=student_id,
                milestone_key=threshold.key,
                kind=threshold.kind,
                count=threshold.count,
                reached_at=at,
            )
        )
    return reached


def share_recipient_name(student_name: str, rule: ShareName) -> str:
    """The child's name on the public share page: first name, or its initial."""
    first = (student_name.split() or [""])[0]
    if not first:
        return "A player"
    return first if rule == "first_name" else f"{first[0].upper()}."
