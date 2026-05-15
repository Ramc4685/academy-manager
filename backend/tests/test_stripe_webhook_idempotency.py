"""Stripe webhook idempotency, charge.refunded, and checkout.session.expired tests.

Slice 1 of Phase 5 launch-blockers. Covers:
  1. Invalid signature returns 400 with no writes.
  2. Duplicate event id is idempotent (no double-apply).
  3. checkout.session.expired is handled without error and recorded.
  4. charge.refunded creates payment_refunds and updates payments.
  5. Duplicate charge.refunded event does not duplicate refund record.
  6. stripe_webhook_events unique index rejects duplicate event_id inserts.

Tests stub stripe.Webhook.construct_event so no real Stripe keys are needed.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "academy_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test")
os.environ.setdefault("STRIPE_API_KEY", "sk_test_dummy")
os.environ.setdefault("FIREBASE_AUTH_ENABLED", "false")

from mongomock_motor import AsyncMongoMockClient  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pymongo.errors import DuplicateKeyError  # noqa: E402

import db as db_module  # noqa: E402
from routers.billing_routes import router as billing_router  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mongo():
    """Fresh in-memory Mongo for each test, wired into the backend's get_db()."""
    client = AsyncMongoMockClient()
    fake_db = client["academy_test"]
    db_module._client = client
    db_module._db = fake_db
    # Create required indexes synchronously via asyncio.run
    asyncio.run(db_module.ensure_indexes())
    yield fake_db
    db_module._client = None
    db_module._db = None


@pytest.fixture
def app(mongo):
    application = FastAPI()
    application.include_router(billing_router, prefix="/api")
    return application


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


def _make_stripe_event(event_id: str, event_type: str, obj: dict) -> dict:
    """Build a minimal Stripe event dict."""
    return {
        "id": event_id,
        "type": event_type,
        "data": {"object": obj},
    }


def _patch_stripe_webhook(event_dict: dict):
    """Context manager that stubs stripe.Webhook.construct_event to return event_dict."""
    mock_stripe = MagicMock()
    mock_stripe.Webhook.construct_event.return_value = event_dict
    mock_stripe.api_key = "sk_test_dummy"
    return patch(
        "routers.billing_routes._configure_stripe",
        return_value=mock_stripe,
    )


def _post_webhook(client, event_dict: dict):
    """POST a fake webhook event, bypassing signature verification."""
    with _patch_stripe_webhook(event_dict):
        return client.post(
            "/api/webhook/stripe",
            content=b"fake-body",
            headers={"Stripe-Signature": "t=1,v1=abc"},
        )


# ---------------------------------------------------------------------------
# 1. Invalid signature returns 400 with no writes
# ---------------------------------------------------------------------------

class TestInvalidSignature:
    def test_invalid_signature_returns_400_and_no_writes(self, client, mongo):
        """A bogus Stripe-Signature must be rejected with 400 and leave all
        relevant collections empty."""
        mock_stripe = MagicMock()
        mock_stripe.Webhook.construct_event.side_effect = Exception("invalid sig")

        with patch("routers.billing_routes._configure_stripe", return_value=mock_stripe):
            r = client.post(
                "/api/webhook/stripe",
                content=b"bad-payload",
                headers={"Stripe-Signature": "t=1,v1=bogus"},
            )

        assert r.status_code == 400

        # No writes must have occurred in any tracked collection
        assert asyncio.run(mongo.stripe_webhook_events.count_documents({})) == 0
        assert asyncio.run(mongo.payments.count_documents({})) == 0
        assert asyncio.run(mongo.payment_transactions.count_documents({})) == 0


# ---------------------------------------------------------------------------
# 2. Duplicate event id is idempotent
# ---------------------------------------------------------------------------

