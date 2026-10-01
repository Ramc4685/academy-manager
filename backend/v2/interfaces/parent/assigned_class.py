"""Resolved class details for approved parent make-up / trial requests (#1038)."""

from __future__ import annotations

import logging
from datetime import datetime

from pydantic import BaseModel

_log = logging.getLogger(__name__)


class AssignedClassView(BaseModel):
    """The class an approved make-up / trial puts the child in (issue #1038).

    Resolved facts, not raw ids: what, when (UTC instant + the academy's IANA
    timezone so the client renders academy-local time) and where. ``status``
    is the occurrence's own status, so a called-off class reads "cancelled".
    """

    occurrence_id: str
    session_id: str
    session_title: str
    location: str | None = None
    start_at: datetime
    end_at: datetime
    timezone: str | None = None
    status: str


#: Request statuses that still put the child in the assigned class. A
#: re-opened (pending), denied or expired request never shows one.
ASSIGNED_CLASS_STATUSES = frozenset({"approved", "completed", "converted"})


async def resolve_assigned_classes(
    resolver: object | None, occurrence_ids: list[str]
) -> dict[str, AssignedClassView]:
    """Best-effort lookup: a failure degrades to "no details", never a 500."""
    if resolver is None or not occurrence_ids:
        return {}
    try:
        raw = await resolver(occurrence_ids)  # type: ignore[operator]
    except Exception:
        _log.warning("parent requests: assigned class lookup failed", exc_info=True)
        return {}
    return {oid: AssignedClassView(**details) for oid, details in raw.items()}
