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

The CRM routes are still ``require_persona("admin")``, so today every caller
that reaches one is an admin and the answer is True. Opening CRM reads to the
billing and front-desk tiers, and the front-desk flag itself, are the
redaction slice (L2b); they only have to call these functions.
"""

from __future__ import annotations

from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.auth.staff_tiers import (
    MONEY_VIEWER_ROLES,
    can_record_payment,
    can_view_money,
    is_front_desk_only,
)

__all__ = [
    "MONEY_VIEWER_ROLES",
    "can_record_payment",
    "can_view_family_money",
    "is_front_desk_only",
]


def can_view_family_money(claims: AuthClaims) -> bool:
    return can_view_money(claims)