class TestDuplicateEventIdempotency:
    def _seed_pending_payment(self, mongo, payment_id_str: str, session_id: str):
        """Seed a payment and a payment_transaction that would be marked paid
        by a checkout.session.completed event."""
        from bson import ObjectId
        oid = ObjectId(payment_id_str)
        now = datetime.now(timezone.utc).isoformat()
        asyncio.run(mongo.payments.insert_one({
            "_id": oid,
            "status": "pending",
            "final_amount": 50.0,
            "parent_user_id": "user_1",
            "student_id": "stu_1",
            "enrollment_id": None,
            "period": "2026-05",
            "payment_type": "one_off",
            "refunded_amount": 0,
            "refund_status": "none",
            "created_at": now,
        }))
        asyncio.run(mongo.payment_transactions.insert_one({
            "session_id": session_id,
            "payment_id": payment_id_str,
            "user_id": "user_1",
            "payment_status": "initiated",
            "status": "initiated",
            "created_at": now,
            "updated_at": now,
        }))

    def test_duplicate_event_id_is_idempotent(self, client, mongo):
        """Processing the same event id twice must only apply the payment once."""
        from bson import ObjectId
        payment_id_str = "5f43a0d88a1b2c0001000001"
        session_id = "cs_test_dup001"
        self._seed_pending_payment(mongo, payment_id_str, session_id)

        event_dict = _make_stripe_event(
            event_id="evt_dup001",
            event_type="checkout.session.completed",
            obj={
                "id": session_id,
                "payment_intent": "pi_dup001",
                "subscription": None,
                "mode": "payment",
                "metadata": {"payment_id": payment_id_str},
            },
        )

        # First delivery
        r1 = _post_webhook(client, event_dict)
        assert r1.status_code == 200

        pay_after_first = asyncio.run(
            mongo.payments.find_one({"_id": ObjectId(payment_id_str)})
        )
        assert pay_after_first["status"] == "paid"
        assert pay_after_first["stripe_payment_intent"] == "pi_dup001"

        webhook_evt = asyncio.run(
            mongo.stripe_webhook_events.find_one({"event_id": "evt_dup001"})
        )
        assert webhook_evt is not None
        assert webhook_evt["status"] == "processed"

        updated_at_first = pay_after_first.get("payment_date")

        # Second delivery (same event id)
        r2 = _post_webhook(client, event_dict)
        assert r2.status_code == 200
        assert r2.json().get("deduped") is True

        # Payment must not have been mutated a second time
        pay_after_second = asyncio.run(
            mongo.payments.find_one({"_id": ObjectId(payment_id_str)})
        )
        assert pay_after_second["payment_date"] == updated_at_first

        # Only one stripe_webhook_events record
        evt_count = asyncio.run(mongo.stripe_webhook_events.count_documents({"event_id": "evt_dup001"}))
        assert evt_count == 1


# ---------------------------------------------------------------------------
# 3. checkout.session.expired is handled and recorded
# ---------------------------------------------------------------------------

class TestCheckoutSessionExpired:
    def test_checkout_session_expired_marks_event_processed(self, client, mongo):
        """A checkout.session.expired event must be acknowledged without error
        and must create a processed record in stripe_webhook_events."""
        event_dict = _make_stripe_event(
            event_id="evt_expired001",
            event_type="checkout.session.expired",
            obj={"id": "cs_test_expired001"},
        )

        r = _post_webhook(client, event_dict)
        assert r.status_code == 200

        webhook_evt = asyncio.run(
            mongo.stripe_webhook_events.find_one({"event_id": "evt_expired001"})
        )
        assert webhook_evt is not None
        assert webhook_evt["status"] == "processed"
        assert webhook_evt["type"] == "checkout.session.expired"


# ---------------------------------------------------------------------------
# 4. charge.refunded creates payment_refunds and updates payments
# ---------------------------------------------------------------------------

