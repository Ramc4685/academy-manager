"""Composition for the People CRM duplicate warning (Phase 4c).

``POST /admin/people/duplicate-check`` answers from ``FindPossibleDuplicates``
(``contexts/crm``). Wiring only. The CRM context may not import identity, so
this module hands it identity's "user with this email, only if a member of
this academy" lookup as a small adapter: the users lookup is global (one
equality on ``normalized_email``), and the membership check takes the
academy at CALL time (never captured here), exactly like the follow-up
assignee check in ``composition/families_crm.py``.

The bundle is attached lazily by ``interfaces/admin/people_duplicate_routes.py``
on first use (``app.state.admin_people_duplicates``) and reuses the app's
cached family index when there is one, so ``main.py`` stays untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.composition.families_crm import FAMILY_INDEX_CACHE_TTL_SECONDS, _index_model
from backend.v2.contexts.crm.application.use_cases.find_possible_duplicates import (
    FindPossibleDuplicates,
)
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.contexts.crm.infrastructure.mongo_family_contacts_repo import (
    MongoFamilyContactRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_membership_repo import (
    MongoMembershipRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository


@dataclass(frozen=True)
class _Member:
    user_id: str
    display_name: str | None
    email: str | None
    phone: str | None


class _AcademyMemberDirectory:
    """Identity's user by normalised email, kept only with an ACTIVE membership
    in the asked academy (any role)."""

    def __init__(self, db: Any) -> None:
        self._users = MongoUserRepository(db)
        self._memberships = MongoMembershipRepository(db)

    async def find_member_by_email(self, academy_id: str, email: str) -> _Member | None:
        found = await self._users.find_alias_set_by_normalized_email(email)
        if found is None:
            return None
        membership = await self._memberships.get_membership(
            academy_id, found.canonical_id, aliases=sorted(found.aliases)
        )
        if membership is None or not membership.is_active():
            return None
        return _Member(
            user_id=found.canonical_id,
            display_name=found.display_name,
            email=found.email,
            phone=found.phone,
        )


@dataclass(frozen=True)
class AdminPeopleDuplicates:
    find: FindPossibleDuplicates


def compose_admin_people_duplicates(db: Any, *, cached_index: Any = None) -> AdminPeopleDuplicates:
    """``cached_index`` is the app's shared family index when there is one."""
    families = cached_index or _index_model(db, FAMILY_INDEX_CACHE_TTL_SECONDS)
    return AdminPeopleDuplicates(
        find=FindPossibleDuplicates(
            families=families,
            family_contacts=MongoFamilyContactRepository(db),
            members=_AcademyMemberDirectory(db),
            inquiries=MongoCrmContactRepository(db),
        )
    )
