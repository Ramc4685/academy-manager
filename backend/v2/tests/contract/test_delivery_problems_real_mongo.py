"""Delivery-problems reads on a real mongod (L11 item 3): failed sends stay in
the request academy, and the suppression lookup returns only the addresses
asked for, never the rest of the global list."""

from __future__ import annotations

from backend.v2.contexts.communications.application.ports import ResolvedRecipient
from backend.v2.contexts.communications.domain.email_suppression import SuppressionReason
from backend.v2.contexts.communications.domain.models import Delivery
from backend.v2.contexts.communications.infrastructure.mongo_delivery_repo import (
    MongoDeliveryRepository,
)
from backend.v2.contexts.communications.infrastructure.mongo_suppression_repo import (
    MongoSuppressionRepository,
)
from backend.v2.shared.tenancy import tenant_scope


async def test_failed_deliveries_stay_in_the_request_academy(real_db) -> None:
    repo = MongoDeliveryRepository(real_db)
    for academy in ("acad-a", "acad-b"):
        with tenant_scope(academy):
            queued = Delivery.queued(
                delivery_id=f"d-{academy}",
                academy_id=academy,
                campaign_id="c",
                recipient=ResolvedRecipient(user_id="u", email="u@example.test"),
            )
            await repo.save_many([queued.mark_failed(reason="provider 422")])
    with tenant_scope("acad-a"):
        failed = await repo.list_failed(limit=10)
    assert [d.delivery_id for d in failed] == ["d-acad-a"]


async def test_suppression_lookup_returns_only_the_addresses_asked_for(real_db) -> None:
    repo = MongoSuppressionRepository(real_db)
    await repo.record(email="mine@example.test", reason=SuppressionReason.HARD_BOUNCE)
    await repo.record(email="theirs@example.test", reason=SuppressionReason.COMPLAINT)
    rows = await repo.list_active_for(["MINE@example.test", "absent@example.test"])
    assert [r.email for r in rows] == ["mine@example.test"]
    assert await repo.list_active_for([]) == []


async def test_a_later_escalation_from_another_academy_hides_detail_from_the_first(
    real_db,
) -> None:
    """A records a complaint first, B's hard bounce escalates the row: A must
    see only the generic status, B sees its own bounce."""
    from backend.v2.contexts.communications.application.ports import ResolvedRecipient
    from backend.v2.contexts.communications.application.use_cases.delivery_problems import (
        GetDeliveryProblems,
    )

    repo = MongoSuppressionRepository(real_db)
    with tenant_scope("acad-a"):
        await repo.record(email="shared@example.test", reason=SuppressionReason.COMPLAINT)
    with tenant_scope("acad-b"):
        row = await repo.record(email="shared@example.test", reason=SuppressionReason.HARD_BOUNCE)
    assert row.first_seen_academy_id == "acad-a"
    assert row.last_seen_academy_id == "acad-b"

    class _Members:
        async def resolve_academy_audience(self, audience):  # type: ignore[no-untyped-def]
            if audience.role != "parent":
                return []
            return [ResolvedRecipient(user_id="s1", email="shared@example.test")]

    async def view(academy: str):  # type: ignore[no-untyped-def]
        with tenant_scope(academy):
            result = await GetDeliveryProblems(
                resolver=_Members(),  # type: ignore[arg-type]
                suppressions=repo,
                deliveries=MongoDeliveryRepository(real_db),
            ).execute()
        return result.suppressed[0]

    seen_by_a = await view("acad-a")
    assert (seen_by_a.reason, seen_by_a.last_seen_at) == (None, None)
    assert (await view("acad-b")).reason == "hard_bounce"


async def test_an_event_that_does_not_set_the_reason_clears_attribution(real_db) -> None:
    repo = MongoSuppressionRepository(real_db)
    with tenant_scope("acad-a"):
        await repo.record(email="x@example.test", reason=SuppressionReason.HARD_BOUNCE)
    with tenant_scope("acad-b"):
        row = await repo.record(email="x@example.test", reason=SuppressionReason.MANUAL)
    assert row.reason == SuppressionReason.HARD_BOUNCE
    assert row.last_seen_academy_id is None
