"""Staff-tier memberships round-trip through the real store (#553).

``academy_memberships`` carries a production ``$jsonSchema`` validator
(migration 0132) whose ``roles`` items are plain strings, so the new
``billing`` and ``front_desk`` values need no migration. This proves it on a
real ``mongod`` with every migration replayed, and proves the stored row
deserializes into ``AuthClaims`` (the UIM12 failure mode: a role the claims
literal does not know locks the member out) and lands on the right tier.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.contexts.crm.application.money_visibility import (
    can_record_payment,
    can_view_family_money,
    is_front_desk_only,
)
from backend.v2.contexts.identity.domain.models import AcademyMembership
from backend.v2.contexts.identity.infrastructure.mongo_membership_repo import (
    MongoMembershipRepository,
)
from backend.v2.shared.auth.claims import AuthClaims


async def _claims_for(db: Any, academy_id: str, user_id: str) -> AuthClaims | None:
    membership = await MongoMembershipRepository(db).get_membership(academy_id, user_id)
    if membership is None or not membership.is_active():
        return None
    return AuthClaims(
        user_id=user_id,
        email=f"{user_id}@example.com",
        academy_id=academy_id,
        membership_id=membership.membership_id,
        roles=membership.roles,
    )


@pytest.mark.asyncio
async def test_billing_and_front_desk_memberships_store_and_load(real_db: Any) -> None:
    repo = MongoMembershipRepository(real_db)
    await repo.upsert_membership(
        AcademyMembership(
            membership_id="m-bill", academy_id="acad-a", user_id="u-bill", roles=("billing",)
        )
    )
    await repo.upsert_membership(
        AcademyMembership(
            membership_id="m-desk", academy_id="acad-a", user_id="u-desk", roles=("front_desk",)
        )
    )

    billing = await _claims_for(real_db, "acad-a", "u-bill")
    desk = await _claims_for(real_db, "acad-a", "u-desk")

    assert billing is not None and billing.roles == ("billing",)
    assert can_view_family_money(billing) and can_record_payment(billing)
    assert desk is not None and desk.roles == ("front_desk",)
    assert not can_view_family_money(desk) and not can_record_payment(desk)
    assert is_front_desk_only(desk)


@pytest.mark.asyncio
async def test_validator_accepts_a_raw_staff_tier_row(real_db: Any) -> None:
    """A raw insert (as the directory writes it) passes the collection validator."""
    await real_db["academy_memberships"].insert_one(
        {
            "membership_id": "m-raw",
            "academy_id": "acad-a",
            "user_id": "u-raw",
            "roles": ["front_desk", "billing"],
            "status": "active",
        }
    )

    claims = await _claims_for(real_db, "acad-a", "u-raw")

    assert claims is not None
    assert set(claims.roles) == {"front_desk", "billing"}
    assert can_record_payment(claims) and not is_front_desk_only(claims)


@pytest.mark.asyncio
async def test_a_staff_tier_in_one_academy_is_nothing_in_another(real_db: Any) -> None:
    await MongoMembershipRepository(real_db).upsert_membership(
        AcademyMembership(
            membership_id="m-bill-a", academy_id="acad-a", user_id="u-bill", roles=("billing",)
        )
    )

    assert await _claims_for(real_db, "acad-b", "u-bill") is None
