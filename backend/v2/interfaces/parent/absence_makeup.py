"""The makeup state shown on a parent's reported absence (Requests, Children)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from backend.v2.interfaces.parent.assigned_class import (
    AssignedClassView,
    resolve_assigned_classes,
)

_log = logging.getLogger(__name__)


class AbsenceMakeupView(BaseModel):
    """Where a reported absence stands: reported, makeup eligible, requested,
    booked (with the makeup class) or expired. Decided server-side by the
    same eligibility check a makeup request runs; the client only displays it."""

    state: Literal["reported", "eligible", "requested", "booked", "expired"]
    expires_at: datetime | None = None
    reason: str | None = None
    booked_class: AssignedClassView | None = None


async def describe_absence_makeups(
    use_cases: object, keys: list[tuple[str, str]]
) -> dict[tuple[str, str], AbsenceMakeupView]:
    """``(student_id, occurrence_id)`` -> state. Callers pass only the parent's
    own notice keys. Best-effort: a failure shows no state, never a 500."""
    describe = getattr(use_cases, "describe_absence_makeups", None)
    if describe is None or not keys:
        return {}
    try:
        statuses = await describe.execute(keys)
    except Exception:
        _log.warning("parent absences: makeup state lookup failed", exc_info=True)
        return {}
    booked = await resolve_assigned_classes(
        getattr(use_cases, "resolve_assigned_classes", None),
        sorted({s.booked_occurrence_id for s in statuses.values() if s.booked_occurrence_id}),
    )
    return {
        key: AbsenceMakeupView(
            state=s.state,
            expires_at=s.expires_at,
            reason=s.reason,
            booked_class=booked.get(s.booked_occurrence_id) if s.booked_occurrence_id else None,
        )
        for key, s in statuses.items()
    }
