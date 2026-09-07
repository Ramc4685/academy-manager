"""Student progress domain errors."""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class StudentNotPlaced(DomainError):
    code = "StudentProgress.StudentNotPlaced"
    status_code = 404


class SkillProgressNotFound(DomainError):
    code = "StudentProgress.SkillProgressNotFound"
    status_code = 404


class SkillAlreadyPassed(DomainError):
    code = "StudentProgress.SkillAlreadyPassed"
    status_code = 409


class LevelUpNotReady(DomainError):
    code = "StudentProgress.LevelUpNotReady"
    status_code = 409


class RecommendationNotFound(DomainError):
    code = "StudentProgress.RecommendationNotFound"
    status_code = 404


class RecommendationAlreadyReviewed(DomainError):
    code = "StudentProgress.RecommendationAlreadyReviewed"
    status_code = 409


class OverrideNotPermitted(DomainError):
    code = "StudentProgress.OverrideNotPermitted"
    status_code = 403


class ActiveRecommendationExists(DomainError):
    code = "StudentProgress.ActiveRecommendationExists"
    status_code = 409


class LevelNotConfigured(DomainError):
    code = "StudentProgress.LevelNotConfigured"
    status_code = 422


class EnrollmentEnded(DomainError):
    """The student no longer has a live (active or paused) enrollment (#673).

    Raised on recommend and on approve: a withdrawn or cancelled student must
    not be advanced or certified. Reject stays allowed so the admin can clear
    the row.
    """

    code = "StudentProgress.EnrollmentEnded"
    status_code = 409