class TestChargeRefunded:
    def _seed_paid_payment(self, mongo, payment_id_str: str, stripe_pi: str, final_amount: float = 100.0):
        from bson import ObjectId
        now = datetime.now(timezone.utc).isoformat()
        asyncio.run(mongo.payments.insert_one({
            "_id": ObjectId(payment_id_str),
            "status": "paid",
            "final_amount": final_amount,
            "refunded_amount": 0,
            "refund_status": "none",
            "stripe_payment_intent": stripe_pi,
            "parent_user_id": "user_2",
            "student_id": "stu_2",
            "period": "2026-05",
            "payment_type": "one_off",
            "created_at": now,
        }))

    def test_charge_refunded_creates_payment_refund_record(self, client, mongo):
        """A charge.refunded event must create a payment_refunds doc and
        update refunded_amount / refund_status on the parent payments doc."""
        from bson import ObjectId
        payment_id_str = "5f43a0d88a1b2c0001000002"
        stripe_pi = "pi_refund001"
        refund_amount_cents = 3000  # $30 partial refund

        self._seed_paid_payment(mongo, payment_id_str, stripe_pi, final_amount=100.0)

        event_dict = _make_stripe_event(
            event_id="evt_refund001",
            event_type="charge.refunded",
            obj={
                "payment_intent": stripe_pi,
                "amount_refunded": refund_amount_cents,
                "refunds": {
                    "data": [
                        {
                            "id": "re_001",
                            "amount": refund_amount_cents,
                            "reason": "requested_by_customer",
                        }
                    ]
                },
            },
        )

        r = _post_webhook(client, event_dict)
        assert r.status_code == 200

        # Exactly one payment_refunds record
        refund_docs = list(asyncio.run(mongo.payment_refunds.find({}).to_list(length=100)))
        assert len(refund_docs) == 1
        refund_doc = refund_docs[0]
        assert refund_doc["stripe_refund_id"] == "re_001"
        assert refund_doc["payment_id"] == payment_id_str
        assert refund_doc["amount"] == pytest.approx(30.0)
        assert refund_doc["reason"] == "requested_by_customer"
        assert "created_at" in refund_doc

        # Parent payment updated
        pay = asyncio.run(mongo.payments.find_one({"_id": ObjectId(payment_id_str)}))
        assert pay["refunded_amount"] == pytest.approx(30.0)
        assert pay["refund_status"] == "partially_refunded"
        assert pay["status"] == "partially_refunded"

    def test_charge_refunded_full_refund_sets_refunded_status(self, client, mongo):
        """When refunded_amount >= final_amount, payment status must be refunded."""
        from bson import ObjectId
        payment_id_str = "5f43a0d88a1b2c0001000003"
        stripe_pi = "pi_refund002"

        self._seed_paid_payment(mongo, payment_id_str, stripe_pi, final_amount=50.0)

        event_dict = _make_stripe_event(
            event_id="evt_refund002",
            event_type="charge.refunded",
            obj={
                "payment_intent": stripe_pi,
                "amount_refunded": 5000,  # $50 — full refund
                "refunds": {
                    "data": [
                        {
                            "id": "re_002",
                            "amount": 5000,
                            "reason": "duplicate",
                        }
                    ]
                },
            },
        )

        r = _post_webhook(client, event_dict)
        assert r.status_code == 200

        pay = asyncio.run(mongo.payments.find_one({"_id": ObjectId(payment_id_str)}))
        assert pay["refund_status"] == "refunded"
        assert pay["status"] == "refunded"
        assert pay["refunded_amount"] == pytest.approx(50.0)

    def test_charge_refunded_falls_back_to_payment_transaction_intent(self, client, mongo):
        """One-time checkout stores payment_intent on payment_transactions;
        refunds must still resolve the parent payment."""
        from bson import ObjectId
        payment_id_str = "5f43a0d88a1b2c0001000005"
        stripe_pi = "pi_tx_only_refund"
        now = datetime.now(timezone.utc).isoformat()
        asyncio.run(mongo.payments.insert_one({
            "_id": ObjectId(payment_id_str),
            "status": "paid",
            "final_amount": 75.0,
            "refunded_amount": 0,
            "refund_status": "none",
            "parent_user_id": "user_4",
            "student_id": "stu_4",
            "period": "2026-05",
            "payment_type": "one_off",
            "created_at": now,
        }))
        asyncio.run(mongo.payment_transactions.insert_one({
            "session_id": "cs_tx_only",
            "payment_id": payment_id_str,
            "stripe_payment_intent": stripe_pi,
            "payment_status": "paid",
            "status": "complete",
            "created_at": now,
            "updated_at": now,
        }))

        event_dict = _make_stripe_event(
            event_id="evt_refund_tx_only",
            event_type="charge.refunded",
            obj={
                "payment_intent": stripe_pi,
                "amount_refunded": 2500,
                "refunds": {
                    "data": [
                        {
                            "id": "re_tx_only",
                            "amount": 2500,
                            "reason": "requested_by_customer",
                        }
                    ]
                },
            },
        )

        r = _post_webhook(client, event_dict)
        assert r.status_code == 200

        pay = asyncio.run(mongo.payments.find_one({"_id": ObjectId(payment_id_str)}))
        assert pay["stripe_payment_intent"] == stripe_pi
        assert pay["refunded_amount"] == pytest.approx(25.0)
        assert pay["refund_status"] == "partially_refunded"
        assert pay["status"] == "partially_refunded"

    def test_charge_refunded_no_matching_payment_is_noop(self, client, mongo):
        """If no payments doc matches the payment_intent, the event must still
        be marked processed without raising an error."""
        event_dict = _make_stripe_event(
            event_id="evt_refund_noop",
            event_type="charge.refunded",
            obj={
                "payment_intent": "pi_unknown_xyz",
                "amount_refunded": 1000,
                "refunds": {
                    "data": [{"id": "re_noop", "amount": 1000, "reason": None}]
                },
            },
        )

        r = _post_webhook(client, event_dict)
        assert r.status_code == 200

        webhook_evt = asyncio.run(
            mongo.stripe_webhook_events.find_one({"event_id": "evt_refund_noop"})
        )
        assert webhook_evt is not None
        assert webhook_evt["status"] == "processed"
        assert asyncio.run(mongo.payment_refunds.count_documents({})) == 0


