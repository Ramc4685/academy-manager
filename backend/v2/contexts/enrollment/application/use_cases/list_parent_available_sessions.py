"""Parent-facing session catalog.

Parents need a small, safe catalog during onboarding. This is not generic
session CRUD; it is the read model needed to choose an enrollable session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field


class ParentAvailableSession(BaseModel):
    model_config = {"frozen": True}

    session_id: str
    title: str
    location: str
    start_at: datetime
    end_at: datetime
    # The IANA zone the class is actually scheduled in. `start_at`/`end_at` are
    # UTC instants, so a client that renders them in the viewer's browser zone
    # shows the wrong hour for anyone outside the academy's zone. Carrying the
    # session's own zone lets the parent catalog render "6:00 PM CDT" rather
    # than whatever local time that instant happens to be. `None` means the
    # session document never recorded one; clients should fall back to the
    # academy timezone from GET /parent/academy.
    timezone: str | None = None
    capacity: int = Field(ge=1)
    enrolled_count: int = Field(ge=0)
    available_seats: int = Field(ge=0)
    amount_cents: int = Field(ge=0)


class ParentSessionCatalogQuery(Protocol):
    async def available_for_parent_catalog(self) -> list[ParentAvailableSession]: ...


class ListParentAvailableSessions:
    def __init__(self, sessions: ParentSessionCatalogQuery) -> None:
        self._sessions = sessions

    async def execute(self) -> list[ParentAvailableSession]:
        return await self._sessions.available_for_parent_catalog()
