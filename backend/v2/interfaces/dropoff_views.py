"""Drop-off check-in views shared by the parent, coach and admin BFFs.

``state``: ``none`` (not reported), ``pending`` (reported, staff have not
confirmed yet), ``confirmed`` (attendance written) or ``expired`` (still
unconfirmed after the window closed). Only ``confirmed`` is attendance.
All timestamps are server clock, UTC.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel

from backend.v2.composition.dropoff_checkins import DropoffCheckinComposition
from backend.v2.contexts.coaching.application.use_cases.dropoff_checkin import (
    DropoffCheckinSnapshot,
)


class DropoffCheckinView(BaseModel):
    occurrence_id: str
    student_id: str
    state: Literal["none", "pending", "confirmed", "expired"]
    reported_at: datetime | None = None
    confirmed_at: datetime | None = None
    window_opens_at: datetime
    window_closes_at: datetime
    can_report_arrival: bool = False

    @classmethod
    def from_snapshot(cls, snap: DropoffCheckinSnapshot) -> DropoffCheckinView:
        row = snap.checkin
        return cls(
            occurrence_id=snap.occurrence_id,
            student_id=snap.student_id,
            state=snap.state,
            reported_at=row.reported_at if row else None,
            confirmed_at=row.confirmed_at if row else None,
            window_opens_at=snap.window_opens_at,
            window_closes_at=snap.window_closes_at,
            can_report_arrival=snap.can_report_arrival,
        )


class StaffDropoffCheckinView(DropoffCheckinView):
    """Adds who reported / confirmed (names resolved where the read does so)
    and the attendance mark the confirmation wrote or linked to."""

    reported_by: str | None = None
    reported_by_name: str | None = None
    confirmed_by: str | None = None
    confirmed_by_name: str | None = None
    attendance_id: str | None = None
    #: A mark already existed, so the confirmation linked to it.
    reconciled_with_existing_mark: bool = False

    @classmethod
    def from_staff_snapshot(
        cls, snap: DropoffCheckinSnapshot, names: Mapping[str, str] | None = None
    ) -> StaffDropoffCheckinView:
        names = names or {}
        row = snap.checkin
        base = DropoffCheckinView.from_snapshot(snap).model_dump()
        if row is None:
            return cls(**base)
        return cls(
            **base,
            reported_by=row.reported_by,
            reported_by_name=names.get(row.reported_by),
            confirmed_by=row.confirmed_by,
            confirmed_by_name=names.get(row.confirmed_by or ""),
            attendance_id=row.attendance_id,
            reconciled_with_existing_mark=row.reconciled_with_existing_mark,
        )


def dropoff_checkins(request: Request) -> DropoffCheckinComposition:
    composed = getattr(request.app.state, "dropoff_checkins", None)
    if composed is None:
        raise HTTPException(status_code=503, detail="Drop-off check-in is not configured")
    return composed  # type: ignore[no-any-return]


def optional_dropoff_checkins(request: Request) -> DropoffCheckinComposition | None:
    """For reads that only decorate: fixtures without the composition skip it."""
    return getattr(request.app.state, "dropoff_checkins", None)
