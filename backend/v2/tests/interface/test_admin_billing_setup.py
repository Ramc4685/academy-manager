"""Admin Billing Setup routes — registration status list + invite/charge/autopay actions."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from backend.v2.contexts.billing.application.ports import (
    BillingSetupStudent,
)
from backend.v2.contexts.billing.application.use_cases.billing_setup_registration import (
    BillingSetupPage,
    BillingSetupRow,
    BillingSetupSummary,
)
from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    LoginInviteResult,
)

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
REQUEST_ID = "billing-setup-request-0001"
CHARGE_BODY = {
    "invoice_id": "inv-1",
    "expected_amount_cents": 5000,
    "request_id": REQUEST_ID,
}


class _FakeInviteOutcome:
    def __init__(self, *, ok: bool, failed_reason: str | None = None) -> None:
        self.ok = ok
        self.failed_reason = failed_reason


class FakeListBillingSetup:
    def __init__(self, page: BillingSetupPage) -> None:
        self._page = page
        self.calls: list[dict[str, object]] = []

    async def execute(self, **kwargs: object) -> BillingSetupPage:
        self.calls.append(kwargs)
        return self._page


def _row(
    parent_id: str = "parent-1",
    *,
    state: str = "no_account",
    outstanding: int = 0,
) -> BillingSetupRow:
    return BillingSetupRow(
        parent_id=parent_id,
        parent_name="Pat Lee",
        parent_email="pat@example.com",
        students=(BillingSetupStudent(student_id="student-1", full_name="Sam Lee"),),
        registration_state=state,  # type: ignore[arg-type]
        card_label="Visa" if state == "card_on_file" else None,
        card_last4="4242" if state == "card_on_file" else None,
        autopay_active_count=0,
        autopay_eligible_count=0,
        outstanding_balance_cents=outstanding,
        charge_invoice_id="inv-1" if outstanding else None,
        charge_amount_cents=outstanding,
        last_invited_at=None,
    )


def _page(rows: tuple[BillingSetupRow, ...]) -> BillingSetupPage:
    return BillingSetupPage(
        rows=rows,
        summary=BillingSetupSummary(
            families_total=len(rows),
            families_registered=sum(1 for r in rows if r.registration_state == "card_on_file"),
            families_no_card=sum(1 for r in rows if r.registration_state != "card_on_file"),
            outstanding_total_cents=sum(r.outstanding_balance_cents for r in rows),
        ),
        next_cursor=None,
    )


def test_list_billing_setup_returns_rows_and_summary(admin_client):
    page = _page((_row(state="card_on_file", outstanding=5000),))
    admin_client.use_cases.list_billing_setup = FakeListBillingSetup(page)

    r = admin_client.get("/api/v2/admin/billing/setup")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["families_total"] == 1
    assert body["summary"]["families_registered"] == 1
    assert body["summary"]["outstanding_total_cents"] == 5000
    assert body["rows"][0]["parent_id"] == "parent-1"
    assert body["rows"][0]["registration_state"] == "card_on_file"
    assert body["rows"][0]["students"][0]["full_name"] == "Sam Lee"


def test_charge_with_no_saved_card_returns_400(admin_client):
    admin_client.use_cases.charge_billing_setup_balance = AsyncMock(
        side_effect=ValueError("no_saved_payment_method: parent has no saved card")
    )

    r = admin_client.post("/api/v2/admin/billing/setup/parent-1/charge", json=CHARGE_BODY)

    assert r.status_code == 400, r.text
    assert "no_saved_payment_method" in r.json()["detail"]


def test_charge_with_zero_balance_returns_400(admin_client):
    admin_client.use_cases.charge_billing_setup_balance = AsyncMock(
        side_effect=ValueError(
            "no_outstanding_balance: parent has no open invoices with a balance due"
        )
    )

    r = admin_client.post("/api/v2/admin/billing/setup/parent-1/charge", json=CHARGE_BODY)

    assert r.status_code == 400, r.text
    assert "no_outstanding_balance" in r.json()["detail"]


def test_charge_success_returns_result(admin_client):
    admin_client.use_cases.charge_billing_setup_balance = AsyncMock(
        return_value={
            "invoice_id": "inv-1",
            "success": True,
            "status": "paid",
            "balance_due_cents": 0,
            "charged_amount_cents": 5000,
        }
    )

    r = admin_client.post("/api/v2/admin/billing/setup/parent-1/charge", json=CHARGE_BODY)

    assert r.status_code == 200, r.text
    assert r.json()["success"] is True
    assert r.json()["invoice_id"] == "inv-1"
    assert r.json()["charged_amount_cents"] == 5000
    admin_client.use_cases.charge_billing_setup_balance.assert_awaited_once_with(
        parent_id="parent-1",
        invoice_id="inv-1",
        expected_amount_cents=5000,
        request_id=REQUEST_ID,
        actor_id="u-admin",
    )


def test_charge_processing_returns_submitted_state_and_actual_amount(admin_client):
    admin_client.use_cases.charge_billing_setup_balance = AsyncMock(
        return_value={
            "invoice_id": "inv-1",
            "success": False,
            "status": "open",
            "balance_due_cents": 4750,
            "charged_amount_cents": 0,
            "attempted_amount_cents": 4750,
            "processing": True,
        }
    )

    r = admin_client.post("/api/v2/admin/billing/setup/parent-1/charge", json=CHARGE_BODY)

    assert r.status_code == 200, r.text
    assert r.json()["processing"] is True
    assert r.json()["charged_amount_cents"] == 0
    assert r.json()["attempted_amount_cents"] == 4750


def test_charge_unavailable_returns_503_without_provider_detail(admin_client):
    admin_client.use_cases.charge_billing_setup_balance = AsyncMock(
        side_effect=RuntimeError("secret Stripe provider detail")
    )

    r = admin_client.post("/api/v2/admin/billing/setup/parent-1/charge", json=CHARGE_BODY)

    assert r.status_code == 503, r.text
    assert r.json()["detail"] == "payment_service_unavailable"
    assert "secret" not in r.text


def test_invite_dispatches_login_invite_when_no_account(admin_client):
    admin_client.use_cases.list_billing_setup = FakeListBillingSetup(
        _page((_row(state="no_account"),))
    )
    admin_client.use_cases.send_login_invite.execute = AsyncMock(
        return_value=LoginInviteResult(sent_at=NOW)
    )
    admin_client.use_cases.provision_parent_login = AsyncMock()
    admin_client.use_cases.provision_parent_login.execute = AsyncMock(return_value="parent-1")
    admin_client.use_cases.send_add_card_reminder.execute = AsyncMock()
    admin_client.use_cases.record_billing_setup_invite = AsyncMock(return_value=NOW)

    r = admin_client.post("/api/v2/admin/billing/setup/parent-1/invite")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "login_invite"
    assert body["ok"] is True
    admin_client.use_cases.send_login_invite.execute.assert_awaited_once()
    admin_client.use_cases.provision_parent_login.execute.assert_awaited_once()
    admin_client.use_cases.send_add_card_reminder.execute.assert_not_awaited()
    assert admin_client.use_cases.list_billing_setup.calls == [
        {"academy_id": "acad", "parent_id": "parent-1", "limit": 1}
    ]


def test_invite_dispatches_add_card_reminder_when_account_no_card(admin_client):
    admin_client.use_cases.list_billing_setup = FakeListBillingSetup(
        _page((_row(state="account_no_card"),))
    )
    admin_client.use_cases.send_add_card_reminder.execute = AsyncMock(
        return_value=_FakeInviteOutcome(ok=True)
    )
    admin_client.use_cases.send_login_invite.execute = AsyncMock()
    admin_client.use_cases.record_billing_setup_invite = AsyncMock(return_value=NOW)

    r = admin_client.post("/api/v2/admin/billing/setup/parent-1/invite")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "add_card_reminder"
    assert body["ok"] is True
    admin_client.use_cases.send_add_card_reminder.execute.assert_awaited_once()
    admin_client.use_cases.send_login_invite.execute.assert_not_awaited()


def test_invite_add_card_exception_returns_normalized_failure(admin_client):
    admin_client.use_cases.list_billing_setup = FakeListBillingSetup(
        _page((_row(state="account_no_card"),))
    )
    admin_client.use_cases.send_add_card_reminder.execute = AsyncMock(
        side_effect=RuntimeError("provider secret detail")
    )

    r = admin_client.post("/api/v2/admin/billing/setup/parent-1/invite")

    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False
    assert r.json()["failed_reason"] == "add_card_reminder_failed"


def test_invite_not_applicable_when_already_card_on_file(admin_client):
    admin_client.use_cases.list_billing_setup = FakeListBillingSetup(
        _page((_row(state="card_on_file"),))
    )
    admin_client.use_cases.send_login_invite.execute = AsyncMock()
    admin_client.use_cases.send_add_card_reminder.execute = AsyncMock()

    r = admin_client.post("/api/v2/admin/billing/setup/parent-1/invite")

    assert r.status_code == 200, r.text
    assert r.json()["action"] == "not_applicable"
    admin_client.use_cases.send_login_invite.execute.assert_not_awaited()
    admin_client.use_cases.send_add_card_reminder.execute.assert_not_awaited()


def test_autopay_enable_with_no_saved_card_returns_400(admin_client):
    admin_client.use_cases.enable_billing_setup_autopay = AsyncMock(
        side_effect=ValueError("no_saved_payment_method: parent has no saved card")
    )

    r = admin_client.post(
        "/api/v2/admin/billing/setup/parent-1/autopay/enable",
        json={"request_id": REQUEST_ID},
    )

    assert r.status_code == 400, r.text
    assert "no_saved_payment_method" in r.json()["detail"]


def test_autopay_enable_success_returns_counts(admin_client):
    admin_client.use_cases.enable_billing_setup_autopay = AsyncMock(
        return_value={"eligible_count": 2, "enabled_count": 2}
    )

    r = admin_client.post(
        "/api/v2/admin/billing/setup/parent-1/autopay/enable",
        json={"request_id": REQUEST_ID},
    )

    assert r.status_code == 200, r.text
    assert r.json() == {"eligible_count": 2, "enabled_count": 2}


def test_billing_setup_routes_wrong_persona_are_hidden(coach_on_admin_client):
    assert coach_on_admin_client.get("/api/v2/admin/billing/setup").status_code == 404
    assert (
        coach_on_admin_client.post("/api/v2/admin/billing/setup/parent-1/invite").status_code == 404
    )
    assert (
        coach_on_admin_client.post(
            "/api/v2/admin/billing/setup/parent-1/charge", json=CHARGE_BODY
        ).status_code
        == 404
    )
    assert (
        coach_on_admin_client.post(
            "/api/v2/admin/billing/setup/parent-1/autopay/enable",
            json={"request_id": REQUEST_ID},
        ).status_code
        == 404
    )
