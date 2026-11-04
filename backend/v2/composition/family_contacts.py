"""Composition for family contacts and family details (People CRM Phase 4b).

``GET/POST /admin/families/{id}/contacts``, ``PATCH/DELETE .../contacts/{cid}``
and ``GET/PATCH /admin/families/{id}/details``. Wiring only.

The use cases share the family index that ``composition/families_crm.py``
builds for ``app.state.admin_family_index`` (the one "is this a family of the
academy" check, with its one-minute cache), plus a fresh build for the miss
re-check, exactly as the notes do.

The bundle is attached lazily by ``interfaces/admin/family_contacts_routes.py``
on first use (``app.state.admin_family_contacts``), which keeps ``main.py`` and
``composition/families_crm.py`` untouched while other open changes edit them.
A later change may move the one line into ``main.py`` beside the family index.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.composition.families_crm import FAMILY_INDEX_CACHE_TTL_SECONDS, _index_model
from backend.v2.contexts.crm.application.family_directory import IndexFamilyDirectory
from backend.v2.contexts.crm.application.use_cases.family_contacts import (
    AddFamilyContact,
    DeleteFamilyContact,
    GetFamilyDetails,
    ListFamilyContacts,
    UpdateFamilyContact,
    UpdateFamilyDetails,
)
from backend.v2.contexts.crm.infrastructure.mongo_family_contacts_repo import (
    MongoFamilyContactRepository,
    MongoFamilyDetailsRepository,
)


@dataclass(frozen=True)
class AdminFamilyContacts:
    list: ListFamilyContacts
    add: AddFamilyContact
    update: UpdateFamilyContact
    delete: DeleteFamilyContact
    get_details: GetFamilyDetails
    update_details: UpdateFamilyDetails


def compose_admin_family_contacts(db: Any, *, cached_index: Any = None) -> AdminFamilyContacts:
    """``cached_index`` is the app's shared family index when there is one, so
    the contacts reuse its cache instead of building a second copy."""
    cached = cached_index or _index_model(db, FAMILY_INDEX_CACHE_TTL_SECONDS)
    families = IndexFamilyDirectory(cached=cached, fresh=_index_model(db, 0.0))
    contacts = MongoFamilyContactRepository(db)
    details = MongoFamilyDetailsRepository(db)
    return AdminFamilyContacts(
        list=ListFamilyContacts(contacts, families),
        add=AddFamilyContact(contacts, families),
        update=UpdateFamilyContact(contacts, families),
        delete=DeleteFamilyContact(contacts, families),
        get_details=GetFamilyDetails(details, families),
        update_details=UpdateFamilyDetails(details, families),
    )
