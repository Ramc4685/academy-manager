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


class AttendanceNotFound(DomainError):
    """Correction rejected because no attendance mark exists for this (occurrence, student)."""

    code = "Coaching.AttendanceNotFound"
    status_code = 404


class CorrectionWindowExpired(DomainError):
    """Coach correction rejected because the grace window has passed (admin can still correct)."""

    code = "Coaching.CorrectionWindowExpired"
    status_code = 403


class BulkSessionNotAssigned(DomainError):
    """Bulk attendance rejected because the coach is not assigned to this occurrence."""

    code = "Coaching.BulkSessionNotAssigned"
    status_code = 403


class BulkStudentNotEnrolled(DomainError):
    """Bulk attendance rejected because a student is not enrolled (whole batch fails)."""

    code = "Coaching.BulkStudentNotEnrolled"
    status_code = 422


class NoteShareForbidden(DomainError):
    """An assistant-only caller tried to share a note with a parent (or change
    its visibility at all). A forbidden action on an allowed surface, so 403 —
    not the wrong-persona 404."""

    code = "Coaching.NoteShareForbidden"
    status_code = 403


class NoteNotFound(DomainError):
    """Visibility change on a note that does not exist in this session/student,
    or that a non-supervisor did not author."""

    code = "Coaching.NoteNotFound"
    status_code = 404
