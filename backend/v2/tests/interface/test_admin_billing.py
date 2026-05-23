"""Admin billing + finance BFF — happy + wrong-persona 404."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.billing.application.use_cases.finance import Payout
from backend.v2.contexts.billing.domain.models import Payment


def _seed_payment(
    seed,
    payment_id: str,
    amount_cents: int = 15000,
    status: str = "succeeded",
    stripe: bool = True,
):
    now = datetime.now(UTC)
    seed["payments"].rows[payment_id] = Payment(
        payment_id=payment_id,
        academy_id="acad",
        parent_id=f"parent-{payment_id}",
        session_id="sess-1",
        stripe_payment_intent_id=f"pi_{payment_id}" if stripe else None,
        amount_cents=amount_cents,
        currency="usd",
        status=status,  # type: ignore[arg-type]
        refunded_cents=0,
        created_at=now,
        updated_at=now,
    )


def test_list_payments_returns_recent(admin_client):
    _seed_payment(admin_client.seed, "pay-1", 15000)
    _seed_payment(admin_client.seed, "pay-2", 22500)
    r = admin_client.get("/api/v2/admin/payments")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {p["payment_id"] for p in body["payments"]}
    assert ids == {"pay-1", "pay-2"}


def test_list_payments_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.get("/api/v2/admin/payments")
    assert r.status_code == 404


def test_issue_refund_happy_path(admin_client):
    _seed_payment(admin_client.seed, "pay-1", 15000)
    r = admin_client.post(
        "/api/v2/admin/payments/refund",
        json={"payment_id": "pay-1", "amount_cents": 5000, "reason": "admin_initiated"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refunded_cents"] == 5000
    assert body["total_refunded_cents"] == 5000
    # Stripe gateway recorded the refund.
    refunds = admin_client.seed["stripe"].refunds
    assert len(refunds) == 1
    assert refunds[0]["amount_cents"] == 5000


def test_issue_refund_exceeds_amount_returns_400(admin_client):
    _seed_payment(admin_client.seed, "pay-1", 15000)
    r = admin_client.post(
        "/api/v2/admin/payments/refund",
        json={"payment_id": "pay-1", "amount_cents": 99999},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "Billing.RefundExceedsAmount"


def test_issue_refund_wrong_persona_404(parent_on_admin_client):
    r = parent_on_admin_client.post(
        "/api/v2/admin/payments/refund",
        json={"payment_id": "pay-x", "amount_cents": 1},
    )
    assert r.status_code == 404


def test_generate_monthly_payments(admin_client):
    r = admin_client.post(
        "/api/v2/admin/payments/generate-monthly",
        json={"period": "2026-05"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1
    assert admin_client.seed["payments"].generated_periods == ["2026-05"]


def test_mark_payment_paid(admin_client):
    _seed_payment(admin_client.seed, "pay-manual", status="pending", stripe=False)
    r = admin_client.post(
        "/api/v2/admin/payments/pay-manual/mark-paid",
        json={"payment_method": "cash", "notes": "desk"},
    )
    assert r.status_code == 200, r.text
    assert admin_client.seed["payments"].rows["pay-manual"].status == "succeeded"


def test_apply_payment_discount(admin_client):
    _seed_payment(admin_client.seed, "pay-pending", status="pending", stripe=False)
    r = admin_client.post(
        "/api/v2/admin/payments/pay-pending/discount",
        json={"discount_cents": 2500, "reason": "sibling discount"},
    )
    assert r.status_code == 200, r.text
    assert admin_client.seed["payments"].discounts["pay-pending"] == 2500


def test_undo_manual_paid_blocks_stripe_linked(admin_client):
    _seed_payment(admin_client.seed, "pay-stripe", status="succeeded", stripe=True)
    r = admin_client.post("/api/v2/admin/payments/pay-stripe/undo-paid")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "Billing.PaymentOperationNotAllowed"


def test_undo_manual_paid(admin_client):
    _seed_payment(admin_client.seed, "pay-cash", status="succeeded", stripe=False)
    r = admin_client.post("/api/v2/admin/payments/pay-cash/undo-paid")
    assert r.status_code == 200, r.text
    assert admin_client.seed["payments"].rows["pay-cash"].status == "pending"


# --- # FINANCE ---


def test_list_payouts_returns_seeded(admin_client):
    admin_client.seed["payouts"].rows["po-1"] = Payout(
        payout_id="po-1",
        academy_id="acad",
        coach_id="coach-1",
        amount_cents=80000,
        period_start=datetime(2026, 4, 1, tzinfo=UTC),
        period_end=datetime(2026, 4, 30, tzinfo=UTC),
    )
    r = admin_client.get("/api/v2/admin/finance/payouts")
    assert r.status_code == 200
    assert r.json()["payouts"][0]["payout_id"] == "po-1"


def test_list_payouts_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.get("/api/v2/admin/finance/payouts")
    assert r.status_code == 404


def test_record_expense_creates_entry(admin_client):
    r = admin_client.post(
        "/api/v2/admin/finance/expenses",
        json={"category": "rent", "amount_cents": 250000, "note": "May rent"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"] == "rent"
    assert body["amount_cents"] == 250000
    assert body["note"] == "May rent"


def test_record_expense_wrong_persona_404(parent_on_admin_client):
    r = parent_on_admin_client.post(
        "/api/v2/admin/finance/expenses",
        json={"category": "rent", "amount_cents": 1},
    )
    assert r.status_code == 404


def test_revenue_aggregates_by_month(admin_client):
    # Revenue query in AcademyRevenueQuery only runs with a parent_id filter
    # in the Wave 3 stub; admin route passes None which yields {}.
    r = admin_client.get("/api/v2/admin/finance/revenue")
    assert r.status_code == 200
    assert r.json() == {"by_month": {}}


def test_revenue_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.get("/api/v2/admin/finance/revenue")
    assert r.status_code == 404
