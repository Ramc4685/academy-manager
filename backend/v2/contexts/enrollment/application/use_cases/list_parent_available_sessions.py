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
