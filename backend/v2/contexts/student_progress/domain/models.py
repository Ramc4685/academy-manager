"""Student progress domain models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SkillStatus = Literal[
    "NOT_STARTED",
    "INTRODUCED",
    "LEARNING",
    "PRACTICING",
    "TEST_READY",
    "PASSED",
    "NEEDS_REVIEW",
]

LevelUpStatus = Literal[
    "NOT_READY",
    "READY",
    "RECOMMENDED",
    "APPROVED",
    "REJECTED",
    "COMPLETED",
]

LevelProgressStatus = Literal["active", "completed", "withdrawn"]


class StudentLevelProgress(BaseModel):
    """Tracks which level a student is on for a program."""

    model_config = {"frozen": True}

    progress_id: str
    academy_id: str
    student_id: str
    program_id: str
    level_id: str
    status: LevelProgressStatus = "active"
    started_at: datetime
    completed_at: datetime | None = None
    created_at: datetime


class StudentSkillProgress(BaseModel):
    """Tracks the status of a single skill for a student."""

    model_config = {"frozen": True}

    skill_progress_id: str
    academy_id: str
    student_id: str
    skill_id: str
    level_id: str
    program_id: str
    status: SkillStatus = "NOT_STARTED"
    introduced_at: datetime | None = None
    last_updated_at: datetime
    last_updated_by: str


class TestAttempt(BaseModel):
    """One recorded test of a skill for a student."""

    model_config = {"frozen": True}

    attempt_id: str
    academy_id: str
    student_id: str
    skill_id: str
    level_id: str
    program_id: str
    session_id: str | None = None
    occurrence_id: str | None = None
    coach_id: str
    scoring_type: str  # mirrors ScoringType from curriculum
    attempts_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    score: float = Field(ge=0.0, le=100.0)
    passed: bool
    coach_override: bool = False
    override_reason: str | None = None
    notes: str = ""
    tested_at: datetime


class LevelUpRecommendation(BaseModel):
    """Coach recommendation + admin approval for a student level-up."""

    model_config = {"frozen": True}

    rec_id: str
    academy_id: str
    student_id: str
    from_level_id: str
    to_level_id: str
    program_id: str
    status: LevelUpStatus = "RECOMMENDED"
    recommended_by: str
    recommended_at: datetime
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None


class SkillCertificate(BaseModel):
    """Certificate issued when a student completes a level."""

    model_config = {"frozen": True}

    cert_id: str
    academy_id: str
    student_id: str
    program_id: str
    level_id: str
    cert_number: str
    student_name: str
    level_name: str
    program_name: str
    completed_at: datetime
    issued_by: str
    issued_at: datetime


# ---------------------------------------------------------------------------
# Read models used by BFF responses
# ---------------------------------------------------------------------------


class StudentProgressSummary(BaseModel):
    """Aggregated progress for one student in one program."""

    model_config = {"frozen": True}

    student_id: str
    program_id: str
    program_name: str
    current_level_id: str | None
    current_level_name: str | None
    current_level_sequence: int | None
    total_skills: int
    passed_skills: int
    in_progress_skills: int
    not_started_skills: int
    level_up_status: LevelUpStatus | None
    certificates: list[SkillCertificate]


class SkillPassportEntry(BaseModel):
    """One skill entry in the student's passport view."""

    model_config = {"frozen": True}

    skill_id: str
    skill_name: str
    skill_description: str
    sequence: int
    is_required: bool
    status: SkillStatus
    last_test_passed: bool | None
    last_tested_at: datetime | None
    test_attempt_count: int
