"""Staff-tier route guard for the admin BFF (#553).

The admin surface has three kinds of gate, and this module holds the third:

* ``require_persona("admin")``: day-to-day operations, admins only;
* ``require_owner()``: money governance, listed in
  :data:`backend.v2.interfaces.admin.owner_gate.OWNER_ONLY_ROUTE_PATHS`;
* :func:`require_staff_tier`: a route a staff tier (billing, front desk) may
  also reach, listed in :data:`STAFF_TIER_ROUTE_PATHS`.

Two tiers open routes:

* ``billing``: recording a payment the family already made
  (``record-payment`` on a ledger invoice, ``mark-paid`` on a legacy
  payment). Owner, admin or billing.
* ``front_desk``: reading the People CRM family index (the Families list,
  its scope tiles and one family's record row). Owner, admin, billing or
  front desk; the routes redact money per caller with
  ``money_visibility.family_money_view`` (front desk gets the "owes money"
  flag, never an amount). Front desk has no money write anywhere.

Owner and admin keep every route here, so existing tokens behave exactly as
before.

Misses are 404, like every persona and owner guard, so a route's existence
is never leaked. ``tests/structural/test_money_route_staff_tiers.py`` walks
the real router and holds :data:`STAFF_TIER_ROUTE_PATHS` and the dependency
chain equal in both directions, and keeps every money-moving route
owner-only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Final, Literal

from fastapi import Depends, HTTPException

from backend.v2.shared.auth.staff_tiers import can_read_family_index, can_record_payment

if TYPE_CHECKING:  # pragma: no cover - typing only
    from backend.v2.shared.auth.claims import AuthClaims

_ADMIN = "/api/v2/admin"

StaffTier = Literal["billing", "front_desk"]

#: Every admin route a staff tier opens, by tier.
STAFF_TIER_ROUTE_PATHS: Final[dict[StaffTier, frozenset[tuple[str, str]]]] = {
    "billing": frozenset(
        {
            # billing_routes.py: record a manual payment against a ledger invoice
            ("POST", f"{_ADMIN}/billing/invoices/{{invoice_id}}/record-payment"),
            # billing_routes.py: mark a legacy payment paid (cash, check at the desk)
            ("POST", f"{_ADMIN}/payments/{{payment_id}}/mark-paid"),
        }
    ),
    "front_desk": frozenset(
        {
            # family_index_routes.py: read-only, money redacted per caller (L2b)
            ("GET", f"{_ADMIN}/families"),
            ("GET", f"{_ADMIN}/families/summary"),
            ("GET", f"{_ADMIN}/families/{{family_id}}/record"),
        }
    ),
}

_TIER_CHECKS: Final[dict[StaffTier, Callable[[AuthClaims], bool]]] = {
    "billing": can_record_payment,
    "front_desk": can_read_family_index,
}


def require_staff_tier(tier: StaffTier) -> Callable[..., Awaitable[AuthClaims]]:
    """Admit owner, admin and the named staff tier; 404 for anyone else.

    ``billing``: owner, admin or billing (``staff_tiers.can_record_payment``).
    ``front_desk``: owner, admin, billing or front desk
    (``staff_tiers.can_read_family_index``). Coaches, parents and callers
    with no academy role get 404; so does front desk on a ``billing`` route.
    """

    from backend.v2.shared.auth.claims import get_auth_claims

    if tier not in _TIER_CHECKS:  # pragma: no cover - guarded by the Literal
        raise ValueError(f"unknown staff tier: {tier}")

    async def _dep(claims: AuthClaims = Depends(get_auth_claims)) -> AuthClaims:
        # `tier` stays a closure variable so the structural policy test can
        # read which tier a route admits.
        if not _TIER_CHECKS[tier](claims):
            raise HTTPException(status_code=404, detail="Not found")
        return claims

    return _dep
