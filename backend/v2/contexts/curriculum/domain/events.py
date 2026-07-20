"""Curriculum domain events."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from backend.v2.shared.events.base import DomainEvent


class ProgramCreatedPayload(BaseModel):
    model_config = {"frozen": True}
    program_id: str
    sport: str
    name: str


class ProgramCreated(DomainEvent):
    name: Literal["Curriculum.ProgramCreated"] = "Curriculum.ProgramCreated"
    schema_version: Literal[1] = 1
    payload: ProgramCreatedPayload


class LevelCreatedPayload(BaseModel):
    model_config = {"frozen": True}
    level_id: str
    program_id: str
    sequence: int
    name: str


class LevelCreated(DomainEvent):
    name: Literal["Curriculum.LevelCreated"] = "Curriculum.LevelCreated"
    schema_version: Literal[1] = 1
    payload: LevelCreatedPayload


class SkillCreatedPayload(BaseModel):
    model_config = {"frozen": True}
    skill_id: str
    level_id: str
    program_id: str
    name: str
    is_required: bool


class SkillCreated(DomainEvent):
    name: Literal["Curriculum.SkillCreated"] = "Curriculum.SkillCreated"
    schema_version: Literal[1] = 1
    payload: SkillCreatedPayload
