"""Staff money tiers: owner, billing, front desk (#553).

Owner decision 2026-09-22 (docs/roadmap/2026-09-22-product-roadmap.md,
section 6 item 2):

* **owner**: every money action. Money-moving actions (refund, void, card
  charge, discounts, adjustments, fees, payroll approval, Stripe disconnect,
  role management) are owner-only and stay behind ``require_owner``; nothing
  here widens them.
* **billing**: sees family money amounts and records payments the family
  already made (manual record-payment, mark-paid).
* **front desk**: an "owes money" flag only. No amounts, no money writes.

``admin`` is the pre-existing day-to-day operations role. Existing admin
memberships keep exactly the money capabilities they had before the tiers
(spec 2026-09-04 role model: admins record manual payments and see
balances), so ``admin`` sits in the billing tier. A membership holding
``admin`` alongside ``front_desk`` is an admin: roles are additive and the
widest one wins.

These are the only predicates that decide a staff money tier. Route guards
(``interfaces/admin/staff_tier.py``) and the CRM money seam
(``contexts/crm/application/money_visibility.py``) both call them, so a
tier change is a one-line change here. Every role is academy-scoped:
``claims.roles`` only ever holds the request tenant's membership roles, so
a billing member of one academy is nobody in another.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:  # pragma: no cover - typing only
    from backend.v2.shared.auth.claims import AuthClaims

#: Roles that see family money amounts (balances, invoice amounts).
MONEY_VIEWER_ROLES: Final[frozenset[str]] = frozenset({"owner", "admin", "billing"})

#: Roles that may record a payment the family already made. Never a refund,
#: void, charge or discount: those are owner-only.
PAYMENT_RECORDER_ROLES: Final[frozenset[str]] = frozenset({"owner", "admin", "billing"})

#: The staff tiers of #553 that are not ``admin``/``owner``.
STAFF_TIER_ROLES: Final[frozenset[str]] = frozenset({"billing", "front_desk"})

#: Roles that may read the People CRM family index (the Families list, its
#: scope tiles and one family's record row). Front desk reads it with money
#: redacted to the "owes money" flag; billing, admin and owner see amounts.
FAMILY_INDEX_READER_ROLES: Final[frozenset[str]] = frozenset(
    {"owner", "admin", "billing", "front_desk"}
)

#: How a caller sees family money: ``amounts`` (owner, admin, billing),
#: ``flag`` (front desk: "owes money" yes or no, never an amount) or
#: ``none``.
MoneyView = Literal["amounts", "flag", "none"]


def can_view_money(claims: AuthClaims) -> bool:
    """True when the caller may see family money amounts."""

    return any(role in MONEY_VIEWER_ROLES for role in claims.roles)


def can_record_payment(claims: AuthClaims) -> bool:
    """True when the caller may record a payment the family already made."""

    return any(role in PAYMENT_RECORDER_ROLES for role in claims.roles)


def is_front_desk_only(claims: AuthClaims) -> bool:
    """True when ``front_desk`` is the caller's only staff money tier.

    Such a caller gets the "owes money" flag and never an amount. Holding
    ``owner``, ``admin`` or ``billing`` as well lifts the restriction.
    """

    return "front_desk" in claims.roles and not can_view_money(claims)


def can_read_family_index(claims: AuthClaims) -> bool:
    """True when the caller may read the family index (L2b, #553)."""

    return any(role in FAMILY_INDEX_READER_ROLES for role in claims.roles)


def money_view(claims: AuthClaims) -> MoneyView:
    """The one answer to "what may this caller see of a family's money"."""

    if can_view_money(claims):
        return "amounts"
    if is_front_desk_only(claims):
        return "flag"
    return "none"
