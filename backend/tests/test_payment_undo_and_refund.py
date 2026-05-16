"""Phase 5 Slice 4: Stripe-paid undo-paid gating and admin refund endpoint tests.

Covers:
  1-8.  Undo-paid endpoint now blocks Stripe-linked payments with 409.
  9-15. Admin refund endpoint at POST /api/admin/payments/{id}/refund.

Tests use mongomock-motor + patched auth + FastAPI TestClient.
No live Stripe or Mongo connection required.
"""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "academy_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("STRIPE_API_KEY", "sk_test_dummy")
os.environ["FIREBASE_AUTH_ENABLED"] = "false"

from mongomock_motor import AsyncMongoMockClient  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from bson import ObjectId  # noqa: E402

import db as db_module  # noqa: E402
import auth as auth_module  # noqa: E402


# ---------------------------------------------------------------------------
# User stubs
# ---------------------------------------------------------------------------

ADMIN_USER = {
    "id": "admin-user-id-001",
    "email": "admin@example.com",
    "role": "admin",
    "name": "Test Admin",
}

PARENT_USER = {
    "id": "parent-user-id-001",
    "email": "parent@example.com",
    "role": "parent",
    "name": "Test Parent",
}

COACH_USER = {
    "id": "coach-user-id-001",
    "email": "coach@example.com",
    "role": "coach",
    "name": "Test Coach",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mongo():
    """Fresh in-memory Mongo for each test."""
    client = AsyncMongoMockClient()
    fake_db = client["academy_test"]
    db_module._client = client
    db_module._db = fake_db
    yield fake_db
    db_module._client = None
    db_module._db = None


@pytest.fixture(autouse=True)
def force_local_auth():
    """Ensure JWT (local) auth is used for this test module, regardless of test ordering."""
    import os
    prev = os.environ.get("FIREBASE_AUTH_ENABLED")
    os.environ["FIREBASE_AUTH_ENABLED"] = "false"
    yield
    if prev is None:
        os.environ.pop("FIREBASE_AUTH_ENABLED", None)
    else:
        os.environ["FIREBASE_AUTH_ENABLED"] = prev


@pytest.fixture
def app(mongo):
    from routers.finance_routes import router as finance_router
    application = FastAPI()
    application.include_router(finance_router, prefix="/api")
    return application


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_client(app, mongo):
    """TestClient with admin credentials seeded in DB and JWT auth."""
    oid = ObjectId()
    asyncio.run(mongo.users.insert_one({
        "_id": oid,
        "email": ADMIN_USER["email"],
        "name": ADMIN_USER["name"],
        "role": "admin",
        "status": "active",
        "password_hash": "$2b$12$dummy",
    }))
    from auth import create_access_token
    token = create_access_token(str(oid), ADMIN_USER["email"], "admin")
    tc = TestClient(app, raise_server_exceptions=False)
    tc.headers = {"Authorization": f"Bearer {token}"}
    return tc


@pytest.fixture
def coach_client(app, mongo):
    """TestClient with coach credentials."""
    oid = ObjectId()
    asyncio.run(mongo.users.insert_one({
        "_id": oid,
        "email": COACH_USER["email"],
        "name": COACH_USER["name"],
        "role": "coach",
        "status": "active",
        "password_hash": "$2b$12$dummy",
    }))
    from auth import create_access_token
    token = create_access_token(str(oid), COACH_USER["email"], "coach")
    tc = TestClient(app, raise_server_exceptions=False)
    tc.headers = {"Authorization": f"Bearer {token}"}
    return tc


@pytest.fixture
def parent_client(app, mongo):
    """TestClient with parent credentials."""
    oid = ObjectId()
    asyncio.run(mongo.users.insert_one({
        "_id": oid,
        "email": PARENT_USER["email"],
        "name": PARENT_USER["name"],
        "role": "parent",
        "status": "active",
        "password_hash": "$2b$12$dummy",
    }))
    from auth import create_access_token
    token = create_access_token(str(oid), PARENT_USER["email"], "parent")
    tc = TestClient(app, raise_server_exceptions=False)
    tc.headers = {"Authorization": f"Bearer {token}"}
    return tc


# ---------------------------------------------------------------------------
# Payment seeding helpers
# ---------------------------------------------------------------------------

def _make_payment(
    mongo,
    *,
    status: str = "paid",
    payment_method: str | None = "cash",
    stripe_payment_intent: str | None = None,
    stripe_invoice_id: str | None = None,
    final_amount: float = 100.0,
) -> str:
    """Seed a payment document and return its string id."""
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "status": status,
        "payment_method": payment_method,
        "final_amount": final_amount,
        "amount": final_amount,
        "discount": 0,
        "period": "2026-05",
        "parent_user_id": "parent-001",
        "student_id": "student-001",
        "enrollment_id": "enrollment-001",
        "session_id": "session-001",
        "notes": "",
        "refunded_amount": 0,
        "refund_status": "none",
        "refunds": [],
        "is_deleted": False,
        "created_at": now,
    }
    if stripe_payment_intent is not None:
        doc["stripe_payment_intent"] = stripe_payment_intent
    if stripe_invoice_id is not None:
        doc["stripe_invoice_id"] = stripe_invoice_id
    result = asyncio.run(mongo.payments.insert_one(doc))
    return str(result.inserted_id)


