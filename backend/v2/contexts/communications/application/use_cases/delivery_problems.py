"""Admin "Delivery problems" (L11 item 3). Read-only.

The suppression list is global (see ``MongoSuppressionRepository``): one row
per address, shared by every academy, and the bounce webhook records no
academy. So the academy view shows only *which of its own people* are not
receiving email, never why or since when: a reason could describe a bounce or
complaint about another academy's mail.

Failed campaign sends are this academy's own rows, minus suppression-list
refusals (``suppressed:``, which would leak the same reason), with provider
text mapped to a safe code. An unsubscribe refusal stays listed as
``recipient_unsubscribed``: email preferences are the academy's own data.

There is no academy-side clear: membership is not ownership of a global row.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    DeliveryRepository,
    SuppressionRepository,
)
from backend.v2.contexts.communications.domain.email_suppression import normalize_email
from backend.v2.contexts.communications.domain.models import AcademyAudience, AudienceRole
from backend.v2.shared.comms.public_failure import public_failure

_ROLES: tuple[AudienceRole, ...] = ("parent", "coach", "admin", "owner")
_FAILED_LIMIT = 100


@dataclass(frozen=True, slots=True)
class FailedSend:
    delivery_id: str
    recipient_email: str | None
    failed_reason: str


@dataclass(frozen=True, slots=True)
class DeliveryProblems:
    #: This academy's people whose address is suppressed (no reason, no dates).
    suppressed_emails: list[str]
    failed: list[FailedSend]


async def _member_emails(resolver: AudienceResolver) -> set[str]:
    out: set[str] = set()
    for role in _ROLES:
        for r in await resolver.resolve_academy_audience(AcademyAudience(role=role)):
            if r.email:
                out.add(normalize_email(r.email))
    return out


@dataclass
class GetDeliveryProblems:
    resolver: AudienceResolver
    suppressions: SuppressionRepository
    deliveries: DeliveryRepository

    async def execute(self) -> DeliveryProblems:
        members = await _member_emails(self.resolver)
        rows = await self.suppressions.list_active_for(sorted(members))
        failed = [
            FailedSend(
                delivery_id=d.delivery_id,
                recipient_email=d.recipient_email,
                failed_reason=public_failure(d.failed_reason, "email_delivery_failed"),
            )
            for d in await self.deliveries.list_failed(limit=_FAILED_LIMIT)
        ]
        return DeliveryProblems(
            suppressed_emails=sorted(row.email for row in rows if row.email in members),
            failed=failed,
        )
