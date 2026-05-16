"""Enrollment domain events."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from backend.v2.shared.events import DomainEvent


class EnrollmentConfirmedPayload(BaseModel):
    model_config = {"frozen": True}
    enrollment_id: str
    session_id: str
    student_id: str
    parent_id: str


class EnrollmentConfirmed(DomainEvent):
    name: Literal["Enrollment.EnrollmentConfirmed"] = "Enrollment.EnrollmentConfirmed"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: EnrollmentConfirmedPayload  # type: ignore[assignment]


class EnrollmentCancelledPayload(BaseModel):
    model_config = {"frozen": True}
    enrollment_id: str
    session_id: str
    student_id: str
    reason: Literal["admin_cancel", "parent_cancel", "session_cancelled"]


class EnrollmentCancelled(DomainEvent):
    name: Literal["Enrollment.EnrollmentCancelled"] = "Enrollment.EnrollmentCancelled"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: EnrollmentCancelledPayload  # type: ignore[assignment]


class WaitlistPromotedPayload(BaseModel):
    model_config = {"frozen": True}
    waitlist_id: str
    session_id: str
    student_id: str
    parent_id: str


class WaitlistPromoted(DomainEvent):
    name: Literal["Enrollment.WaitlistPromoted"] = "Enrollment.WaitlistPromoted"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: WaitlistPromotedPayload  # type: ignore[assignment]


class CapacityExceededPayload(BaseModel):
    model_config = {"frozen": True}
    session_id: str
    parent_id: str
    student_id: str | None
    payment_id: str | None


class CapacityExceeded(DomainEvent):
    """Emitted when ConfirmEnrollment fails capacity; triggers auto-refund."""

    name: Literal["Enrollment.CapacityExceeded"] = "Enrollment.CapacityExceeded"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: CapacityExceededPayload  # type: ignore[assignment]
