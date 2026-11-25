"""Coaching domain errors.

Coaching detects facts about Enrollment-owned data through the
``SessionLookup`` / ``EnrollmentLookup`` ports — never by importing
Enrollment directly (ADR-0005 rule 5). When Coaching rejects a write
because of those facts, it raises *its own* error class. Error codes are
namespaced ``Coaching.*`` because Coaching is the producer.
"""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class PayoutPeriodFrozen(DomainError):
    """Payroll inputs for this date are already snapshotted into an
    approved or paid payout period (#787).

    Coaching learns this through the ``PayoutPeriodLock`` port — Finance
    owns the period, Coaching only asks whether the window is frozen. The
    refusal is deliberate: a frozen period does not re-read attendance, so
    a status or rate-override change after approval is invisible money
    drift rather than a correction. The owner reopens the period first.
    """

    code = "Coaching.PayoutPeriodFrozen"
    status_code = 409


class SessionCancelled(DomainError):
    code = "Coaching.SessionCancelled"
    status_code = 409


class SessionNotAssigned(DomainError):
    code = "Coaching.SessionNotAssigned"
    status_code = 409


class StudentNotEnrolled(DomainError):
    code = "Coaching.StudentNotEnrolled"
    status_code = 409


class OccurrenceNotStarted(DomainError):
    """Mark rejected because the class starts more than the marking lead time
    from now: a future class cannot have attendance yet."""

    code = "Coaching.OccurrenceNotStarted"
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


class MarkVoided(DomainError):
    """Coach correction rejected because an admin voided the mark; only an
    admin may un-void it."""

    code = "Coaching.MarkVoided"
    status_code = 403


class BulkSessionNotAssigned(DomainError):
    """Bulk attendance rejected because the coach is not assigned to this occurrence."""

    code = "Coaching.BulkSessionNotAssigned"
    status_code = 403


class BulkStudentNotEnrolled(DomainError):
    """Bulk attendance rejected because a student is not eligible (whole batch
    fails). ``details["student_ids"]`` lists every ineligible student so the
    coach UI can name them (issue #672)."""

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


class RecapNotAllowed(DomainError):
    """Caller may not see or change this occurrence's class recap. 404: the
    occurrence is not theirs (or does not exist), so do not leak it."""

    code = "Coaching.RecapNotAllowed"
    status_code = 404


class RecapWriteForbidden(DomainError):
    """Caller may read the recap (assistant, admin) but only the assigned lead
    coach or the academy owner may write it or submit a report."""

    code = "Coaching.RecapWriteForbidden"
    status_code = 403


class RecapConflict(DomainError):
    """The recap changed since the caller read it (stale ``expected_revision``)
    or this mutation id was already used for a different write."""

    code = "Coaching.RecapConflict"
    status_code = 409


class RecapInvalid(DomainError):
    """Unknown curriculum skill, or a participant who is not marked present."""

    code = "Coaching.RecapInvalid"
    status_code = 422


class DropoffCheckinDisabled(DomainError):
    """The academy has not switched parent drop-off check-in on."""

    code = "Coaching.DropoffCheckinDisabled"
    status_code = 403


class DropoffCheckinNotFound(DomainError):
    """No such student for this parent, no such occurrence in this academy,
    or (for a confirmation) no arrival report to confirm. 404 so another
    family's child or another academy's class is never revealed."""

    code = "Coaching.DropoffCheckinNotFound"
    status_code = 404


class DropoffWindowClosed(DomainError):
    """The arrival cannot be reported or confirmed now. ``details["reason"]``
    is ``cancelled``, ``not_scheduled``, ``not_open_yet``, ``closed`` or
    ``expired``."""

    code = "Coaching.DropoffWindowClosed"
    status_code = 409
