"""EnrollmentDeparturePolicy — academy-scoped staff-departure & hold policy.

Sibling of ``ParentSelfServicePolicy`` (see ``domain/self_service.py``), NOT
an extension of it. Three independent reasons, any one sufficient (issue
#697 design contract §1.1):

1. ``PUT /self-service/policy`` is a whole-object PUT owned by the parent
   self-service panel; folding these four fields into it would let a stale
   parent-panel tab silently rewrite departure policy.
2. Authorization boundary: this PUT must be owner-only
   (``delete_enrollment_requires_owner`` governs an owner-only capability),
   while self-service policy is admin-writable.
3. Bounded-context naming: this governs staff departure actions and
   automatic system reclaim, not parent-facing self-service flows.

Pure domain model. No infra imports.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.shared.http.errors import DomainError


class EnrollmentDeparturePolicy(BaseModel):
    """Academy-scoped policy governing staff departure actions and hold reclaim."""

    academy_id: str

    #: Maximum length of a hold, in days, measured from hold_started_at.
    #: Snapshotted onto the enrollment as hold_expires_at when the hold
    #: starts, so lowering this never retroactively expires a running hold.
    max_hold_days: int = Field(default=60, ge=1, le=365)

    #: What happens when a full class needs a seat and holds exist.
    #: "longest_held" — reclaim the hold with the smallest hold_started_at.
    #: "never"        — holds are never reclaimed; a full class stays full.
    hold_reclaim_policy: Literal["longest_held", "never"] = "longest_held"

    #: The default the Drop dialog pre-selects and the value the SYSTEM uses
    #: for a reclaim or a hold expiry (which have no admin to choose).
    #: Encodes both halves of the owner's "no credit, mid-month" as one
    #: value so the two can never be set to an incoherent pair.
    drop_default_outcome: Literal[
        "no_credit_mid_month",  # attendance stops now, no money back  (default)
        "credit_mid_month",  # attendance stops now, prorated credit
        "no_credit_end_of_period",  # attendance stops at period end, no money back
    ] = "no_credit_mid_month"

    #: Whether Delete (hard removal of the enrollment row) needs the owner role.
    delete_enrollment_requires_owner: bool = True

    @staticmethod
    def default(academy_id: str) -> EnrollmentDeparturePolicy:
        return EnrollmentDeparturePolicy(academy_id=academy_id)


def compute_hold_expiry(started_at: datetime, max_hold_days: int) -> datetime:
    """The only place ``hold_expires_at`` is computed.

    A pure snapshot function: called once, at hold start, and never again.
    Re-running it against a later (changed) ``max_hold_days`` must never be
    used to move an existing hold's expiry.
    """
    return started_at + timedelta(days=max_hold_days)


class EnrollmentNotHoldable(DomainError):
    """The row cannot be placed on hold from its current status (issue #697).

    In particular a ``paused`` row cannot go directly to ``held`` — it has
    already released its seat, and converting it would require a
    ``try_reserve_seat`` that can fail mid-conversion. The admin path is
    Resume, then Hold.
    """

    code = "Enrollment.NotHoldable"
    status_code = 409


class EnrollmentNotReturnable(DomainError):
    """The row is not ``held`` (already returned, or its hold was reclaimed
    or expired) so Return cannot apply."""

    code = "Enrollment.NotReturnable"
    status_code = 409


class HoldWindowExceeded(DomainError):
    """The requested return date is beyond ``hold_started_at + max_hold_days``."""

    code = "Enrollment.HoldWindowExceeded"
    status_code = 422


class HoldRequiresReturnDate(DomainError):
    """A hold cannot start without a promised return date."""

    code = "Enrollment.HoldRequiresReturnDate"
    status_code = 422


class DeleteRequiresOwner(DomainError):
    """Delete is owner-only for this academy (``delete_enrollment_requires_owner``)."""

    code = "Enrollment.DeleteRequiresOwner"
    status_code = 404
