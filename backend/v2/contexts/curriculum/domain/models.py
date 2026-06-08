"""Curriculum domain models — programs, levels, skills, criteria, external references."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

LevelCompletionRule = Literal["ALL_REQUIRED_SKILLS", "POINTS_BASED", "COACH_APPROVAL_ONLY"]
ScoringType = Literal[
    "ATTEMPT_BASED",
    "CHECKLIST_BASED",
    "COACH_APPROVAL",
    "RALLY_COUNT",
    "TIME_BASED",
    "POINTS_BASED",
]
ExternalSource = Literal["BWF_SHUTTLE_TIME", "ACADEMY_CUSTOM", "COACH_CREATED"]


class Program(BaseModel):
    model_config = {"frozen": True}

    program_id: str
    academy_id: str
    sport: str
    name: str
    description: str = ""
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    created_by: str


class Level(BaseModel):
    model_config = {"frozen": True}

    level_id: str
    program_id: str
    academy_id: str
    sequence: int = Field(ge=1)
    name: str
    description: str = ""
    completion_rule: LevelCompletionRule = "ALL_REQUIRED_SKILLS"
    points_threshold: int | None = None
    requires_coach_recommendation: bool = True
    requires_admin_approval: bool = False
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    created_by: str


class Skill(BaseModel):
    model_config = {"frozen": True}

    skill_id: str
    level_id: str
    program_id: str
    academy_id: str
    sequence: int = Field(ge=1)
    name: str
    description: str = ""
    is_required: bool = True
    scoring_type: ScoringType = "ATTEMPT_BASED"
    pass_threshold_pct: float = Field(default=70.0, ge=0.0, le=100.0)
    coach_override_allowed: bool = False
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    created_by: str


class SkillCriterion(BaseModel):
    model_config = {"frozen": True}

    criterion_id: str
    skill_id: str
    level_id: str
    program_id: str
    academy_id: str
    description: str
    display_order: int = Field(ge=0)
    created_at: datetime
    created_by: str


class ExternalLessonReference(BaseModel):
    """Reference-only record mapping a skill to an external curriculum source.

    IMPORTANT: This record must NEVER contain copied lesson body text,
    drill descriptions, or any verbatim content from the external source.
    Store only: source identifier, module name, lesson range, short title,
    page hint, and an internal note for the academy's own mapping rationale.
    """

    model_config = {"frozen": True}

    ref_id: str
    skill_id: str
    academy_id: str
    source: ExternalSource
    source_title: str
    module_name: str
    lesson_range: str
    reference_title: str
    page_hint: str | None = None
    internal_note: str = ""
    created_at: datetime
    created_by: str


class PathwayLevel(BaseModel):
    """Read model: level with its skills and criteria, for the pathway tree."""

    model_config = {"frozen": True}

    level: Level
    skills: list[SkillWithCriteria]


class SkillWithCriteria(BaseModel):
    model_config = {"frozen": True}

    skill: Skill
    criteria: list[SkillCriterion]
    external_refs: list[ExternalLessonReference]


class FullPathway(BaseModel):
    model_config = {"frozen": True}

    program: Program
    levels: list[PathwayLevel]
