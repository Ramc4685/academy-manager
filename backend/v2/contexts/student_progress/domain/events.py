"""Student progress domain events."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from backend.v2.shared.events.base import DomainEvent


class StudentPlacedInLevelPayload(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    program_id: str
    level_id: str
    progress_id: str
    placed_by: str
    reason: str


class StudentPlacedInLevel(DomainEvent):
    name: Literal["StudentProgress.StudentPlacedInLevel"] = "StudentProgress.StudentPlacedInLevel"
    schema_version: Literal[1] = 1
    payload: StudentPlacedInLevelPayload


class SkillStatusUpdatedPayload(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    skill_id: str
    level_id: str
    old_status: str
    new_status: str
    updated_by: str


class SkillStatusUpdated(DomainEvent):
    name: Literal["StudentProgress.SkillStatusUpdated"] = "StudentProgress.SkillStatusUpdated"
    schema_version: Literal[1] = 1
    payload: SkillStatusUpdatedPayload


class SkillTestAttemptedPayload(BaseModel):
    model_config = {"frozen": True}
    attempt_id: str
    student_id: str
    skill_id: str
    level_id: str
    program_id: str
    coach_id: str
    attempts_count: int
    success_count: int
    score: float
    passed: bool


class SkillTestAttempted(DomainEvent):
    name: Literal["StudentProgress.SkillTestAttempted"] = "StudentProgress.SkillTestAttempted"
    schema_version: Literal[1] = 1
    payload: SkillTestAttemptedPayload


class SkillPassedPayload(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    skill_id: str
    level_id: str
    program_id: str
    coach_id: str
    attempt_id: str


class SkillPassed(DomainEvent):
    name: Literal["StudentProgress.SkillPassed"] = "StudentProgress.SkillPassed"
    schema_version: Literal[1] = 1
    payload: SkillPassedPayload


class LevelCompletedPayload(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    level_id: str
    program_id: str
    progress_id: str


class LevelCompleted(DomainEvent):
    name: Literal["StudentProgress.LevelCompleted"] = "StudentProgress.LevelCompleted"
    schema_version: Literal[1] = 1
    payload: LevelCompletedPayload


class LevelUpRecommendedPayload(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    from_level_id: str
    to_level_id: str
    program_id: str
    rec_id: str
    recommended_by: str


class LevelUpRecommended(DomainEvent):
    name: Literal["StudentProgress.LevelUpRecommended"] = "StudentProgress.LevelUpRecommended"
    schema_version: Literal[1] = 1
    payload: LevelUpRecommendedPayload


class StudentLeveledUpPayload(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    from_level_id: str
    to_level_id: str
    program_id: str
    new_progress_id: str
    cert_id: str | None


class StudentLeveledUp(DomainEvent):
    name: Literal["StudentProgress.StudentLeveledUp"] = "StudentProgress.StudentLeveledUp"
    schema_version: Literal[1] = 1
    payload: StudentLeveledUpPayload


class CertificateIssuedPayload(BaseModel):
    model_config = {"frozen": True}
    cert_id: str
    cert_number: str
    student_id: str
    level_id: str
    program_id: str
    issued_by: str


class CertificateIssued(DomainEvent):
    name: Literal["StudentProgress.CertificateIssued"] = "StudentProgress.CertificateIssued"
    schema_version: Literal[1] = 1
    payload: CertificateIssuedPayload
