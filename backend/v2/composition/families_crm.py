"""Composition for the People CRM family index (``/admin/families``, ``/summary``).

People CRM spec §1 and §7 Phase 2: wiring only, zero lines in
``composition/admin.py`` (at its line budget). The CRM context may not import
identity, enrollment or billing, so this module hands it each owner's
implementation of the CRM ports:

* identity's ``MongoUserRepository.resolve_parent_aliases`` (parent aliases,
  one equality lookup per field);
* enrollment's ``MongoStudentRepository.lifecycle_snapshots`` (the
  ``/admin/students`` lifecycle derivation, batched);
* billing's ``MongoFamilyMoneyReadModel`` (every family's money, the Billing
  tab's balance rule).

Nothing tenant-specific is captured: every read takes the request's
``academy_id``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.contexts.billing.infrastructure.family_money_read_model import (
    MongoFamilyMoneyReadModel,
)
from backend.v2.contexts.crm.infrastructure.family_index_read_model import (
    MongoFamilyIndexReadModel,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup

#: Spec §3.2: the index is rebuilt at most once a minute per academy, so the
#: list and the summary tiles of one page load share a build.
FAMILY_INDEX_CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class AdminFamilyIndex:
    index: MongoFamilyIndexReadModel


def compose_admin_family_index(db: Any) -> AdminFamilyIndex:
    return AdminFamilyIndex(
        index=MongoFamilyIndexReadModel(
            db,
            parents=MongoUserRepository(db),
            children=MongoStudentRepository(db),
            money=MongoFamilyMoneyReadModel(db),
            academy_timezone=academy_timezone_lookup(db),
            cache_ttl_seconds=FAMILY_INDEX_CACHE_TTL_SECONDS,
        )
    )
