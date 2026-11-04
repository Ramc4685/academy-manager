"""Who may see family money amounts: the one seam (#553).

Every money field the People CRM returns (balance, open and overdue invoice
counts and amounts, the last failed charge) is gated by
:func:`can_view_family_money`, called once per request at the interface
layer. Nothing else may decide it.

The staff tiers of #553 (owner decision 2026-09-22) are decided in
``shared/auth/staff_tiers.py`` and this seam delegates to it:

* owner, admin and billing see amounts;
* front desk sees an "owes money" flag only (:func:`is_front_desk_only`),
  never an amount;
* coaches, parents and anyone else see nothing.

The family index reads (``GET /admin/families``, ``/families/summary`` and
``/families/{family_id}/record``) are open to the billing and front-desk
tiers (L2b, ``require_staff_tier("front_desk")``). :func:`family_money_view`
tells those routes which shape to serialize: amounts, the "owes money" flag
only, or nothing. Every other CRM route stays ``require_persona("admin")``.
"""

from __future__ import annotations

from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.auth.staff_tiers import (
    MONEY_VIEWER_ROLES,
    MoneyView,
    can_record_payment,
    can_view_money,
    is_front_desk_only,
    money_view,
)

__all__ = [
    "MONEY_VIEWER_ROLES",
    "MoneyView",
    "can_record_payment",
    "can_view_family_money",
    "family_money_view",
    "is_front_desk_only",
]


def can_view_family_money(claims: AuthClaims) -> bool:
    return can_view_money(claims)


def family_money_view(claims: AuthClaims) -> MoneyView:
    return money_view(claims)
