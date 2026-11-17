"""Admin "Delivery problems" (L11 item 3). The suppression list is shared by
every academy, so the academy view lists only its own people, shows reason and
dates only for suppressions recorded under this academy, and offers no clear."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.communications.application.ports import ResolvedRecipient
from backend.v2.contexts.communications.application.use_cases.delivery_problems import (
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
from backend.v2.shared.tenancy import tenant_scope

T = datetime(2026, 11, 1, tzinfo=UTC)

#: acad-a and acad-b share one family (shared@). Each has one private family.
MEMBERS = {
    "acad-a": [("a1", "Mine@Example.test"), ("s1", "shared@example.test"), ("a2", None)],
    "acad-b": [("b1", "theirs@example.test"), ("s1", "shared@example.test")],
}


class _Resolver:
    """Tenant-scoped like the real resolver: reads the academy in scope."""

    async def resolve_academy_audience(self, audience: AcademyAudience) -> list[ResolvedRecipient]:
        from backend.v2.shared.tenancy import current_academy_id

        if audience.role != "parent":
            return []
        return [
            ResolvedRecipient(user_id=uid, email=email)
            for uid, email in MEMBERS[current_academy_id()]
        ]


def _sup(email: str, reason: SuppressionReason, academy: str | None) -> EmailSuppression:
    return EmailSuppression(
        email=email,
        reason=reason,
        first_seen_at=T,
        last_seen_at=T,
        bounce_subtype="General",
        first_seen_academy_id=academy,
    )


class _Suppressions:
    def __init__(self) -> None:
        self.asked: list[list[str]] = []
        self.rows = {
            "mine@example.test": _sup("mine@example.test", SuppressionReason.HARD_BOUNCE, "acad-a"),
            # The shared family complained about acad-b's mail.
            "shared@example.test": _sup(
                "shared@example.test", SuppressionReason.COMPLAINT, "acad-b"
            ),
            "theirs@example.test": _sup(
                "theirs@example.test", SuppressionReason.HARD_BOUNCE, "acad-b"
            ),
        }

    async def list_active_for(self, emails: list[str]) -> list[EmailSuppression]:
        self.asked.append(emails)
        return [self.rows[e] for e in emails if e in self.rows]


class _Deliveries:
    async def list_failed(self, *, limit: int) -> list[Delivery]:
        return [
            Delivery(
                delivery_id="d1",
                academy_id="acad-a",
                campaign_id="c1",
                recipient_user_id="a1",
                recipient_email="mine@example.test",
                status=DeliveryStatus.FAILED,
                provider_message_id=None,
                sent_at=None,
                opened_at=None,
                failed_reason="provider 422",
            )
        ][:limit]


def _use_case(store: _Suppressions) -> GetDeliveryProblems:
    return GetDeliveryProblems(
        resolver=_Resolver(),  # type: ignore[arg-type]
        suppressions=store,  # type: ignore[arg-type]
        deliveries=_Deliveries(),  # type: ignore[arg-type]
    )


async def test_academy_a_sees_its_own_people_and_detail_only_for_its_own_events() -> None:
    store = _Suppressions()
    with tenant_scope("acad-a"):
        result = await _use_case(store).execute()
    # Only acad-a's addresses were ever asked for: theirs@ never leaves the store.
    assert store.asked == [["mine@example.test", "shared@example.test"]]
    by_email = {row.email: row for row in result.suppressed}
    assert set(by_email) == {"mine@example.test", "shared@example.test"}
    assert by_email["mine@example.test"].reason == "hard_bounce"
    assert by_email["mine@example.test"].last_seen_at == T
    # acad-b's complaint: listed as not receiving, with no reason or dates.
    shared = by_email["shared@example.test"]
    assert (shared.reason, shared.bounce_subtype, shared.last_seen_at) == (None, None, None)
    assert [d.delivery_id for d in result.failed] == ["d1"]


async def test_academy_b_sees_the_complaint_it_caused() -> None:
    with tenant_scope("acad-b"):
        result = await _use_case(_Suppressions()).execute()
    by_email = {row.email: row for row in result.suppressed}
    assert set(by_email) == {"theirs@example.test", "shared@example.test"}
    assert by_email["shared@example.test"].reason == "complaint"


async def test_an_unattributed_suppression_shows_no_detail() -> None:
    store = _Suppressions()
    store.rows["mine@example.test"] = _sup("mine@example.test", SuppressionReason.HARD_BOUNCE, None)
    with tenant_scope("acad-a"):
        result = await _use_case(store).execute()
    mine = next(r for r in result.suppressed if r.email == "mine@example.test")
    assert mine.reason is None
