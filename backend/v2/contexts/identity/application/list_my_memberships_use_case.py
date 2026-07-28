"""List the caller's own academy memberships (self-service, no persona gate).

Backs `GET /me/memberships`, which powers the admin TenantSwitcher for
multi-academy users (franchise owners, platform staff). Only the caller's own
data is returned — any authenticated persona may call this.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from backend.v2.contexts.identity.domain.models import AcademyMembership


class MembershipsLookup(Protocol):
    async def list_memberships_for_user(self, user_id: str) -> list[AcademyMembership]: ...


class AcademyNameLookup(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class MembershipSummary:
    academy_id: str
    academy_name: str | None
    academy_slug: str | None
    roles: tuple[str, ...]
    status: str
    is_default: bool


@dataclass(frozen=True)
class ListMyMembershipsOutput:
    memberships: list[MembershipSummary]
    active_academy_id: str


class ListMyMembershipsUseCase:
    def __init__(self, memberships: MembershipsLookup, academies: AcademyNameLookup) -> None:
        self._memberships = memberships
        self._academies = academies

    async def execute(self, *, user_id: str, active_academy_id: str) -> ListMyMembershipsOutput:
        rows = await self._memberships.list_memberships_for_user(user_id)
        active_rows = [row for row in rows if row.is_active()]

        summaries: list[MembershipSummary] = []
        for row in active_rows:
            doc = await self._academies.find_by_id(row.academy_id)
            name = (doc.get("display_name") or doc.get("name")) if doc else None
            slug = doc.get("slug") if doc else None
            summaries.append(
                MembershipSummary(
                    academy_id=row.academy_id,
                    academy_name=str(name) if name else None,
                    academy_slug=str(slug) if slug else None,
                    roles=tuple(row.roles),
                    status=row.status,
                    is_default=row.academy_id == active_academy_id,
                )
            )

        return ListMyMembershipsOutput(memberships=summaries, active_academy_id=active_academy_id)
