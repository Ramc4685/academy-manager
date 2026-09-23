"""Who may see family money amounts: the one seam (#553).

Every money field the People CRM returns (balance, open and overdue invoice
counts and amounts, the last failed charge) is gated by
:func:`can_view_family_money`, called once per request at the interface
layer. Nothing else may decide it.

Today the CRM routes are ``require_persona("admin")`` and the answer is
"owner or admin", so for every caller that reaches a CRM route it is True.
That is deliberate: this is the seam the staff tiers of #553 (owner, billing,
front desk; owner decision 2026-09-22, spec §8 decision 4) will narrow, and
narrowing it must be a one-function change rather than a hunt through every
serializer. #553 itself is not built here. A later front-desk "owes money"
flag without amounts (spec §3.2) is a separate, non-money field.
"""

from __future__ import annotations

from typing import Final

from backend.v2.shared.auth.claims import AuthClaims

#: Academy roles that see family money amounts today.
MONEY_VIEWER_ROLES: Final[frozenset[str]] = frozenset({"owner", "admin"})


def can_view_family_money(claims: AuthClaims) -> bool:
    return any(role in MONEY_VIEWER_ROLES for role in claims.roles)
