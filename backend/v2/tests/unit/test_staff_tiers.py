"""Staff money tiers (#553): who sees amounts, who records payments.

Owner decision 2026-09-22: owner does everything; billing sees amounts and
records payments; front desk sees an "owes money" flag only. Existing admin
memberships keep the money capabilities they already had.
"""

from __future__ import annotations

import pytest

from backend.v2.contexts.crm.application.money_visibility import (
    can_record_payment,
    can_view_family_money,
    is_front_desk_only,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.auth.staff_tiers import can_view_money


def _claims(*roles: str) -> AuthClaims:
    return AuthClaims(
        user_id="u-1",
        email="staff@example.com",
        academy_id="acad",
        roles=roles,  # type: ignore[arg-type]
    )


# (roles, sees amounts, records payments, front-desk only)
MATRIX = [
    (("owner",), True, True, False),
    (("admin", "owner"), True, True, False),
    (("admin",), True, True, False),
    (("billing",), True, True, False),
    (("front_desk",), False, False, True),
    (("coach",), False, False, False),
    (("assistant_coach",), False, False, False),
    (("parent",), False, False, False),
    (("student",), False, False, False),
    ((), False, False, False),
    # Roles are additive: the widest tier wins.
    (("front_desk", "billing"), True, True, False),
    (("front_desk", "admin"), True, True, False),
    (("front_desk", "coach"), False, False, True),
    (("billing", "coach"), True, True, False),
]


@pytest.mark.parametrize(("roles", "sees", "records", "desk_only"), MATRIX, ids=str)
def test_staff_tier_matrix(
    roles: tuple[str, ...], sees: bool, records: bool, desk_only: bool
) -> None:
    claims = _claims(*roles)
    assert can_view_family_money(claims) is sees
    assert can_view_money(claims) is sees
    assert can_record_payment(claims) is records
    assert is_front_desk_only(claims) is desk_only


def test_front_desk_never_sees_an_amount_or_records_a_payment() -> None:
    claims = _claims("front_desk")
    assert not can_view_family_money(claims)
    assert not can_record_payment(claims)


def test_platform_roles_grant_no_money_tier() -> None:
    claims = AuthClaims(
        user_id="u-1",
        email="ops@example.com",
        academy_id="acad",
        roles=(),
        platform_roles=("platform_admin",),
    )
    assert not can_view_family_money(claims)
    assert not can_record_payment(claims)
    assert not is_front_desk_only(claims)


# --- L2b: family index reads and the money view -----------------------------

_MONEY_VIEWS: list[tuple[tuple[str, ...], str, bool]] = [
    (("owner",), "amounts", True),
    (("admin",), "amounts", True),
    (("billing",), "amounts", True),
    (("front_desk",), "flag", True),
    (("front_desk", "billing"), "amounts", True),
    (("front_desk", "coach"), "flag", True),
    (("coach",), "none", False),
    (("assistant_coach",), "none", False),
    (("parent",), "none", False),
    ((), "none", False),
]


@pytest.mark.parametrize(("roles", "view", "reads_index"), _MONEY_VIEWS)
def test_money_view_and_family_index_reads(
    roles: tuple[str, ...], view: str, reads_index: bool
) -> None:
    from backend.v2.contexts.crm.application.money_visibility import family_money_view
    from backend.v2.shared.auth.staff_tiers import can_read_family_index

    claims = _claims(*roles)
    assert family_money_view(claims) == view
    assert can_read_family_index(claims) is reads_index
    # The view and the older boolean seam never disagree.
    assert (view == "amounts") is can_view_family_money(claims)
