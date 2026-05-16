"""Coaching domain errors.

Coaching detects facts about Enrollment-owned data through the
``SessionLookup`` / ``EnrollmentLookup`` ports — never by importing
Enrollment directly (ADR-0005 rule 5). When Coaching rejects a write
because of those facts, it raises *its own* error class. Error codes are
namespaced ``Coaching.*`` because Coaching is the producer.
"""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class SessionCancelled(DomainError):
    code = "Coaching.SessionCancelled"
    status_code = 409


class SessionNotAssigned(DomainError):
    code = "Coaching.SessionNotAssigned"
    status_code = 409


class StudentNotEnrolled(DomainError):
    code = "Coaching.StudentNotEnrolled"
    status_code = 409


class ConflictAttendanceExists(DomainError):
    """A different mutation already recorded attendance for this (session, student)."""

    code = "Coaching.ConflictAttendanceExists"
    status_code = 409
