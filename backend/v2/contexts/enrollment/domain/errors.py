"""Enrollment domain errors."""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class SessionNotFound(DomainError):
    code = "Enrollment.SessionNotFound"
    status_code = 404


class SessionCancelled(DomainError):
    code = "Enrollment.SessionCancelled"
    status_code = 409


class DuplicateSessionSeries(DomainError):
    code = "Enrollment.DuplicateSessionSeries"
    status_code = 409


class SessionNotAssigned(DomainError):
    """The session exists but is not assigned to the requesting coach for the requested date."""

    code = "Enrollment.SessionNotAssigned"
    status_code = 403


class StudentNotEnrolled(DomainError):
    code = "Enrollment.StudentNotEnrolled"
    status_code = 409


class StudentNotFound(DomainError):
    code = "Enrollment.StudentNotFound"
    status_code = 404


class StudentParentNotFound(DomainError):
    code = "Enrollment.StudentParentNotFound"
    status_code = 404


class StudentParentInactive(DomainError):
    code = "Enrollment.StudentParentInactive"
    status_code = 409


class StudentParentInvalidRole(DomainError):
    code = "Enrollment.StudentParentInvalidRole"
    status_code = 409


class CapacityExceeded(DomainError):
    code = "Enrollment.CapacityExceeded"
    status_code = 409


class EnrollmentAlreadyConfirmed(DomainError):
    code = "Enrollment.AlreadyConfirmed"
    status_code = 409


class EnrollmentNotFound(DomainError):
    code = "Enrollment.NotFound"
    status_code = 404


class WaitlistEmpty(DomainError):
    code = "Enrollment.WaitlistEmpty"
    status_code = 404
