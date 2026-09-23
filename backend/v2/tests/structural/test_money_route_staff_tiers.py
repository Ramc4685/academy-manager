"""Staff money tiers on the admin surface (owner decision 2026-09-22).

Staff tiers are owner, billing and front desk. Billing staff may RECORD a
payment (cash, cheque, bank transfer the family already made); every action
that MOVES money (refunds, card charges, credits, discounts, payment voids)
is owner-only, enforced on the backend by ``require_owner`` and listed in
``OWNER_ONLY_ROUTE_PATHS``, and hidden from non-owners on the Billing tab
through ``OWNER_ONLY_ACTIONS``. This walks the real admin router (the
``test_owner_gate_policy`` walker) so a money route that drifts onto the
wrong tier fails here.

Two card-charge routes are admin-reachable today. They are pinned as strict
xfails so the gap is visible in CI and flips to a failure (forcing the
marker off) the moment it is closed.
"""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.family_billing import OWNER_ONLY_ACTIONS
from backend.v2.interfaces.admin.owner_gate import OWNER_ONLY_ROUTE_PATHS
from backend.v2.tests.structural.test_crm_admin_persona_gate import _personas
from backend.v2.tests.structural.test_owner_gate_policy import (
    _admin_routes,
    _is_owner_guarded,
)

_ADMIN = "/api/v2/admin"

#: Routes that move money out of, or onto, a family's account.
MONEY_MOVING_ROUTES: tuple[tuple[str, str], ...] = (
    ("POST", f"{_ADMIN}/payments/refund"),
    ("POST", f"{_ADMIN}/billing/invoices/{{invoice_id}}/refund"),
    ("POST", f"{_ADMIN}/payments/{{payment_id}}/discount"),
    ("POST", f"{_ADMIN}/payments/{{payment_id}}/void"),
    ("POST", f"{_ADMIN}/payments/{{payment_id}}/undo-paid"),
    ("POST", f"{_ADMIN}/billing/invoices/{{invoice_id}}/adjustments"),
    ("PUT", f"{_ADMIN}/enrollments/{{enrollment_id}}/tuition-discount"),
    ("POST", f"{_ADMIN}/enrollments/{{enrollment_id}}/fee"),
)

_CHARGE_GAP = (
    "Card charges are money-moving and owner-only per the 2026-09-22 staff-tier "
    "decision, but this route is require_persona('admin') and not in "
    "OWNER_ONLY_ROUTE_PATHS (A5 finding; see deferred)."
)

#: Admin-reachable card charges: the known gap.
CARD_CHARGE_ROUTES: tuple[tuple[str, str], ...] = (
    ("POST", f"{_ADMIN}/billing/invoices/{{invoice_id}}/charge-autopay"),
    ("POST", f"{_ADMIN}/billing/setup/{{parent_id}}/charge"),
)

#: Recording money the family already paid: billing staff, i.e. the admin persona.
RECORD_PAYMENT_ROUTES: tuple[tuple[str, str], ...] = (
    ("POST", f"{_ADMIN}/billing/invoices/{{invoice_id}}/record-payment"),
    ("POST", f"{_ADMIN}/payments/{{payment_id}}/mark-paid"),
)


@pytest.mark.parametrize("key", MONEY_MOVING_ROUTES, ids=lambda k: f"{k[0]} {k[1]}")
def test_money_moving_route_is_owner_only(key: tuple[str, str]) -> None:
    routes = _admin_routes()
    assert key in routes, f"money route not registered: {key}"
    assert key in OWNER_ONLY_ROUTE_PATHS
    assert _is_owner_guarded(routes[key])


@pytest.mark.parametrize(
    "key",
    [
        pytest.param(k, marks=pytest.mark.xfail(strict=True, reason=_CHARGE_GAP))
        for k in CARD_CHARGE_ROUTES
    ],
    ids=lambda k: f"{k[0]} {k[1]}",
)
def test_card_charge_route_is_owner_only(key: tuple[str, str]) -> None:
    routes = _admin_routes()
    assert key in routes, f"charge route not registered: {key}"
    assert key in OWNER_ONLY_ROUTE_PATHS
    assert _is_owner_guarded(routes[key])


@pytest.mark.parametrize("key", RECORD_PAYMENT_ROUTES, ids=lambda k: f"{k[0]} {k[1]}")
def test_recording_a_payment_is_open_to_billing_staff_and_no_one_else(
    key: tuple[str, str],
) -> None:
    """Admin persona (billing staff) records; not owner-only, and never ungated."""
    routes = _admin_routes()
    assert key in routes, f"record route not registered: {key}"
    assert "admin" in _personas(routes[key])
    assert key not in OWNER_ONLY_ROUTE_PATHS
    assert not _is_owner_guarded(routes[key])


def test_billing_tab_hides_money_moving_actions_from_non_owners() -> None:
    assert {"refund", "void", "discount_once", "recurring_discount"} <= OWNER_ONLY_ACTIONS
    assert "record_payment" not in OWNER_ONLY_ACTIONS


@pytest.mark.xfail(strict=True, reason=_CHARGE_GAP)
def test_billing_tab_hides_the_card_charge_from_non_owners() -> None:
    assert "charge_card" in OWNER_ONLY_ACTIONS