# ---------------------------------------------------------------------------
# 5. Duplicate charge.refunded does not duplicate refund record
# ---------------------------------------------------------------------------

class TestChargeRefundedDuplication:
    def _seed_paid_payment(self, mongo, payment_id_str: str, stripe_pi: str):
        from bson import ObjectId
        now = datetime.now(timezone.utc).isoformat()
        asyncio.run(mongo.payments.insert_one({
            "_id": ObjectId(payment_id_str),
            "status": "paid",
            "final_amount": 80.0,
            "refunded_amount": 0,
            "refund_status": "none",
            "stripe_payment_intent": stripe_pi,
            "parent_user_id": "user_3",
            "student_id": "stu_3",
            "period": "2026-05",
            "payment_type": "one_off",
            "created_at": now,
        }))

    def test_charge_refunded_duplicate_event_does_not_duplicate_refund(self, client, mongo):
        """The same charge.refunded event id sent twice must yield exactly ONE
        payment_refunds document."""
        payment_id_str = "5f43a0d88a1b2c0001000004"
        stripe_pi = "pi_refund003"
        self._seed_paid_payment(mongo, payment_id_str, stripe_pi)

        event_dict = _make_stripe_event(
            event_id="evt_refund_dup",
            event_type="charge.refunded",
            obj={
                "payment_intent": stripe_pi,
                "amount_refunded": 2000,
                "refunds": {
                    "data": [{"id": "re_dup", "amount": 2000, "reason": None}]
                },
            },
        )

        r1 = _post_webhook(client, event_dict)
        assert r1.status_code == 200

        r2 = _post_webhook(client, event_dict)
        assert r2.status_code == 200
        assert r2.json().get("deduped") is True

        refund_count = asyncio.run(mongo.payment_refunds.count_documents({}))
        assert refund_count == 1


# ---------------------------------------------------------------------------
# 6. stripe_webhook_events unique index rejects duplicate event_id
# ---------------------------------------------------------------------------

class TestStripeWebhookEventsUniqueIndex:
    def test_stripe_webhook_events_unique_constraint(self, mongo):
        """Inserting two stripe_webhook_events with the same event_id must
        raise DuplicateKeyError from mongomock."""
        now = datetime.now(timezone.utc).isoformat()
        asyncio.run(mongo.stripe_webhook_events.insert_one({
            "event_id": "evt_unique_test",
            "type": "checkout.session.completed",
            "status": "processed",
            "received_at": now,
            "processed_at": now,
        }))

        with pytest.raises(DuplicateKeyError):
            asyncio.run(mongo.stripe_webhook_events.insert_one({
                "event_id": "evt_unique_test",
                "type": "checkout.session.completed",
                "status": "processed",
                "received_at": now,
                "processed_at": now,
            }))
