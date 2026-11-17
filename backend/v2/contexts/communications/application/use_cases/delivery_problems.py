"""Admin "Delivery problems" (L11 item 3). Read-only.

The suppression list is global (see ``MongoSuppressionRepository``): one row
per address, shared by every academy. So the academy view is limited twice:

* only the academy's own people are listed (the list is intersected with the
  academy's members, and the store is asked for those addresses alone);
* the reason and dates are shown only when the event that set the current
  reason was recorded under this academy (``last_seen_academy_id``). Otherwise the
  row says only that the address is not receiving email, so an admin cannot
  learn that a family bounced or complained about another academy's mail.

There is no academy-side clear. Membership is not ownership of a global row,
and the bounce webhook records no academy today, so a clear here would lift a
suppression another academy depends on. Clearing stays a platform action.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    DeliveryRepository,
    SuppressionRepository,
)
from backend.v2.contexts.communications.domain.email_suppression import normalize_email
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    AudienceRole,
    Delivery,
)
from backend.v2.shared.tenancy import current_academy_id

_ROLES: tuple[AudienceRole, ...] = ("parent", "coach", "admin", "owner")


@dataclass(frozen=True, slots=True)
class SuppressedMember:
    user_id: str
    email: str
    #: ``None`` (with the dates) when the suppression was caused elsewhere.
    reason: str | None
    bounce_subtype: str | None
    last_seen_at: datetime | None


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

    async def execute(self, *, limit: int = 100) -> DeliveryProblems:
        academy_id = current_academy_id()
        members = await _members(self.resolver)
        rows = await self.suppressions.list_active_for(sorted(members))
        suppressed = []
        for row in rows:
            if row.email not in members:
                continue
            ours = row.last_seen_academy_id == academy_id
            suppressed.append(
                SuppressedMember(
                    user_id=members[row.email],
                    email=row.email,
                    reason=str(row.reason) if ours else None,
                    bounce_subtype=row.bounce_subtype if ours else None,
                    last_seen_at=row.last_seen_at if ours else None,
                )
            )
        return DeliveryProblems(
            suppressed=suppressed,
            failed=await self.deliveries.list_failed(limit=max(1, min(limit, 200))),
        )
