"""Curriculum application-layer error re-exports.

Interface layer imports from here (allowed) rather than domain.errors (forbidden).
"""

from backend.v2.contexts.curriculum.domain.errors import (
    ActiveProgramExists,
    DuplicateSequence,
    LevelNotFound,
    MultipleActivePrograms,
    NoActiveProgram,
    PathwayAlreadySeeded,
    ProgramNotFound,
    SkillNotFound,
)

__all__ = [
    "ActiveProgramExists",
    "DuplicateSequence",
    "LevelNotFound",
    "MultipleActivePrograms",
    "NoActiveProgram",
    "PathwayAlreadySeeded",
    "ProgramNotFound",
    "SkillNotFound",
]
