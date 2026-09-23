"""Staff money tiers on the admin surface (People CRM engineering spec §4).

Staff tiers are owner, billing and front desk (owner decision 2026-09-22).
Per docs/design/people-crm/engineering-spec.md §4, every money-moving action
is owner-only: Record payment, charge, refund, void, add charge, one-time
discount, autopay on or off, "enforced on the backend with the existing owner
gate". Owner-only routes are guarded by ``require_owner`` and listed in
``OWNER_ONLY_ROUTE_PATHS``; the Billing tab hides owner-only actions from
non-owners through ``OWNER_ONLY_ACTIONS``. This walks the real admin router
(the ``test_owner_gate_policy`` walker) so a money route that drifts onto the
wrong tier fails here.

Known gaps, pinned as strict xfails so they are visible in CI and flip to a
failure (forcing the marker off) the moment they are closed; the production
fix is out of A5's test-only scope:

* the two card-charge routes are admin-reachable;
* Record payment (``/record-payment`` and ``/payments/{id}/mark-paid``) is
  gated only by ``require_persona("admin")``. No billing-vs-front-desk tier
  exists in code yet (#553), so today ANY admin-persona staff member can
  record a manual payment.
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

_RECORD_PAYMENT_GAP = (
    "Record payment is money-moving and owner-only per People CRM engineering "
    "spec §4, but this route is require_persona('admin') only and not in "
    "OWNER_ONLY_ROUTE_PATHS, so any admin-persona staff can record a manual "
    "payment (A5 finding; production fix deferred)."
)

#: Recording money the family already paid: owner-only per the spec (known gap).
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


@pytest.mark.parametrize(
    "key",
    [
        pytest.param(k, marks=pytest.mark.xfail(strict=True, reason=_RECORD_PAYMENT_GAP))
        for k in RECORD_PAYMENT_ROUTES
    ],
    ids=lambda k: f"{k[0]} {k[1]}",
)
def test_recording_a_payment_is_owner_only(key: tuple[str, str]) -> None:
    routes = _admin_routes()
    assert key in routes, f"record route not registered: {key}"
    assert key in OWNER_ONLY_ROUTE_PATHS
    assert _is_owner_guarded(routes[key])


@pytest.mark.parametrize("key", RECORD_PAYMENT_ROUTES, ids=lambda k: f"{k[0]} {k[1]}")
def test_recording_a_payment_is_never_ungated(key: tuple[str, str]) -> None:
    """Floor that holds today and after the fix: the admin persona gate stays."""
    routes = _admin_routes()
    assert key in routes, f"record route not registered: {key}"
    assert "admin" in _personas(routes[key])


def test_billing_tab_hides_money_moving_actions_from_non_owners() -> None:
    assert {"refund", "void", "discount_once", "recurring_discount"} <= OWNER_ONLY_ACTIONS


@pytest.mark.xfail(strict=True, reason=_RECORD_PAYMENT_GAP)
def test_billing_tab_hides_record_payment_from_non_owners() -> None:
    assert "record_payment" in OWNER_ONLY_ACTIONS


@pytest.mark.xfail(strict=True, reason=_CHARGE_GAP)
def test_billing_tab_hides_the_card_charge_from_non_owners() -> None:
    assert "charge_card" in OWNER_ONLY_ACTIONS
