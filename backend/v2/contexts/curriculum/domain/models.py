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


LessonResourceKind = Literal["YOUTUBE", "PDF_REFERENCE"]
VideoRefScope = Literal["LEVEL", "SKILL"]


class LessonResourceLink(BaseModel):
    """A single resource link attached to a lesson card.

    LICENSING: A ``PDF_REFERENCE`` link is a citation chip only — ``url`` is
    always ``None`` and the title carries the manual/module/lesson/page
    citation. We never host, link, or attach the Shuttle Time PDF. A
    ``YOUTUBE`` link points at a publicly hosted video/playlist URL.
    """

    model_config = {"frozen": True}

    kind: LessonResourceKind
    title: str
    url: str | None = None


class LessonCard(BaseModel):
    """Original-wording teaching card mapping one lesson to a level + skills.

    Unlike :class:`ExternalLessonReference` (pointer-only), a LessonCard DOES
    carry teaching content — but every word must be ORIGINAL academy wording.
    It must NEVER contain text copied verbatim from BWF Shuttle Time or any
    other source. The ``source``/``module_name``/``lesson_range``/``page_hint``
    fields are citation metadata only; ``resource_links`` of kind
    ``PDF_REFERENCE`` carry ``url=None`` (citation chip, never a hosted file).
    """

    model_config = {"frozen": True}

    card_id: str
    academy_id: str
    program_id: str
    level_id: str
    skill_ids: list[str] = Field(default_factory=list)
    slug: str
    lesson_number: int = Field(ge=1)
    title: str
    goal_summary: str = ""
    teaching_points: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    activity_summary: str = ""
    safety_notes: list[str] = Field(default_factory=list)
    source: ExternalSource = "BWF_SHUTTLE_TIME"
    module_name: str = ""
    lesson_range: str = ""
    page_hint: str | None = None
    resource_links: list[LessonResourceLink] = Field(default_factory=list)
    content_hash: str = ""
    display_order: int = Field(default=0, ge=0)
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    created_by: str


class CurriculumVideoRef(BaseModel):
    """Curated YouTube reference at level or skill granularity.

    Pointer-only: stores a short academy-authored title and a public video/
    playlist URL. No copied transcript or lesson text.
    """

    model_config = {"frozen": True}

    ref_id: str
    academy_id: str
    program_id: str
    scope: VideoRefScope
    level_id: str
    skill_id: str | None = None
    title: str
    url: str
    display_order: int = Field(default=0, ge=0)
    content_hash: str = ""
    is_active: bool = True
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
