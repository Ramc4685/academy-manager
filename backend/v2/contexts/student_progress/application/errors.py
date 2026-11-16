"""Student progress application-layer error re-exports.

Interface layer imports from here (allowed) rather than domain.errors (forbidden).
"""

from backend.v2.contexts.student_progress.domain.errors import (
    ActiveRecommendationExists,
    CertificateAlreadyRevoked,
    CertificateNotFound,
    LevelNotConfigured,
    LevelUpInProgress,
    LevelUpNotReady,
    MasteryNoteClosed,
    OverrideNotPermitted,
    PassNeedsLeadCoach,
    RecommendationAlreadyReviewed,
    RecommendationNotFound,
    SkillAlreadyPassed,
    SkillNotOnCurrentLevel,
    SkillProgressNotFound,
    StudentNotFound,
    StudentNotPlaced,
)
from backend.v2.contexts.student_progress.domain.models import ProgressNextAction

__all__ = [
    "ActiveRecommendationExists",
    "CertificateAlreadyRevoked",
    "CertificateNotFound",
    "LevelNotConfigured",
    "LevelUpInProgress",
    "LevelUpNotReady",
    "MasteryNoteClosed",
    "OverrideNotPermitted",
    "PassNeedsLeadCoach",
    "ProgressNextAction",
    "RecommendationAlreadyReviewed",
    "RecommendationNotFound",
    "SkillAlreadyPassed",
    "SkillNotOnCurrentLevel",
    "SkillProgressNotFound",
    "StudentNotFound",
    "StudentNotPlaced",
]
