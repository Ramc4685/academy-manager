"""ParentSelfServicePolicy — academy-scoped parent self-service configuration.

Pure domain model. No infra imports. Governs absence notices, makeup
requests, and self-cancel behavior for parent-facing self-service flows
(R1/R2/R4). Defaults are conservative: notice windows and fees are set to
sane defaults an academy can tune from the admin BFF.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from backend.v2.shared.http.errors import DomainError


class AbsenceWindowClosed(DomainError):
    """Raised when a parent tries to submit an absence notice for an
    occurrence that has already started."""

    code = "Enrollment.AbsenceWindowClosed"
    status_code = 409


class DuplicateAbsenceNotice(DomainError):
    """Raised when a parent submits a second absence notice for the same
    (occurrence, student) pair."""

    code = "Enrollment.DuplicateAbsenceNotice"
    status_code = 409


class MakeupNotEligible(DomainError):
    """Raised when a makeup request is submitted without a window-met
    absence notice, when the academy's policy requires one."""

    code = "Enrollment.MakeupNotEligible"
    status_code = 409


class MakeupWindowExpired(DomainError):
    """Raised when a makeup request is submitted after the policy's
    makeup-expiry window (relative to the missed occurrence's start) has
    passed."""

    code = "Enrollment.MakeupWindowExpired"
    status_code = 409


class DuplicateMakeupRequest(DomainError):
    """Raised when a parent submits a second non-denied makeup request for
    the same (missed occurrence, student) pair."""

    code = "Enrollment.DuplicateMakeupRequest"
    status_code = 409


class MakeupRequestNotFound(DomainError):
    """Raised when an admin acts on a makeup request id that doesn't exist."""

    code = "Enrollment.MakeupRequestNotFound"
    status_code = 404


class MakeupRequestNotPending(DomainError):
    """Raised when an admin tries to approve/deny a request that has
    already been decided (or otherwise isn't pending)."""

    code = "Enrollment.MakeupRequestNotPending"
    status_code = 409


class OccurrenceFull(DomainError):
    """Raised when approving a makeup request would exceed the target
    occurrence's session capacity."""

    code = "Enrollment.OccurrenceFull"
    status_code = 409


class ParentSelfServicePolicy(BaseModel):
    """Academy-scoped policy governing parent self-service actions."""

    academy_id: str
    absence_notice_min_hours: int = 2  # R1 notice window
    makeup_expiry_days: int = 30  # R2 expiry window
    makeup_requires_notice: bool = True
    cancellation_minimum_notice_days: int = 7  # R4
    cancellation_fee_cents: int = 0  # R4, flat
    cancellation_effective_timing: Literal["immediate", "end_of_period"] = "end_of_period"

    @staticmethod
    def default(academy_id: str) -> ParentSelfServicePolicy:
        return ParentSelfServicePolicy(academy_id=academy_id)


class OccurrenceRosterEntry(BaseModel):
    """A one-time roster addition for a single occurrence.

    Written when a makeup (Task 5) or trial (Task 7) request is approved —
    the student attends exactly this occurrence without a standing
    enrollment. Task 3 only defines the repository/model; Tasks 5/7 write
    to it via ``origin_request_id`` (the approved request's id).
    """

    model_config = {"frozen": True}

    entry_id: str
    academy_id: str
    occurrence_id: str
    student_id: str
    source: Literal["makeup", "trial"]
    origin_request_id: str
    created_at: datetime


MakeupRequestStatus = Literal["pending", "approved", "denied", "expired", "completed"]


class MakeupRequest(BaseModel):
    """A parent-submitted request to make up a missed occurrence (R2).

    Submission (Task 4) always creates a ``pending`` request. Admin review
    (Task 5) decides it — approving stamps ``approved_target_occurrence_id``
    and writes an ``OccurrenceRosterEntry``; denying sets
    ``denial_reason``. Both decisions stamp ``decided_by``/``decided_at``.
    """

    request_id: str
    academy_id: str
    student_id: str
    parent_id: str
    missed_occurrence_id: str
    requested_target_occurrence_id: str | None = None
    status: MakeupRequestStatus = "pending"
    expires_at: datetime
    denial_reason: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    approved_target_occurrence_id: str | None = None
    created_at: datetime