def _make_stripe_payment(
    mongo,
    *,
    final_amount: float = 100.0,
    payment_method: str = "stripe",
    stripe_payment_intent: str = "pi_test_123",
) -> str:
    """Seed a paid Stripe payment and return its string id."""
    return _make_payment(
        mongo,
        status="paid",
        payment_method=payment_method,
        stripe_payment_intent=stripe_payment_intent,
        final_amount=final_amount,
    )


def _mock_stripe_refund(refund_id: str = "re_test_abc", amount: int = 10000) -> MagicMock:
    """Build a fake stripe.Refund object."""
    refund = MagicMock()
    refund.id = refund_id
    refund.status = "succeeded"
    refund.amount = amount
    refund.to_dict_recursive.return_value = {
        "id": refund_id,
        "status": "succeeded",
        "amount": amount,
    }
    return refund


# ===========================================================================
# Undo-paid gating tests (1-8)
# ===========================================================================

class TestUndoPaidGating:
    """Undo-paid endpoint must block Stripe-linked payments."""

    def test_undo_paid_blocked_for_stripe_payment_method(self, admin_client, mongo):
        """payment_method='stripe' -> 409 with stripe_paid_use_refund error."""
        pid = _make_payment(mongo, payment_method="stripe")
        r = admin_client.post(f"/api/payments/{pid}/undo-paid")
        assert r.status_code == 409
        body = r.json()
        assert body["error"] == "stripe_paid_use_refund"
        assert "refund" in body["detail"].lower()

    def test_undo_paid_blocked_for_stripe_subscription(self, admin_client, mongo):
        """payment_method='stripe_subscription' -> 409."""
        pid = _make_payment(mongo, payment_method="stripe_subscription")
        r = admin_client.post(f"/api/payments/{pid}/undo-paid")
        assert r.status_code == 409
        assert r.json()["error"] == "stripe_paid_use_refund"

    def test_undo_paid_blocked_for_stripe_onboarding(self, admin_client, mongo):
        """payment_method='stripe_onboarding' -> 409."""
        pid = _make_payment(mongo, payment_method="stripe_onboarding")
        r = admin_client.post(f"/api/payments/{pid}/undo-paid")
        assert r.status_code == 409
        assert r.json()["error"] == "stripe_paid_use_refund"

    def test_undo_paid_blocked_when_stripe_payment_intent_set(self, admin_client, mongo):
        """payment_method='manual' but stripe_payment_intent set -> 409."""
        pid = _make_payment(
            mongo,
            payment_method="manual",
            stripe_payment_intent="pi_xxx_defensive",
        )
        r = admin_client.post(f"/api/payments/{pid}/undo-paid")
        assert r.status_code == 409
        assert r.json()["error"] == "stripe_paid_use_refund"

    def test_undo_paid_blocked_when_stripe_invoice_id_set(self, admin_client, mongo):
        """payment_method='manual' but stripe_invoice_id set -> 409."""
        pid = _make_payment(
            mongo,
            payment_method="manual",
            stripe_invoice_id="in_test_invoice",
        )
        r = admin_client.post(f"/api/payments/{pid}/undo-paid")
        assert r.status_code == 409
        assert r.json()["error"] == "stripe_paid_use_refund"

    def test_undo_paid_allowed_for_cash_payment(self, admin_client, mongo):
        """payment_method='cash' with no Stripe fields -> 200, status flips."""
        pid = _make_payment(mongo, payment_method="cash")
        r = admin_client.post(f"/api/payments/{pid}/undo-paid")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        updated = asyncio.run(mongo.payments.find_one({"_id": ObjectId(pid)}))
        assert updated["status"] == "pending"

    def test_undo_paid_allowed_for_check_payment(self, admin_client, mongo):
        """payment_method='check' with no Stripe fields -> 200, status flips."""
        pid = _make_payment(mongo, payment_method="check")
        r = admin_client.post(f"/api/payments/{pid}/undo-paid")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        updated = asyncio.run(mongo.payments.find_one({"_id": ObjectId(pid)}))
        assert updated["status"] == "pending"

    def test_undo_paid_blocked_writes_audit_log(self, admin_client, mongo):
        """Blocked undo-paid must write exactly one audit_logs row with correct action."""
        pid = _make_payment(mongo, payment_method="stripe")
        r = admin_client.post(f"/api/payments/{pid}/undo-paid")
        assert r.status_code == 409

        logs = asyncio.run(mongo.audit_logs.find({}).to_list(100))
        blocked_logs = [lg for lg in logs if lg["action"] == "payment.undo_paid_blocked"]
        assert len(blocked_logs) == 1
        log_entry = blocked_logs[0]
        assert log_entry["entity_type"] == "payment"
        assert log_entry["entity_id"] == pid
        assert log_entry["user_email"] == ADMIN_USER["email"]


