"""Owner (franchise) BFF composition — UIM11 cross-academy rollup.

Small on purpose: the owner surface is read-only and spans academies, so it
gets its own composition root rather than borrowing the admin one (whose
use cases all assume a single resolved tenant).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.billing.application.ports import OwnerAcademyRef
from backend.v2.contexts.billing.application.use_cases.owner_rollup import (
    GetOwnerFinancialRollup,
)
from backend.v2.contexts.billing.infrastructure.mongo_owner_rollup_reader import (
    MongoAcademyFinancialSnapshotReader,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_membership_repo import (
    MongoMembershipRepository,
)

OWNER_ROLE: Literal["owner"] = "owner"


class MembershipOwnerAcademyDirectory:
    """Resolves owned academies from the caller's OWN active memberships.

    The request tenant is not consulted: an owner of A and B sees A+B no
    matter which academy they are currently "in", and a user with no active
    `owner` membership resolves to an empty list (the route turns that into
    a 404).
    """

    def __init__(
        self,
        memberships: MongoMembershipRepository,
        academies: MongoAcademyRepository,
    ) -> None:
        self._memberships = memberships
        self._academies = academies

    async def list_owner_academies(self, user_id: str) -> list[OwnerAcademyRef]:
        rows = await self._memberships.list_memberships_for_user(user_id)
        refs: list[OwnerAcademyRef] = []
        for row in rows:
            if not row.has_role(OWNER_ROLE):  # has_role() already requires status=active
                continue
            doc = await self._academies.find_by_id(row.academy_id)
            name = (doc.get("display_name") or doc.get("name")) if doc else None
            refs.append(
                OwnerAcademyRef(
                    academy_id=row.academy_id,
                    academy_name=str(name) if name else None,
                )
            )
        return refs


@dataclass(frozen=True)
class OwnerComposition:
    get_rollup: GetOwnerFinancialRollup


def compose_owner(db: AsyncIOMotorDatabase[Any]) -> OwnerComposition:
    return OwnerComposition(
        get_rollup=GetOwnerFinancialRollup(
            academies=MembershipOwnerAcademyDirectory(
                MongoMembershipRepository(db),
                MongoAcademyRepository(db),
            ),
            snapshots=MongoAcademyFinancialSnapshotReader(db),
        )
    )
