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


class AcademyTimezoneUnset(DomainError):
    """No timezone could be resolved for the tenant, so we refuse to guess.

    Session instants are computed from a wall-clock start_time plus a zone, and
    occurrence synthesis, monthly invoices and payroll all re-derive from the
    persisted zone. A wrong guess silently corrupts all three, so writes fail
    closed rather than defaulting.
    """

    code = "Enrollment.AcademyTimezoneUnset"
    status_code = 422


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


class SessionNotEnrollable(DomainError):
    """The session exists but its status does not accept new enrollments.

    Distinct from `CapacityExceeded` on purpose: a cancelled or completed
    session also fails the atomic `try_reserve_seat` predicate, and reporting
    that as "session full" sent admins hunting for a capacity problem that
    was not there (issue #610).
    """

    code = "Enrollment.SessionNotEnrollable"
    status_code = 409


class SeatCounterDrift(DomainError):
    """`reserved_seats` says full while the roster is under capacity.

    Reported, never auto-reconciled. `reserved_seats` is a shared counter that
    every enrollment path increments *before* writing its row, so being ahead
    of the active-enrollment count is a legitimate transient state during an
    in-flight parent checkout. A repair write here would clobber a live
    reservation and oversell the session; reconciliation is an explicit ops
    action.
    """

    code = "Enrollment.SeatCounterDrift"
    status_code = 409


class StudentAlreadyOnRoster(DomainError):
    """This student already holds an active or paused enrollment here.

    There is no unique (session, student) index — prod already carries
    duplicate active rows — so this is enforced by an application pre-check
    plus a `DuplicateKeyError` backstop, not by the database.
    """

    code = "Enrollment.StudentAlreadyOnRoster"
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