# ===========================================================================
# Admin refund endpoint tests (9-15)
# ===========================================================================

class TestAdminRefundEndpoint:
    """Admin refund endpoint POST /api/admin/payments/{id}/refund."""

    def test_admin_refund_full_amount_creates_record(self, admin_client, mongo):
        """Full refund: Stripe called with full cents, payment_refunds row inserted,
        parent payment updated, audit log written."""
        pid = _make_stripe_payment(mongo, final_amount=50.0, stripe_payment_intent="pi_full")

        mock_stripe = MagicMock()
        mock_stripe.Refund.create.return_value = _mock_stripe_refund("re_full_001", 5000)

        with patch("routers.finance_routes.stripe", mock_stripe, create=True):
            r = admin_client.post(
                f"/api/admin/payments/{pid}/refund",
                json={"reason": "Customer dissatisfaction"},
            )

        assert r.status_code == 200
        body = r.json()
        assert body["stripe_refund_id"] == "re_full_001"
        assert body["amount"] == 50.0

        # stripe.Refund.create called with correct cents
        mock_stripe.Refund.create.assert_called_once_with(
            payment_intent="pi_full",
            amount=5000,
            reason="Customer dissatisfaction",
        )

        # payment_refunds row created
        refund_row = asyncio.run(
            mongo.payment_refunds.find_one({"stripe_refund_id": "re_full_001"})
        )
        assert refund_row is not None
        assert refund_row["payment_id"] == pid
        assert refund_row["amount"] == 50.0

        # parent payment updated
        payment = asyncio.run(mongo.payments.find_one({"_id": ObjectId(pid)}))
        assert payment["refunded_amount"] == 50.0
        assert payment["refund_status"] == "refunded"

        # audit log written
        logs = asyncio.run(mongo.audit_logs.find({}).to_list(100))
        assert any(
            lg["action"] == "payment.refunded" and lg["entity_id"] == pid
            for lg in logs
        )

    def test_admin_refund_partial_amount(self, admin_client, mongo):
        """Partial refund of $10.50 -> 1050 cents; refund_status='partially_refunded'."""
        pid = _make_stripe_payment(mongo, final_amount=100.0, stripe_payment_intent="pi_partial")

        mock_stripe = MagicMock()
        mock_stripe.Refund.create.return_value = _mock_stripe_refund("re_partial_001", 1050)

        with patch("routers.finance_routes.stripe", mock_stripe, create=True):
            r = admin_client.post(
                f"/api/admin/payments/{pid}/refund",
                json={"amount": 10.50, "reason": "Partial service failure"},
            )

        assert r.status_code == 200
        body = r.json()
        assert body["amount"] == pytest.approx(10.50)

        mock_stripe.Refund.create.assert_called_once_with(
            payment_intent="pi_partial",
            amount=1050,
            reason="Partial service failure",
        )

        payment = asyncio.run(mongo.payments.find_one({"_id": ObjectId(pid)}))
        assert payment["refunded_amount"] == pytest.approx(10.50)
        assert payment["refund_status"] == "partially_refunded"

    def test_admin_refund_requires_reason(self, admin_client, mongo):
        """Missing or empty reason -> 400."""
        pid = _make_stripe_payment(mongo, stripe_payment_intent="pi_noreason")

        # No reason at all
        r1 = admin_client.post(f"/api/admin/payments/{pid}/refund", json={})
        assert r1.status_code == 400

        # Empty string reason
        r2 = admin_client.post(f"/api/admin/payments/{pid}/refund", json={"reason": ""})
        assert r2.status_code == 400

    def test_admin_refund_requires_admin_role(self, coach_client, parent_client, mongo):
        """Non-admin roles (coach, parent) -> 403."""
        pid = _make_stripe_payment(mongo, stripe_payment_intent="pi_authn")

        for non_admin in (coach_client, parent_client):
            r = non_admin.post(
                f"/api/admin/payments/{pid}/refund",
                json={"reason": "Test"},
            )
            assert r.status_code == 403

    def test_admin_refund_400_for_non_stripe_payment(self, admin_client, mongo):
        """Cash payment -> 400 with not_stripe_paid error."""
        pid = _make_payment(mongo, payment_method="cash")

        r = admin_client.post(
            f"/api/admin/payments/{pid}/refund",
            json={"reason": "Wrong workflow"},
        )

        assert r.status_code == 400
        body = r.json()
        assert body.get("error") == "not_stripe_paid"

    def test_admin_refund_502_on_stripe_error(self, admin_client, mongo):
        """Stripe API error -> 502; no payment_refunds row inserted."""
        pid = _make_stripe_payment(mongo, stripe_payment_intent="pi_stripe_error")

        mock_stripe = MagicMock()
        mock_stripe.Refund.create.side_effect = Exception("card_error: Your card was declined")

        with patch("routers.finance_routes.stripe", mock_stripe, create=True):
            r = admin_client.post(
                f"/api/admin/payments/{pid}/refund",
                json={"reason": "Customer request"},
            )

        assert r.status_code == 502
        count = asyncio.run(mongo.payment_refunds.count_documents({}))
        assert count == 0

    def test_admin_refund_audit_log(self, admin_client, mongo):
        """Successful refund writes audit log with action='payment.refunded' and reason."""
        pid = _make_stripe_payment(mongo, final_amount=75.0, stripe_payment_intent="pi_auditlog")

        mock_stripe = MagicMock()
        mock_stripe.Refund.create.return_value = _mock_stripe_refund("re_audit_001", 7500)

        with patch("routers.finance_routes.stripe", mock_stripe, create=True):
            r = admin_client.post(
                f"/api/admin/payments/{pid}/refund",
                json={"reason": "Quality issue"},
            )

        assert r.status_code == 200

        logs = asyncio.run(mongo.audit_logs.find({}).to_list(100))
        refund_logs = [lg for lg in logs if lg["action"] == "payment.refunded"]
        assert len(refund_logs) == 1
        log_entry = refund_logs[0]
        assert log_entry["entity_type"] == "payment"
        assert log_entry["entity_id"] == pid
        assert log_entry["user_email"] == ADMIN_USER["email"]
        # Summary must contain either the reason or the amount
        assert "Quality issue" in log_entry["summary"] or "75" in log_entry["summary"]
