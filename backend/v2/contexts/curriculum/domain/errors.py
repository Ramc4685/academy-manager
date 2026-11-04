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


class ActiveProgramExists(DomainError):
    """Only one active skill program per tenant is supported (#968).

    Coach, digest and student surfaces resolve "the" program via
    ``ResolveDefaultActiveProgram``, which fails on a second active one.
    """

    code = "Curriculum.ActiveProgramExists"
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
