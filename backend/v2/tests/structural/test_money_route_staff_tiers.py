"""Staff money tiers on the admin surface.

Staff tiers are owner, billing and front desk. The owner decision of
2026-09-22 (docs/roadmap/2026-09-22-product-roadmap.md section 6, item 2) is
authoritative and newer than People CRM engineering spec section 4:

* owner-only: money-moving actions, i.e. refund, void, card charges,
  discounts, undo-paid, adjustments and fees (plus payroll approval, role
  management and Stripe disconnect);
* billing: sees amounts and RECORDS payments the family already made
  (record payment, mark paid);
* front desk: an "owes money" flag only.

Known gap, pinned as strict xfails so it flips to a failure the moment it is
closed: the two card-charge routes and the ``charge_card`` Billing-tab action
are reachable by non-owner admins (production fix deferred to its own PR,
since it removes a live capability and needs a frontend change).

Only the owner tier exists in code today; billing and front desk are #553. So
billing-tier routes are gated by the admin persona and must NOT be owner-gated
(that would take a decided capability away from billing staff). When #553
lands, these routes move from "admin persona" to "billing tier or owner".
This walks the real admin router (the ``test_owner_gate_policy`` walker) so a
money route that drifts onto the wrong tier fails here.
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

#: Billing-tier routes: billing staff record payments the family already
#: made (owner decision 2026-09-22). Admin-persona gated today, never owner-only.
BILLING_TIER_ROUTES: tuple[tuple[str, str], ...] = (
    ("POST", f"{_ADMIN}/billing/invoices/{{invoice_id}}/record-payment"),
    ("POST", f"{_ADMIN}/payments/{{payment_id}}/mark-paid"),
)

_CHARGE_GAP = (
    "Card charges move money and are owner-only per the 2026-09-22 staff-tier "
    "decision, but this route is require_persona('admin') and not in "
    "OWNER_ONLY_ROUTE_PATHS (A5 finding; production fix deferred)."
)

#: Admin-reachable card charges: the known gap.
CARD_CHARGE_ROUTES: tuple[tuple[str, str], ...] = (
    ("POST", f"{_ADMIN}/billing/invoices/{{invoice_id}}/charge-autopay"),
    ("POST", f"{_ADMIN}/billing/setup/{{parent_id}}/charge"),
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


@pytest.mark.parametrize("key", BILLING_TIER_ROUTES, ids=lambda k: f"{k[0]} {k[1]}")
def test_billing_tier_route_is_admin_gated_not_owner_only(key: tuple[str, str]) -> None:
    routes = _admin_routes()
    assert key in routes, f"billing route not registered: {key}"
    assert "admin" in _personas(routes[key])
    assert key not in OWNER_ONLY_ROUTE_PATHS
    assert not _is_owner_guarded(routes[key])


def test_billing_tab_hides_money_moving_actions_from_non_owners() -> None:
    assert {"refund", "void", "discount_once", "recurring_discount"} <= OWNER_ONLY_ACTIONS


def test_billing_tab_offers_record_payment_to_billing_staff() -> None:
    assert "record_payment" not in OWNER_ONLY_ACTIONS


@pytest.mark.xfail(strict=True, reason=_CHARGE_GAP)
def test_billing_tab_hides_the_card_charge_from_non_owners() -> None:
    assert "charge_card" in OWNER_ONLY_ACTIONS
