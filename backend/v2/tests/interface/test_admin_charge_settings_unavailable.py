"""Admin card charges answer 503, not 500, when billing settings can't be read.

The charge reads the billing settings to decide the ACH discount before it asks
Stripe. Since #1220 a failed read propagates (so the dunning worker parks the
rung) and the admin routes turned it into an unhandled 500. It is now
``BillingSettingsUnavailable``, which the shared handler maps to a 503 with a
message an admin can act on.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.v2.contexts.billing.domain.errors import BillingSettingsUnavailable

_DOWN = BillingSettingsUnavailable(
    "Couldn't read the billing settings, so the card was not charged. Try again."
)


@pytest.mark.parametrize(
    ("use_case", "path", "body"),
    [
        (
            "charge_invoice_as_admin_action",
            "/api/v2/admin/billing/invoices/inv-1/charge-autopay",
            {"reason": "family asked"},
        ),
        (
            "charge_billing_setup_balance",
            "/api/v2/admin/billing/setup/parent-1/charge",
            {
                "invoice_id": "inv-1",
                "expected_amount_cents": 5000,
                "request_id": "settings-unavailable-0001",
            },
        ),
    ],
    ids=["invoice", "billing-setup"],
)
def test_settings_read_failure_is_a_clean_503(admin_client, use_case, path, body) -> None:
    setattr(admin_client.use_cases, use_case, AsyncMock(side_effect=_DOWN))

    r = admin_client.post(path, json=body)

    assert r.status_code == 503, r.text
    error = r.json()["error"]
    assert error["code"] == "Billing.SettingsUnavailable"
    assert "not charged" in error["message"]
