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

Card charges (the two charge routes and the ``charge_card`` Billing-tab
action) were reachable by non-owner admins until #928 put them behind
``require_owner``; they are pinned here with the other money-moving routes.

#553 built the billing and front-desk tiers (``shared/auth/staff_tiers.py``).
Billing-tier routes are guarded by ``require_staff_tier("billing")`` (owner,
admin or billing; ``interfaces/admin/staff_tier.py``), never by the admin
persona alone (that would 404 billing staff) and never by ``require_owner``
(that would take a decided capability away from billing staff and admins).
Front desk opens no money route: its only routes are the three People CRM
family index reads (L2b), where money is redacted to an "owes money" flag
by the server. This walks the real admin router (the
``test_owner_gate_policy`` walker) so a money route that drifts onto the
wrong tier fails here, in both directions.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from backend.v2.contexts.billing.application.family_billing import OWNER_ONLY_ACTIONS
from backend.v2.interfaces.admin.owner_gate import OWNER_ONLY_ROUTE_PATHS
from backend.v2.interfaces.admin.staff_tier import STAFF_TIER_ROUTE_PATHS
from backend.v2.shared.auth.staff_tiers import PAYMENT_RECORDER_ROLES
from backend.v2.tests.structural.test_crm_admin_persona_gate import _personas
from backend.v2.tests.structural.test_owner_gate_policy import (
    _admin_routes,
    _dependant_calls,
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
    # Card charges (#928).
    ("POST", f"{_ADMIN}/billing/invoices/{{invoice_id}}/charge-autopay"),
    ("POST", f"{_ADMIN}/billing/setup/{{parent_id}}/charge"),
)

#: Billing-tier routes: billing staff record payments the family already
#: made (owner decision 2026-09-22). Owner, admin or billing; never owner-only.
BILLING_TIER_ROUTES: tuple[tuple[str, str], ...] = (
    ("POST", f"{_ADMIN}/billing/invoices/{{invoice_id}}/record-payment"),
    ("POST", f"{_ADMIN}/payments/{{payment_id}}/mark-paid"),
)


@pytest.mark.parametrize("key", MONEY_MOVING_ROUTES, ids=lambda k: f"{k[0]} {k[1]}")
def test_money_moving_route_is_owner_only(key: tuple[str, str]) -> None:
    routes = _admin_routes()
    assert key in routes, f"money route not registered: {key}"
    assert key in OWNER_ONLY_ROUTE_PATHS
    assert _is_owner_guarded(routes[key])


def _staff_tiers(route: Any) -> set[str]:
    """The tiers named by every ``require_staff_tier`` in a route's chain."""
    found: set[str] = set()
    for call in _dependant_calls(route.dependant):
        if "require_staff_tier" not in getattr(call, "__qualname__", ""):
            continue
        tier = inspect.getclosurevars(call).nonlocals.get("tier")
        if isinstance(tier, str):
            found.add(tier)
    return found


@pytest.mark.parametrize("key", BILLING_TIER_ROUTES, ids=lambda k: f"{k[0]} {k[1]}")
def test_billing_tier_route_admits_the_billing_tier_not_owner_only(
    key: tuple[str, str],
) -> None:
    routes = _admin_routes()
    assert key in routes, f"billing route not registered: {key}"
    assert _staff_tiers(routes[key]) == {"billing"}
    # The admin persona gate would 404 a billing-only member before the tier ran.
    assert "admin" not in _personas(routes[key])
    assert key in STAFF_TIER_ROUTE_PATHS["billing"]
    assert key not in OWNER_ONLY_ROUTE_PATHS
    assert not _is_owner_guarded(routes[key])


def test_staff_tier_route_set_matches_the_router_in_both_directions() -> None:
    routes = _admin_routes()
    guarded = {(tier, key) for key, route in routes.items() for tier in _staff_tiers(route)}
    declared = {(tier, key) for tier, keys in STAFF_TIER_ROUTE_PATHS.items() for key in keys}
    assert guarded == declared


def test_billing_tier_routes_are_exactly_the_payment_recording_routes() -> None:
    assert STAFF_TIER_ROUTE_PATHS["billing"] == frozenset(BILLING_TIER_ROUTES)


@pytest.mark.parametrize("key", MONEY_MOVING_ROUTES, ids=lambda k: f"{k[0]} {k[1]}")
def test_no_staff_tier_reaches_a_money_moving_route(key: tuple[str, str]) -> None:
    routes = _admin_routes()
    assert not _staff_tiers(routes[key])
    assert all(key not in keys for keys in STAFF_TIER_ROUTE_PATHS.values())


def test_front_desk_records_no_payment_and_opens_only_family_index_reads() -> None:
    assert "front_desk" not in PAYMENT_RECORDER_ROLES
    front_desk = STAFF_TIER_ROUTE_PATHS["front_desk"]
    assert front_desk
    assert all(method == "GET" for method, _ in front_desk)
    assert all(path.startswith(f"{_ADMIN}/families") for _, path in front_desk)
    assert not front_desk & set(MONEY_VIEWER_ONLY_READS)


#: Reads that carry amounts and stay closed to front desk.
MONEY_VIEWER_ONLY_READS: tuple[tuple[str, str], ...] = (
    ("GET", f"{_ADMIN}/families/{{parent_id}}/billing"),
    ("GET", f"{_ADMIN}/reports/people/money-owed-by-age"),
)


@pytest.mark.parametrize("key", MONEY_VIEWER_ONLY_READS, ids=lambda k: f"{k[0]} {k[1]}")
def test_amount_reads_admit_no_staff_tier(key: tuple[str, str]) -> None:
    routes = _admin_routes()
    assert key in routes, f"money read not registered: {key}"
    assert not _staff_tiers(routes[key])


def test_billing_tab_hides_money_moving_actions_from_non_owners() -> None:
    assert {"refund", "void", "discount_once", "recurring_discount"} <= OWNER_ONLY_ACTIONS


def test_billing_tab_offers_record_payment_to_billing_staff() -> None:
    assert "record_payment" not in OWNER_ONLY_ACTIONS


def test_billing_tab_hides_the_card_charge_from_non_owners() -> None:
    assert "charge_card" in OWNER_ONLY_ACTIONS
