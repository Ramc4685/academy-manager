"""Curriculum domain errors."""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class ProgramNotFound(DomainError):
    code = "Curriculum.ProgramNotFound"
    status_code = 404


class NoActiveProgram(DomainError):
    code = "Curriculum.NoActiveProgram"
    status_code = 404


class MultipleActivePrograms(DomainError):
    code = "Curriculum.MultipleActivePrograms"
    status_code = 409


class LevelNotFound(DomainError):
    code = "Curriculum.LevelNotFound"
    status_code = 404


class SkillNotFound(DomainError):
    code = "Curriculum.SkillNotFound"
    status_code = 404


class DuplicateSequence(DomainError):
    code = "Curriculum.DuplicateSequence"
    status_code = 409


class PathwayAlreadySeeded(DomainError):
    code = "Curriculum.AlreadySeeded"
    status_code = 409
