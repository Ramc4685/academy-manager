"""Connect webhooks from direct-charge academies, against a real ``mongod``.

Every non-house academy is charged on its OWN connected account, so its
payment events reach the one boot-academy ``/webhooks/stripe`` endpoint as
Connect events carrying a top-level ``account``. These tests drive the real
stores (``MongoStripeEventDedup``, ``MongoConnectedAccountRepository``, the
platform-scoped ``MongoConnectedAccountDirectory`` and the composition
``_ConnectAccountResolver``) with the migrations' real indexes, and pin:

- an event for academy B's account, received by academy A's handler, is
  stored under B, drained only by B, and changes only B's rows;
- ``metadata.academy_id`` that disagrees with the account's owner is
  quarantined at ingest, never trusted over the account;
- an unknown account is quarantined by the processing guard;
- a row mis-stamped under the wrong academy is quarantined, not projected;
- house-academy platform events (no ``account``) attribute exactly as before.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.v2.composition.parent import _ConnectAccountResolver
from backend.v2.contexts.billing.application.use_cases import (
    handle_webhook_event as handle_webhook_event_module,
)
from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    QUARANTINE_ACCOUNT_METADATA_CONFLICT,
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_directory import (
    MongoConnectedAccountDirectory,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_stripe_dedup import MongoStripeEventDedup
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.application.test_webhook_handler import (
    FakeOutbox,
    FakePaymentRepo,
    FakeSubscriptionRepo,
)

HOUSE = "acad_house"
ACAD_A = "acad_a"
ACAD_B = "acad_b"
ACCT_A = "acct_owned_by_a"
ACCT_B = "acct_owned_by_b"


@pytest.fixture(autouse=True)
def _silence_alerts(monkeypatch) -> list[str]:
    alerts: list[str] = []
    monkeypatch.setattr(
        handle_webhook_event_module,
        "capture_message",
        lambda msg, **_: alerts.append(msg) or True,
    )
    return alerts


async def _seed(real_db: Any) -> MongoConnectedAccountRepository:
    repo = MongoConnectedAccountRepository(real_db)
    for academy_id, acct in ((ACAD_A, ACCT_A), (ACAD_B, ACCT_B)):
        with tenant_scope(academy_id):
            await repo.upsert(ConnectedAccount.new(academy_id=academy_id, stripe_account_id=acct))
    return repo


def _handler(
    real_db: Any,
    repo: MongoConnectedAccountRepository,
    academy_id: str,
    *,
    payments: FakePaymentRepo | None = None,
    tenancy_mode: str = "multi_academy",
) -> HandleWebhookEvent:
    return HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=MongoStripeEventDedup(real_db),
        payments=payments or FakePaymentRepo(),
        subscriptions=FakeSubscriptionRepo(),
        outbox=FakeOutbox(),
        academy_id=academy_id,
        connected_accounts=_ConnectAccountResolver(
            repo, academy_id, directory=MongoConnectedAccountDirectory(real_db)
        ),
        tenancy_mode=tenancy_mode,
    )


def _account_updated(event_id: str, acct: str) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": "account.updated",
            "account": acct,
            "data": {
                "object": {
                    "id": acct,
                    "object": "account",
                    "charges_enabled": True,
                    "payouts_enabled": True,
                    "capabilities": {"card_payments": "active"},
                }
            },
        }
    ).encode()


async def _stored(real_db: Any, event_id: str) -> dict[str, Any]:
    row = await real_db["stripe_webhook_events"].find_one({"event_id": event_id})
    assert row is not None
    return row


async def _account(repo: MongoConnectedAccountRepository, academy_id: str) -> ConnectedAccount:
    with tenant_scope(academy_id):
        account = await repo.get_for_academy()
    assert account is not None
    return account


# --- the platform-scoped directory -------------------------------------------


async def test_directory_resolves_any_academys_account_without_a_tenant_scope(real_db) -> None:
    repo = await _seed(real_db)
    with tenant_scope(ACAD_B):
        await repo.mark_disconnected(stripe_account_id=ACCT_B)
    directory = MongoConnectedAccountDirectory(real_db)

    assert await directory.owner_academy_id(ACCT_A) == ACAD_A
    # Disconnected accounts still resolve: refunds and disputes keep coming.
    assert await directory.owner_academy_id(ACCT_B) == ACAD_B
    assert await directory.owner_academy_id("acct_nobody") is None
    assert await directory.owner_academy_id("") is None


async def test_directory_lookup_uses_the_unique_stripe_account_index(real_db) -> None:
    await _seed(real_db)
    plan = await real_db.command(
        {
            "explain": {
                "find": "academy_connected_accounts",
                "filter": {"stripe_account_id": ACCT_B},
                "projection": {"_id": 0, "academy_id": 1},
            },
            "verbosity": "queryPlanner",
        }
    )
    assert "academy_connected_accounts_stripe_account" in json.dumps(plan, default=str)
    index_info = await real_db["academy_connected_accounts"].index_information()
    assert index_info["academy_connected_accounts_stripe_account"].get("unique") is True


# --- ingest + drain ------------------------------------------------------------


async def test_event_for_b_account_is_stored_under_b_and_only_touches_b(real_db) -> None:
    repo = await _seed(real_db)
    handler_a = _handler(real_db, repo, ACAD_A)  # the boot academy serves the endpoint
    handler_b = _handler(real_db, repo, ACAD_B)

    res = await handler_a.accept(_account_updated("evt_b_updated", ACCT_B), "test_signature")

    assert res == {"received": True, "stored": True, "type": "account.updated"}
    assert (await _stored(real_db, "evt_b_updated"))["academy_id"] == ACAD_B
    assert (await handler_a.process_next(processor_id="worker-a")).get("empty") is True
    processed = await handler_b.process_next(processor_id="worker-b")
    assert processed["processed"] is True, processed
    assert (await _account(repo, ACAD_B)).status == "active"
    untouched = await _account(repo, ACAD_A)
    assert untouched.status == "pending"
    assert untouched.charges_enabled is False


async def test_metadata_naming_another_academy_is_quarantined_at_ingest(
    real_db, _silence_alerts
) -> None:
    """A Connect event on B's account whose metadata claims academy A: the
    account wins, the event is quarantined under B, and no processor projects
    it — neither A (whose data the metadata points at) nor B."""
    repo = await _seed(real_db)
    payments_a = FakePaymentRepo()
    payments_b = FakePaymentRepo()
    handler_a = _handler(real_db, repo, ACAD_A, payments=payments_a)
    handler_b = _handler(real_db, repo, ACAD_B, payments=payments_b)
    spoofed = json.dumps(
        {
            "id": "evt_spoofed",
            "type": "checkout.session.completed",
            "account": ACCT_B,
            "data": {
                "object": {
                    "id": "cs_spoofed",
                    "mode": "payment",
                    "payment_status": "paid",
                    "metadata": {"academy_id": ACAD_A, "parent_id": "p1"},
                }
            },
        }
    ).encode()

    res = await handler_a.accept(spoofed, "test_signature")

    assert res["status"] == "quarantined"
    row = await _stored(real_db, "evt_spoofed")
    assert row["academy_id"] == ACAD_B
    assert row["status"] == "quarantined"
    assert row["quarantine_reason"] == QUARANTINE_ACCOUNT_METADATA_CONFLICT
    assert (await handler_a.process_next(processor_id="worker-a")).get("empty") is True
    assert (await handler_b.process_next(processor_id="worker-b")).get("empty") is True
    assert payments_a.by_id == {} and payments_b.by_id == {}
    assert len(_silence_alerts) == 1 and "evt_spoofed" in _silence_alerts[0]


async def test_metadata_agreeing_with_the_account_owner_is_not_quarantined(real_db) -> None:
    repo = await _seed(real_db)
    handler_a = _handler(real_db, repo, ACAD_A)
    body = json.dumps(
        {
            "id": "evt_agree",
            "type": "checkout.session.expired",
            "account": ACCT_B,
            "data": {"object": {"id": "cs_b", "metadata": {"academy_id": ACAD_B}}},
        }
    ).encode()

    await handler_a.accept(body, "test_signature")

    row = await _stored(real_db, "evt_agree")
    assert (row["academy_id"], row["status"]) == (ACAD_B, "received")


async def test_unknown_account_is_quarantined_by_the_processing_guard(real_db) -> None:
    repo = await _seed(real_db)
    handler_a = _handler(real_db, repo, ACAD_A)

    await handler_a.accept(_account_updated("evt_unknown", "acct_nobody"), "test_signature")
    assert (await _stored(real_db, "evt_unknown"))["academy_id"] == ACAD_A
    result = await handler_a.process_next(processor_id="worker-a")

    assert result["status"] == "quarantined"
    assert "unknown connected account" in result["error"]
    assert (await _stored(real_db, "evt_unknown"))["status"] == "quarantined"
    assert (await _account(repo, ACAD_A)).status == "pending"


async def test_row_stamped_under_the_wrong_academy_is_quarantined_not_projected(
    real_db,
) -> None:
    """A row for B's account sitting in A's bucket (stamped before this
    routing existed): A's processor must refuse it, and B's row stays as is."""
    repo = await _seed(real_db)
    handler_a = _handler(real_db, repo, ACAD_A)
    body = _account_updated("evt_legacy_misstamped", ACCT_B)
    await MongoStripeEventDedup(real_db).store_received(
        json.loads(body), raw_payload=body, academy_id=ACAD_A
    )

    result = await handler_a.process_next(processor_id="worker-a")

    assert result["status"] == "quarantined"
    assert "academy mismatch" in result["error"]
    assert (await _account(repo, ACAD_B)).status == "pending"
    assert (await _account(repo, ACAD_A)).status == "pending"


# --- house academy platform events are unchanged -------------------------------


async def test_house_platform_events_attribute_exactly_as_before(real_db) -> None:
    repo = await _seed(real_db)
    single = _handler(real_db, repo, HOUSE, tenancy_mode="single_academy")
    by_metadata = json.dumps(
        {
            "id": "evt_house_meta",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_house", "metadata": {"academy_id": HOUSE}}},
        }
    ).encode()
    unmarked = json.dumps(
        {
            "id": "evt_house_plain",
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_house"}},
        }
    ).encode()

    first = await single.accept(by_metadata, "test_signature")
    second = await single.accept(unmarked, "test_signature")

    assert first == {"received": True, "stored": True, "type": "checkout.session.completed"}
    assert second == {"received": True, "stored": True, "type": "payment_intent.succeeded"}
    for event_id in ("evt_house_meta", "evt_house_plain"):
        row = await _stored(real_db, event_id)
        assert (row["academy_id"], row["status"], row["stripe_account"]) == (
            HOUSE,
            "received",
            None,
        )
