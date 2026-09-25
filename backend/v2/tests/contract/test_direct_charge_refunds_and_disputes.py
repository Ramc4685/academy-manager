"""Refunds, dashboard-refund sync and disputes for DIRECT charges, on a real ``mongod``.

A non-house academy is charged on its OWN connected account, so everything
that follows the charge happens there too:

- an in-app refund is created ON that account (``stripe_account``), with no
  destination-charge flags; the house academy's refund request is unchanged;
- the account is persisted on the payment when the webhook confirms it, and
  the refund reads it from there (the account-aware fake answers
  ``resource_missing`` for a PaymentIntent used on the wrong account);
- a refund made in the academy's Stripe dashboard arrives as a Connect
  ``charge.refunded`` and converges the ledger once; the app's own refund
  echoing back is a no-op;
- ``charge.dispute.created`` / ``closed`` mark the payment disputed, show on
  Billing Health and ask for exactly one owner e-mail per (dispute, kind),
  without moving any money;
- another academy's account never touches this academy's rows.

Real stores throughout (ledger, payments, dedup, outbox, disputes, connected
accounts): the permissive-fake lesson of #664.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.v2.composition.billing_health import _open_disputes
from backend.v2.composition.parent import _ConnectAccountResolver
from backend.v2.contexts.billing.application.use_cases import (
    handle_webhook_event as handle_webhook_event_module,
)
from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.application.use_cases.issue_refund import (
    IssueRefund,
    IssueRefundCommand,
)
from backend.v2.contexts.billing.application.use_cases.record_payment_dispute import (
    RecordPaymentDispute,
    dispute_notice_event_id,
)
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
from backend.v2.contexts.billing.domain.errors import RefundFailed, StripeAccountMismatch
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_directory import (
    MongoConnectedAccountDirectory,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_dispute_repo import (
    MongoPaymentDisputeRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository
from backend.v2.contexts.billing.infrastructure.mongo_stripe_dedup import MongoStripeEventDedup
from backend.v2.shared.events import MongoOutbox
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.application.test_webhook_handler import (
    FakeSubscriptionRepo,
    _ledger_invoice,
)

HOUSE = "acad_house"
ACAD_A = "acad_a"
ACAD_B = "acad_b"
ACCT_A = "acct_owned_by_a"
ACCT_B = "acct_owned_by_b"
PARENT = "parent-1"


@pytest.fixture(autouse=True)
def _silence_alerts(monkeypatch) -> list[str]:
    alerts: list[str] = []
    monkeypatch.setattr(
        handle_webhook_event_module,
        "capture_message",
        lambda msg, **_: alerts.append(msg) or True,
    )
    return alerts


class _World:
    def __init__(self, real_db: Any) -> None:
        self.db = real_db
        self.stripe = FakeStripeGateway()
        self.accounts = MongoConnectedAccountRepository(real_db)
        self.ledger = MongoBillingLedgerRepository(real_db)
        self.payments = MongoPaymentRepository(real_db)
        self.disputes = MongoPaymentDisputeRepository(real_db)
        self.outbox = MongoOutbox(real_db)

    async def seed_accounts(self) -> None:
        for academy_id, acct in ((ACAD_A, ACCT_A), (ACAD_B, ACCT_B)):
            with tenant_scope(academy_id):
                await self.accounts.upsert(
                    ConnectedAccount.new(academy_id=academy_id, stripe_account_id=acct)
                )

    def handler(
        self, academy_id: str, *, tenancy_mode: str = "multi_academy"
    ) -> HandleWebhookEvent:
        return HandleWebhookEvent(
            stripe=self.stripe,
            dedup=MongoStripeEventDedup(self.db),
            payments=self.payments,
            subscriptions=FakeSubscriptionRepo(),
            billing_ledger=self.ledger,
            outbox=self.outbox,
            academy_id=academy_id,
            connected_accounts=_ConnectAccountResolver(
                self.accounts, academy_id, directory=MongoConnectedAccountDirectory(self.db)
            ),
            payment_disputes=self.disputes,
            tenancy_mode=tenancy_mode,
        )

    def refunder(self) -> IssueRefund:
        return IssueRefund(
            payment_repo=self.payments,
            stripe=self.stripe,
            outbox=self.outbox,
            idempotency_store=MongoIdempotencyStore(self.db),
        )

    async def deliver(self, academy_id: str, event: dict[str, Any], **kw: Any) -> dict[str, Any]:
        """Stripe -> the boot endpoint, then the drain of the academy the event
        must belong to. A Connect event reaches another academy's endpoint
        (ACAD_A's) and is attributed by its account; a platform event is the
        house deployment's own (single_academy)."""
        boot = ACAD_A if event.get("account") else academy_id
        await self.handler(boot, **kw).accept(json.dumps(event).encode(), "test_signature")
        return await self.handler(academy_id, **kw).process_next(processor_id="w")

    async def autopay_payment(self, academy_id: str, *, account: str | None) -> str:
        """An autopay charge, confirmed by its webhook: returns the PI id."""
        with tenant_scope(academy_id):
            await self.ledger.create_invoice(
                _ledger_invoice(invoice_id=f"inv-{academy_id}", academy_id=academy_id),
                lines=[],
                idempotency_key=f"inv-key-{academy_id}",
            )
        customer, pm = f"cus_{academy_id}", f"pm_{academy_id}"
        self.stripe.seed_saved_card(
            academy_id=academy_id,
            parent_id=PARENT,
            customer_id=customer,
            payment_method_id=pm,
            stripe_account=account,
        )
        pi_id, _, _ = await self.stripe.create_off_session_payment_intent(
            amount_cents=10_000,
            currency="usd",
            customer_id=customer,
            payment_method_id=pm,
            idempotency_key=f"autopay:{academy_id}",
            metadata={
                "source": "autopay",
                "invoice_id": f"inv-{academy_id}",
                "academy_id": academy_id,
                "parent_id": "parent-from-invoice",
            },
            **({"stripe_account": account} if account else {}),
        )
        event: dict[str, Any] = {
            "id": f"evt_pi_{pi_id}",
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": pi_id}},
        }
        if account:
            event["account"] = account
        result = await self.deliver(
            academy_id, event, tenancy_mode="multi_academy" if account else "single_academy"
        )
        assert result["processed"] is True, result
        return pi_id

    async def ledger_row(self, academy_id: str, pi_id: str) -> dict[str, Any]:
        row = await self.db["ledger_payments"].find_one(
            {"academy_id": academy_id, "stripe_payment_intent_id": pi_id}
        )
        assert row is not None
        return row

    async def outbox_names(self, academy_id: str) -> list[str]:
        return [
            doc["name"] async for doc in self.db["outbox_events"].find({"academy_id": academy_id})
        ]


def _refunded(pi_id: str, amount_refunded: int, *, account: str | None, n: int = 1) -> dict:
    event: dict[str, Any] = {
        "id": f"evt_refunded_{pi_id}_{amount_refunded}_{n}",
        "type": "charge.refunded",
        "data": {
            "object": {
                "id": f"ch_{pi_id}",
                "object": "charge",
                "payment_intent": pi_id,
                "amount": 10_000,
                "amount_refunded": amount_refunded,
            }
        },
    }
    if account:
        event["account"] = account
    return event


def _dispute_event(
    pi_id: str, *, kind: str, status: str, account: str | None, dispute_id: str = "dp_1", n: int = 1
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": f"evt_dispute_{dispute_id}_{kind}_{n}",
        "type": f"charge.dispute.{kind}",
        "data": {
            "object": {
                "id": dispute_id,
                "object": "dispute",
                "amount": 10_000,
                "currency": "usd",
                "charge": f"ch_{pi_id}",
                "payment_intent": pi_id,
                "reason": "fraudulent",
                "status": status,
                "created": 1_790_000_000,
                "evidence_details": {"due_by": 1_790_900_000},
                "metadata": {},
            }
        },
    }
    if account:
        event["account"] = account
    return event


# --- the account is persisted, and refunds go there -----------------------------


async def test_direct_charge_payment_records_its_account_and_refunds_on_it(real_db) -> None:
    world = _World(real_db)
    await world.seed_accounts()
    pi_id = await world.autopay_payment(ACAD_A, account=ACCT_A)

    row = await world.ledger_row(ACAD_A, pi_id)
    assert row["stripe_account_id"] == ACCT_A

    with tenant_scope(ACAD_A):
        result = await world.refunder().execute(
            IssueRefundCommand(
                payment_id=row["payment_id"], amount_cents=4_000, idempotency_key="r1"
            )
        )

    request = world.stripe.refund_requests[-1]
    assert request["stripe_account"] == ACCT_A
    assert world.stripe.account_of(result.stripe_refund_id) == ACCT_A
    row = await world.ledger_row(ACAD_A, pi_id)
    assert row["refunded_cents"] == 4_000
    assert row["status"] == "partially_refunded"


async def test_house_payment_and_refund_request_are_unchanged(real_db) -> None:
    world = _World(real_db)
    pi_id = await world.autopay_payment(HOUSE, account=None)

    row = await world.ledger_row(HOUSE, pi_id)
    # A platform payment keeps exactly the row shape it always had.
    assert "stripe_account_id" not in row

    with tenant_scope(HOUSE):
        await world.refunder().execute(
            IssueRefundCommand(
                payment_id=row["payment_id"], amount_cents=None, idempotency_key="r1"
            )
        )
    request = world.stripe.refund_requests[-1]
    assert set(request) == {"payment_intent_id", "amount_cents", "idempotency_key"}
    assert request["payment_intent_id"] == pi_id
    assert request["amount_cents"] == 10_000
    assert world.stripe.account_of(world.stripe.refunds[-1]["refund_id"]) is None


async def test_refund_without_the_recorded_account_fails_like_stripe(real_db) -> None:
    """Why the account must be persisted: the same PaymentIntent refunded on
    the platform is ``resource_missing`` on Stripe (and in the fake)."""
    world = _World(real_db)
    await world.seed_accounts()
    pi_id = await world.autopay_payment(ACAD_A, account=ACCT_A)
    await real_db["ledger_payments"].update_one(
        {"academy_id": ACAD_A, "stripe_payment_intent_id": pi_id},
        {"$unset": {"stripe_account_id": ""}},
    )
    row = await world.ledger_row(ACAD_A, pi_id)

    with tenant_scope(ACAD_A), pytest.raises(RefundFailed):
        await world.refunder().execute(
            IssueRefundCommand(payment_id=row["payment_id"], amount_cents=100, idempotency_key="r1")
        )
    assert world.stripe.refunds == []


async def test_another_academy_cannot_refund_the_payment(real_db) -> None:
    world = _World(real_db)
    await world.seed_accounts()
    pi_id = await world.autopay_payment(ACAD_A, account=ACCT_A)
    row = await world.ledger_row(ACAD_A, pi_id)

    with tenant_scope(ACAD_B), pytest.raises(Exception, match="no such payment"):
        await world.refunder().execute(
            IssueRefundCommand(payment_id=row["payment_id"], amount_cents=100, idempotency_key="r1")
        )
    assert world.stripe.refunds == []


# --- dashboard refunds sync back ----------------------------------------------------


async def test_dashboard_refund_via_connect_updates_the_ledger_once(real_db) -> None:
    world = _World(real_db)
    await world.seed_accounts()
    pi_id = await world.autopay_payment(ACAD_A, account=ACCT_A)

    result = await world.deliver(ACAD_A, _refunded(pi_id, 2_500, account=ACCT_A))
    assert result["processed"] is True, result
    row = await world.ledger_row(ACAD_A, pi_id)
    assert row["refunded_cents"] == 2_500
    assert row["status"] == "partially_refunded"
    assert (await world.outbox_names(ACAD_A)).count("Billing.PaymentRefunded") == 1

    # Stripe redelivers the same event, then sends a second event for the
    # same cumulative state: both converge, nothing is counted twice.
    await world.deliver(ACAD_A, _refunded(pi_id, 2_500, account=ACCT_A))
    await world.deliver(ACAD_A, _refunded(pi_id, 2_500, account=ACCT_A, n=2))
    row = await world.ledger_row(ACAD_A, pi_id)
    assert row["refunded_cents"] == 2_500
    assert (await world.outbox_names(ACAD_A)).count("Billing.PaymentRefunded") == 1


async def test_app_refund_echo_does_not_double_refund(real_db) -> None:
    world = _World(real_db)
    await world.seed_accounts()
    pi_id = await world.autopay_payment(ACAD_A, account=ACCT_A)
    row = await world.ledger_row(ACAD_A, pi_id)
    with tenant_scope(ACAD_A):
        await world.refunder().execute(
            IssueRefundCommand(
                payment_id=row["payment_id"], amount_cents=None, idempotency_key="r1"
            )
        )

    # The app-initiated refund comes back as charge.refunded on the account.
    await world.deliver(ACAD_A, _refunded(pi_id, 10_000, account=ACCT_A))
    row = await world.ledger_row(ACAD_A, pi_id)
    assert row["refunded_cents"] == 10_000
    assert row["status"] == "refunded"
    assert (await world.outbox_names(ACAD_A)).count("Billing.PaymentRefunded") == 1
    assert len(world.stripe.refunds) == 1


async def test_refund_event_from_another_academys_account_touches_nothing(real_db) -> None:
    world = _World(real_db)
    await world.seed_accounts()
    pi_id = await world.autopay_payment(ACAD_A, account=ACCT_A)

    # B's account names A's PaymentIntent: attributed to B, drained by B,
    # where the tenant-scoped ledger has no such payment.
    result = await world.deliver(ACAD_B, _refunded(pi_id, 10_000, account=ACCT_B))
    assert result["processed"] is True, result
    row = await world.ledger_row(ACAD_A, pi_id)
    assert row["refunded_cents"] == 0
    assert row["status"] == "succeeded"
    # A's drain never sees B's event.
    assert (await world.handler(ACAD_A).process_next(processor_id="w"))["empty"] is True


async def test_refund_event_whose_account_contradicts_the_payment_is_quarantined(
    real_db, _silence_alerts
) -> None:
    world = _World(real_db)
    await world.seed_accounts()
    pi_id = await world.autopay_payment(ACAD_A, account=ACCT_A)
    # A mis-recorded account on A's own payment: the event's account wins
    # attribution, but the contradiction is never projected.
    await real_db["ledger_payments"].update_one(
        {"academy_id": ACAD_A, "stripe_payment_intent_id": pi_id},
        {"$set": {"stripe_account_id": "acct_someone_else"}},
    )
    result = await world.deliver(ACAD_A, _refunded(pi_id, 10_000, account=ACCT_A))
    assert result.get("status") == "quarantined", result
    assert "stripe account mismatch" in result["error"]
    assert (await world.ledger_row(ACAD_A, pi_id))["refunded_cents"] == 0


# --- disputes --------------------------------------------------------------------------


async def test_dispute_created_marks_the_payment_and_asks_for_one_owner_notice(real_db) -> None:
    world = _World(real_db)
    await world.seed_accounts()
    pi_id = await world.autopay_payment(ACAD_A, account=ACCT_A)

    event = _dispute_event(pi_id, kind="created", status="needs_response", account=ACCT_A)
    result = await world.deliver(ACAD_A, event)
    assert result["processed"] is True, result

    row = await world.ledger_row(ACAD_A, pi_id)
    assert row["dispute_id"] == "dp_1"
    assert row["dispute_status"] == "needs_response"
    assert row["dispute_reason"] == "fraudulent"
    assert row["dispute_amount_cents"] == 10_000
    assert row["dispute_outcome"] is None
    # No platform-side adjustment: money fields are untouched.
    assert row["status"] == "succeeded"
    assert row["refunded_cents"] == 0
    assert row["amount_cents"] == 10_000

    with tenant_scope(ACAD_A):
        dispute = await world.disputes.get("dp_1")
        health = await _open_disputes(world.disputes)
    assert dispute is not None and dispute.is_open
    assert dispute.stripe_account_id == ACCT_A
    assert dispute.payment_id == row["payment_id"]
    assert health["count"] == 1
    assert health["rows"][0]["dispute_id"] == "dp_1"

    notices = [
        doc
        async for doc in real_db["outbox_events"].find(
            {"name": "Billing.PaymentDisputeNoticeRequested"}
        )
    ]
    assert [n["event_id"] for n in notices] == [
        dispute_notice_event_id(academy_id=ACAD_A, dispute_id="dp_1", kind="opened")
    ]
    assert notices[0]["academy_id"] == ACAD_A

    # A redelivery and a second "created" event for the same dispute: still
    # one notice.
    await world.deliver(ACAD_A, event)
    await world.deliver(
        ACAD_A, _dispute_event(pi_id, kind="created", status="needs_response", account=ACCT_A, n=2)
    )
    assert (await world.outbox_names(ACAD_A)).count("Billing.PaymentDisputeNoticeRequested") == 1


async def test_dispute_closed_records_the_outcome_and_a_late_created_does_not_reopen(
    real_db,
) -> None:
    world = _World(real_db)
    await world.seed_accounts()
    pi_id = await world.autopay_payment(ACAD_A, account=ACCT_A)

    await world.deliver(
        ACAD_A, _dispute_event(pi_id, kind="created", status="needs_response", account=ACCT_A)
    )
    await world.deliver(ACAD_A, _dispute_event(pi_id, kind="closed", status="lost", account=ACCT_A))
    # Out of order: another "created" after the close.
    await world.deliver(
        ACAD_A,
        _dispute_event(pi_id, kind="created", status="needs_response", account=ACCT_A, n=3),
    )

    with tenant_scope(ACAD_A):
        dispute = await world.disputes.get("dp_1")
        health = await _open_disputes(world.disputes)
    assert dispute is not None
    assert dispute.outcome == "lost" and not dispute.is_open
    assert health["count"] == 0
    row = await world.ledger_row(ACAD_A, pi_id)
    assert row["dispute_status"] == "lost"
    assert row["dispute_outcome"] == "lost"
    # A lost dispute is the academy's loss on its own account: no ledger money moves.
    assert row["status"] == "succeeded"
    assert row["refunded_cents"] == 0
    names = await world.outbox_names(ACAD_A)
    assert names.count("Billing.PaymentDisputeNoticeRequested") == 2
    ids = {
        doc["event_id"]
        async for doc in real_db["outbox_events"].find(
            {"name": "Billing.PaymentDisputeNoticeRequested"}
        )
    }
    assert ids == {
        dispute_notice_event_id(academy_id=ACAD_A, dispute_id="dp_1", kind="opened"),
        dispute_notice_event_id(academy_id=ACAD_A, dispute_id="dp_1", kind="closed"),
    }


async def test_dispute_from_another_academys_account_stays_in_that_academy(real_db) -> None:
    world = _World(real_db)
    await world.seed_accounts()
    pi_id = await world.autopay_payment(ACAD_A, account=ACCT_A)

    result = await world.deliver(
        ACAD_B, _dispute_event(pi_id, kind="created", status="needs_response", account=ACCT_B)
    )
    assert result["processed"] is True, result

    row = await world.ledger_row(ACAD_A, pi_id)
    assert "dispute_id" not in row
    with tenant_scope(ACAD_A):
        assert await world.disputes.get("dp_1") is None
        assert (await _open_disputes(world.disputes))["count"] == 0
    with tenant_scope(ACAD_B):
        b_dispute = await world.disputes.get("dp_1")
    # Recorded under B (its account is authoritative) without a payment match.
    assert b_dispute is not None and b_dispute.payment_id is None
    assert "Billing.PaymentDisputeNoticeRequested" not in await world.outbox_names(ACAD_A)


async def test_house_dispute_on_the_platform_is_recorded_without_an_account(real_db) -> None:
    world = _World(real_db)
    pi_id = await world.autopay_payment(HOUSE, account=None)

    event = _dispute_event(pi_id, kind="created", status="needs_response", account=None)
    await world.handler(HOUSE, tenancy_mode="single_academy").accept(
        json.dumps(event).encode(), "test_signature"
    )
    result = await world.handler(HOUSE, tenancy_mode="single_academy").process_next(
        processor_id="w"
    )
    assert result["processed"] is True, result

    with tenant_scope(HOUSE):
        dispute = await world.disputes.get("dp_1")
    assert dispute is not None
    assert dispute.stripe_account_id is None
    assert (await world.ledger_row(HOUSE, pi_id))["dispute_status"] == "needs_response"


async def test_dispute_account_contradicting_the_payment_is_refused(real_db) -> None:
    world = _World(real_db)
    await world.seed_accounts()
    pi_id = await world.autopay_payment(ACAD_A, account=ACCT_A)
    use_case = RecordPaymentDispute(
        disputes=world.disputes,
        payments=world.payments,
        ledger=world.ledger,
        outbox=world.outbox,
        academy_id=ACAD_A,
    )
    obj = _dispute_event(pi_id, kind="created", status="needs_response", account=None)["data"][
        "object"
    ]
    with tenant_scope(ACAD_A), pytest.raises(StripeAccountMismatch):
        await use_case.execute(obj, stripe_account_id="acct_not_the_payments")
    with tenant_scope(ACAD_A):
        assert await world.disputes.get("dp_1") is None
