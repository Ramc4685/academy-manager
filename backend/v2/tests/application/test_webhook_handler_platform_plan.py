"""``source == "platform_plan"`` Stripe events go to the platform billing sync
and never to the parent-tuition handlers; everything else is untouched."""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    QUARANTINE_PLATFORM_PLAN_ON_CONNECT_ACCOUNT,
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.tests.application.test_webhook_handler import (
    FakeDedup,
    FakeOutbox,
    FakePaymentRepo,
    FakeSubscriptionRepo,
    _seed_incomplete_subscription,
)


def _build(
    repo: FakePaymentRepo, subs: FakeSubscriptionRepo, sync: Any, dedup: FakeDedup | None = None
) -> HandleWebhookEvent:
    return HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=dedup or FakeDedup(),
        payments=repo,
        subscriptions=subs,
        outbox=FakeOutbox(),
        academy_id="acad",
        platform_plan_sync=sync,
    )


class _Sync:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, event_type: str, event: dict[str, Any]) -> None:
        self.calls.append((event_type, event["data"]["object"]["id"]))


def _event(event_type: str, obj: dict[str, Any], **top: Any) -> bytes:
    return json.dumps(
        {"id": f"evt_{obj['id']}", "type": event_type, "data": {"object": obj}, **top}
    ).encode()


_PLAN_METADATA = {"source": "platform_plan", "academy_id": "acad", "plan_id": "plan_growth"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    [
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ],
)
async def test_platform_plan_event_reaches_only_the_sync(event_type: str) -> None:
    repo, subs, sync = FakePaymentRepo(), FakeSubscriptionRepo(), _Sync()
    uc = _build(repo, subs, sync)
    await uc.execute(
        _event(event_type, {"id": "sub_plan_1", "status": "active", "metadata": _PLAN_METADATA}),
        "test_signature",
    )
    assert sync.calls == [(event_type, "sub_plan_1")]
    # Nothing was projected into parent tuition.
    assert subs.by_stripe_sub == {} and repo.by_id == {}


@pytest.mark.asyncio
async def test_tuition_subscription_event_never_reaches_the_sync() -> None:
    repo, subs, sync = FakePaymentRepo(), FakeSubscriptionRepo(), _Sync()
    _seed_incomplete_subscription(subs, stripe_subscription_id="sub_live_9", status="active")
    uc = _build(repo, subs, sync)
    await uc.execute(
        _event("customer.subscription.updated", {"id": "sub_live_9", "status": "past_due"}),
        "test_signature",
    )
    assert sync.calls == []
    assert subs.by_stripe_sub["sub_live_9"].status == "past_due"


@pytest.mark.asyncio
async def test_platform_plan_event_without_a_sync_is_dropped_not_misrouted() -> None:
    repo, subs = FakePaymentRepo(), FakeSubscriptionRepo()
    uc = _build(repo, subs, None)
    await uc.execute(
        _event(
            "customer.subscription.created",
            {"id": "sub_plan_1", "status": "active", "metadata": _PLAN_METADATA},
        ),
        "test_signature",
    )
    assert subs.by_stripe_sub == {}


@pytest.mark.asyncio
async def test_platform_plan_event_on_a_connected_account_is_quarantined_not_synced() -> None:
    """Metadata is text anyone on a connected account can write; platform-plan
    objects live on the platform account only (no top-level ``account``)."""
    repo, subs, sync, dedup = FakePaymentRepo(), FakeSubscriptionRepo(), _Sync(), FakeDedup()
    uc = _build(repo, subs, sync, dedup)
    body = _event(
        "customer.subscription.updated",
        {"id": "sub_plan_1", "status": "active", "metadata": _PLAN_METADATA},
        account="acct_connected",
    )
    res = await uc.accept(body, "test_signature")
    assert res["status"] == "quarantined"
    row = dedup.events["evt_sub_plan_1"]
    assert row["status"] == "quarantined"
    assert row["quarantine_reason"] == QUARANTINE_PLATFORM_PLAN_ON_CONNECT_ACCOUNT
    # The direct path (a drain racing the mark) refuses it too.
    res = await _build(repo, subs, sync).execute(body, "test_signature")
    assert res["status"] == "quarantined"
    assert sync.calls == []
    assert subs.by_stripe_sub == {} and repo.by_id == {}
