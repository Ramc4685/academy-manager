"""Card charges are owner-only on the admin surface (#928).

Staff tiers (roadmap 2026-09-22 section 6, decision 2): a card charge moves
money, so only the owner may start one. Both card-charge routes use
``require_owner`` (404 on a miss, like every persona and owner guard, so the
route's existence is not leaked) and hand the caller's roles to the use case,
which refuses a non-owner on its own as well (see
``unit/test_charge_admin_invoice.py`` and
``contract/test_card_charge_owner_gate.py``).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

_SETUP_CHARGE = "/api/v2/admin/billing/setup/parent-1/charge"
_INVOICE_CHARGE = "/api/v2/admin/billing/invoices/inv-1/charge-autopay"
_SETUP_BODY = {
    "invoice_id": "inv-1",
    "expected_amount_cents": 5000,
    "request_id": "card-charge-owner-gate-0001",
}
_CHARGED = {
    "invoice_id": "inv-1",
    "success": True,
    "status": "paid",
    "balance_due_cents": 0,
    "charged_amount_cents": 5000,
    "requires_action": False,
    "decline_code": None,
}


def _arm(client) -> tuple[AsyncMock, AsyncMock]:
    setup = AsyncMock(return_value=dict(_CHARGED))
    invoice = AsyncMock(return_value=dict(_CHARGED))
    client.use_cases.charge_billing_setup_balance = setup
    client.use_cases.charge_invoice_as_admin_action = invoice
    return setup, invoice


def test_owner_can_charge_from_billing_setup(admin_client) -> None:
    setup, _ = _arm(admin_client)

    r = admin_client.post(_SETUP_CHARGE, json=_SETUP_BODY)

    assert r.status_code == 200, r.text
    assert setup.await_args.kwargs["actor_roles"] == ("admin", "owner")


def test_owner_can_charge_an_invoice(admin_client) -> None:
    _, invoice = _arm(admin_client)

    r = admin_client.post(_INVOICE_CHARGE, json={"reason": "family asked"})

    assert r.status_code == 200, r.text
    assert r.json()["success"] is True
    kwargs = invoice.await_args.kwargs
    assert kwargs["actor_roles"] == ("admin", "owner")
    assert kwargs["actor_id"] == "u-admin"


@pytest.mark.parametrize(
    ("path", "body"),
    [(_SETUP_CHARGE, _SETUP_BODY), (_INVOICE_CHARGE, {"reason": "family asked"})],
    ids=["billing-setup", "invoice"],
)
def test_admin_without_owner_cannot_charge_a_card(admin_only_client, path, body) -> None:
    setup, invoice = _arm(admin_only_client)

    r = admin_only_client.post(path, json=body)

    assert r.status_code == 404
    setup.assert_not_awaited()
    invoice.assert_not_awaited()


@pytest.mark.parametrize(
    ("path", "body"),
    [(_SETUP_CHARGE, _SETUP_BODY), (_INVOICE_CHARGE, {"reason": "family asked"})],
    ids=["billing-setup", "invoice"],
)
def test_use_case_owner_refusal_is_a_404_not_a_500(admin_client, path, body) -> None:
    """If the use case refuses (roles changed mid-request), the caller sees a 404."""
    from backend.v2.contexts.billing.application.charge_admin_invoice import (
        ChargeRequiresOwner,
    )

    setup, invoice = _arm(admin_client)
    setup.side_effect = ChargeRequiresOwner()
    invoice.side_effect = ChargeRequiresOwner()

    r = admin_client.post(path, json=body)

    assert r.status_code == 404
