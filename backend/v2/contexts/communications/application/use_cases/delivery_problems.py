"""Admin "Delivery problems" (L11 item 3).

The suppression list is global (see ``MongoSuppressionRepository``), so the
academy view is the intersection of that list with the academy's own people:
an admin never learns whether an address outside the academy bounced or
complained. Clearing is limited to hard bounces of the academy's own people
(a fixed mailbox); a spam complaint stays until platform support clears it.
A clear is not permanent: the next bounce re-suppresses the address.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    DeliveryRepository,
    SuppressionRepository,
)
from backend.v2.contexts.communications.domain.email_suppression import (
    SuppressionReason,
    normalize_email,
)
from backend.v2.contexts.communications.domain.models import AcademyAudience, Delivery

_ROLES = ("parent", "coach", "admin", "owner")


class NotAMember(Exception):
    """The address is not one of this academy's people."""


class NotReleasable(Exception):
    """Only a hard bounce may be cleared from the academy view."""


@dataclass(frozen=True, slots=True)
class SuppressedMember:
    user_id: str
    email: str
    reason: str
    bounce_subtype: str | None
    last_seen_at: datetime
    releasable: bool


@dataclass(frozen=True, slots=True)
class DeliveryProblems:
    suppressed: list[SuppressedMember]
    failed: list[Delivery]


async def _members(resolver: AudienceResolver) -> dict[str, str]:
    """Normalized email -> user id for everyone in the current academy."""
    out: dict[str, str] = {}
    for role in _ROLES:
        for r in await resolver.resolve_academy_audience(AcademyAudience(role=role)):
            if r.email:
                out.setdefault(normalize_email(r.email), r.user_id)
    return out


@dataclass
class GetDeliveryProblems:
    resolver: AudienceResolver
    suppressions: SuppressionRepository
    deliveries: DeliveryRepository
    release_enabled: bool = False

    async def execute(self, *, limit: int = 100) -> DeliveryProblems:
        members = await _members(self.resolver)
        rows = await self.suppressions.list_active_for(sorted(members))
        return DeliveryProblems(
            suppressed=[
                SuppressedMember(
                    user_id=members[row.email],
                    email=row.email,
                    reason=str(row.reason),
                    bounce_subtype=row.bounce_subtype,
                    last_seen_at=row.last_seen_at,
                    releasable=self.release_enabled and row.reason == SuppressionReason.HARD_BOUNCE,
                )
                for row in rows
                if row.email in members
            ],
            failed=await self.deliveries.list_failed(limit=max(1, min(limit, 200))),
        )


@dataclass
class ReleaseMemberSuppression:
    resolver: AudienceResolver
    suppressions: SuppressionRepository
    release_enabled: bool = False

    async def execute(self, *, email: str, released_by: str) -> bool:
        if not self.release_enabled:
            raise NotReleasable("Clearing suppressions is turned off")
        key = normalize_email(email)
        if key not in await _members(self.resolver):
            raise NotAMember(key)
        row = await self.suppressions.get_active(key)
        if row is None:
            return False
        if row.reason != SuppressionReason.HARD_BOUNCE:
            raise NotReleasable("Only a hard bounce can be cleared here")
        return await self.suppressions.release(email=key, released_by=released_by)
