"""Admin "Delivery problems" (L11 item 3). The suppression list is shared by
every academy, so the academy view lists only its own people, never a reason
or date, and hides send-time gate refusals and provider text in failed sends."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.communications.application.ports import ResolvedRecipient
from backend.v2.contexts.communications.application.use_cases.delivery_problems import (
    FailedSend,
    GetDeliveryProblems,
)
from backend.v2.contexts.communications.domain.email_suppression import (
    EmailSuppression,
    SuppressionReason,
)
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    Delivery,
    DeliveryStatus,
)
from backend.v2.shared.comms.public_failure import SUPPRESSION_REFUSAL
from backend.v2.shared.tenancy import current_academy_id, tenant_scope

T = datetime(2026, 11, 1, tzinfo=UTC)

#: acad-a and acad-b share one family (shared@). Each has one private family.
MEMBERS = {
    "acad-a": [("a1", "Mine@Example.test"), ("s1", "shared@example.test"), ("a2", None)],
    "acad-b": [("b1", "theirs@example.test"), ("s1", "shared@example.test")],
}


class _Resolver:
    """Tenant-scoped like the real resolver: reads the academy in scope."""

    async def resolve_academy_audience(self, audience: AcademyAudience) -> list[ResolvedRecipient]:
        if audience.role != "parent":
            return []
        return [ResolvedRecipient(user_id=u, email=e) for u, e in MEMBERS[current_academy_id()]]


class _Suppressions:
    def __init__(self) -> None:
        self.asked: list[list[str]] = []
        self.rows = {
            e: EmailSuppression(email=e, reason=r, first_seen_at=T, last_seen_at=T)
            for e, r in [
                ("mine@example.test", SuppressionReason.HARD_BOUNCE),
                ("shared@example.test", SuppressionReason.COMPLAINT),
                ("theirs@example.test", SuppressionReason.HARD_BOUNCE),
            ]
        }

    async def list_active_for(self, emails: list[str]) -> list[EmailSuppression]:
        self.asked.append(emails)
        return [self.rows[e] for e in emails if e in self.rows]


def _failed(delivery_id: str, reason: str) -> Delivery:
    return Delivery(
        delivery_id=delivery_id,
        academy_id="acad-a",
        campaign_id="c1",
        recipient_user_id="a1",
        recipient_email="mine@example.test",
        status=DeliveryStatus.FAILED,
        provider_message_id=None,
        sent_at=None,
        opened_at=None,
        failed_reason=reason,
    )


class _Deliveries:
    """What ``MongoDeliveryRepository.list_failed`` returns: suppression
    refusals are filtered in the query, unsubscribe refusals are not."""

    async def list_failed(self, *, limit: int) -> list[Delivery]:
        rows = [
            _failed("d1", "Resend 422: The to address is invalid"),
            _failed("d2", "suppressed:complaint"),
            _failed("d3", "unsubscribed:campaigns"),
        ]
        return [d for d in rows if not SUPPRESSION_REFUSAL.match(d.failed_reason or "")]


def _use_case(store: _Suppressions) -> GetDeliveryProblems:
    return GetDeliveryProblems(
        resolver=_Resolver(),  # type: ignore[arg-type]
        suppressions=store,  # type: ignore[arg-type]
        deliveries=_Deliveries(),  # type: ignore[arg-type]
    )


async def test_lists_only_this_academys_people_with_no_reason() -> None:
    store = _Suppressions()
    with tenant_scope("acad-a"):
        result = await _use_case(store).execute()
    # Only acad-a's addresses were ever asked for: theirs@ never leaves the store.
    assert store.asked == [["mine@example.test", "shared@example.test"]]
    assert result.suppressed_emails == ["mine@example.test", "shared@example.test"]


async def test_failed_sends_map_provider_text_and_name_unsubscribes() -> None:
    with tenant_scope("acad-a"):
        result = await _use_case(_Suppressions()).execute()
    assert result.failed == [
        FailedSend(
            delivery_id="d1",
            recipient_email="mine@example.test",
            failed_reason="email_delivery_failed",
        ),
        FailedSend(
            delivery_id="d3",
            recipient_email="mine@example.test",
            failed_reason="recipient_unsubscribed",
        ),
    ]
