"""Family contacts and family details (People CRM spec §4 "Details", Phase 4b).

Every use case first proves ``parent_id`` is a family of the caller's academy
through ``FamilyDirectory`` (404 otherwise) and then works on the canonical
family id, so a contact added from an alias URL lands on the same family the
audience resolver expands.

Both switches on a contact (``gets_notices``, ``gets_invoices``) start OFF and
change only when staff set them here; nothing else in the system turns them
on. Any staff member (the admin persona) may manage contacts and details:
there is no money on them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from backend.v2.contexts.crm.application.ports import (
    FamilyContactRepository,
    FamilyDetailsRepository,
    FamilyDirectory,
)
from backend.v2.contexts.crm.application.use_cases.family_notes import (
    Actor,
    resolve_family,
    utc_now_ms,
)
from backend.v2.contexts.crm.domain.errors import (
    FamilyContactNotFound,
    TooManyFamilyContacts,
)
from backend.v2.contexts.crm.domain.family_contacts import (
    CONTACT_RELATIONSHIPS,
    MAX_ADDRESS_LEN,
    MAX_CONTACT_NAME_LEN,
    MAX_CONTACTS_PER_FAMILY,
    MAX_EMAIL_LEN,
    MAX_HEARD_ABOUT_US_LEN,
    MAX_PHONE_LEN,
    MAX_TAG_LEN,
    MAX_TAGS,
    PREFERRED_CHANNELS,
    FamilyContact,
    FamilyDetails,
    check_contact_reachable,
    normalize_address,
    normalize_contact_email,
    normalize_contact_name,
    normalize_contact_phone,
    normalize_heard_about_us,
    normalize_preferred_channel,
    normalize_relationship,
    normalize_tags,
)
from backend.v2.shared.ids import new_ulid

# Re-exported for the admin BFF (interfaces may not import the domain).
__all__ = [
    "CONTACT_RELATIONSHIPS",
    "MAX_ADDRESS_LEN",
    "MAX_CONTACTS_PER_FAMILY",
    "MAX_CONTACT_NAME_LEN",
    "MAX_EMAIL_LEN",
    "MAX_HEARD_ABOUT_US_LEN",
    "MAX_PHONE_LEN",
    "MAX_TAGS",
    "MAX_TAG_LEN",
    "PREFERRED_CHANNELS",
    "AddFamilyContact",
    "ContactChanges",
    "ContactDraft",
    "DeleteFamilyContact",
    "DetailsChanges",
    "FamilyContact",
    "FamilyDetails",
    "GetFamilyDetails",
    "ListFamilyContacts",
    "UpdateFamilyContact",
    "UpdateFamilyDetails",
    "contact_changes",
    "details_changes",
]


@dataclass(frozen=True)
class ContactDraft:
    name: str
    relationship: str = "parent"
    email: str | None = None
    phone: str | None = None
    gets_notices: bool = False
    gets_invoices: bool = False


@dataclass(frozen=True)
class ContactChanges:
    """A partial update. Only the names in ``provided`` change; for ``email``
    and ``phone`` a provided ``None`` (or blank) clears the field."""

    provided: frozenset[str] = field(default_factory=frozenset)
    name: str | None = None
    relationship: str | None = None
    email: str | None = None
    phone: str | None = None
    gets_notices: bool | None = None
    gets_invoices: bool | None = None


@dataclass(frozen=True)
class DetailsChanges:
    """A partial update of the family details. Only ``provided`` names change;
    a provided ``None`` (or blank) clears a text field."""

    provided: frozenset[str] = field(default_factory=frozenset)
    address: str | None = None
    preferred_channel: str | None = None
    heard_about_us: str | None = None
    tags: tuple[str, ...] | None = None


class ListFamilyContacts:
    def __init__(self, contacts: FamilyContactRepository, families: FamilyDirectory) -> None:
        self._contacts = contacts
        self._families = families

    async def execute(self, *, academy_id: str, parent_id: str) -> tuple[str, list[FamilyContact]]:
        family_id = await resolve_family(self._families, academy_id, parent_id)
        return family_id, await self._contacts.list_for_family(family_id)


class AddFamilyContact:
    def __init__(
        self,
        contacts: FamilyContactRepository,
        families: FamilyDirectory,
        *,
        clock: Callable[[], datetime] = utc_now_ms,
        new_id: Callable[[], str] = new_ulid,
    ) -> None:
        self._contacts = contacts
        self._families = families
        self._clock = clock
        self._new_id = new_id

    async def execute(
        self, *, academy_id: str, parent_id: str, draft: ContactDraft, actor: Actor
    ) -> FamilyContact:
        name = normalize_contact_name(draft.name)
        relationship = normalize_relationship(draft.relationship)
        email = normalize_contact_email(draft.email)
        phone, digits = normalize_contact_phone(draft.phone)
        check_contact_reachable(
            email=email,
            phone=phone,
            gets_notices=draft.gets_notices,
            gets_invoices=draft.gets_invoices,
        )
        family_id = await resolve_family(self._families, academy_id, parent_id)
        if await self._contacts.count_for_family(family_id) >= MAX_CONTACTS_PER_FAMILY:
            raise TooManyFamilyContacts(
                f"A family can have at most {MAX_CONTACTS_PER_FAMILY} contacts.",
                parent_id=family_id,
            )
        now = self._clock()
        return await self._contacts.add(
            FamilyContact(
                contact_id=self._new_id(),
                academy_id=academy_id,
                parent_id=family_id,
                name=name,
                relationship=relationship,
                email=email,
                phone=phone,
                phone_digits=digits,
                gets_notices=draft.gets_notices,
                gets_invoices=draft.gets_invoices,
                created_by=actor.user_id,
                created_at=now,
                updated_at=now,
            )
        )


class UpdateFamilyContact:
    def __init__(
        self,
        contacts: FamilyContactRepository,
        families: FamilyDirectory,
        *,
        clock: Callable[[], datetime] = utc_now_ms,
    ) -> None:
        self._contacts = contacts
        self._families = families
        self._clock = clock

    async def execute(
        self,
        *,
        academy_id: str,
        parent_id: str,
        contact_id: str,
        changes: ContactChanges,
        actor: Actor,
    ) -> FamilyContact:
        family_id = await resolve_family(self._families, academy_id, parent_id)
        current = await self._contacts.get(family_id, contact_id)
        if current is None:
            raise FamilyContactNotFound("contact not found", contact_id=contact_id)
        fields: dict[str, object] = {}
        given = changes.provided
        if "name" in given:
            fields["name"] = normalize_contact_name(changes.name or "")
        if "relationship" in given:
            fields["relationship"] = normalize_relationship(changes.relationship or "")
        if "email" in given:
            fields["email"] = normalize_contact_email(changes.email)
        if "phone" in given:
            fields["phone"], fields["phone_digits"] = normalize_contact_phone(changes.phone)
        for switch in ("gets_notices", "gets_invoices"):
            if switch in given and getattr(changes, switch) is not None:
                fields[switch] = bool(getattr(changes, switch))
        merged = current.model_copy(update=fields)
        check_contact_reachable(
            email=merged.email,
            phone=merged.phone,
            gets_notices=merged.gets_notices,
            gets_invoices=merged.gets_invoices,
        )
        if not fields:
            return current
        fields["updated_at"] = self._clock()
        updated = await self._contacts.update(family_id, contact_id, changes=fields)
        if updated is None:  # removed between the read and the write
            raise FamilyContactNotFound("contact not found", contact_id=contact_id)
        return updated


class DeleteFamilyContact:
    def __init__(self, contacts: FamilyContactRepository, families: FamilyDirectory) -> None:
        self._contacts = contacts
        self._families = families

    async def execute(
        self, *, academy_id: str, parent_id: str, contact_id: str, actor: Actor
    ) -> None:
        family_id = await resolve_family(self._families, academy_id, parent_id)
        if not await self._contacts.delete(family_id, contact_id):
            raise FamilyContactNotFound("contact not found", contact_id=contact_id)


class GetFamilyDetails:
    def __init__(self, details: FamilyDetailsRepository, families: FamilyDirectory) -> None:
        self._details = details
        self._families = families

    async def execute(self, *, academy_id: str, parent_id: str) -> FamilyDetails:
        family_id = await resolve_family(self._families, academy_id, parent_id)
        stored = await self._details.get(family_id)
        return stored or FamilyDetails(academy_id=academy_id, parent_id=family_id)


class UpdateFamilyDetails:
    def __init__(
        self,
        details: FamilyDetailsRepository,
        families: FamilyDirectory,
        *,
        clock: Callable[[], datetime] = utc_now_ms,
    ) -> None:
        self._details = details
        self._families = families
        self._clock = clock

    async def execute(
        self, *, academy_id: str, parent_id: str, changes: DetailsChanges, actor: Actor
    ) -> FamilyDetails:
        fields: dict[str, object] = {}
        given = changes.provided
        if "address" in given:
            fields["address"] = normalize_address(changes.address)
        if "preferred_channel" in given:
            fields["preferred_channel"] = normalize_preferred_channel(changes.preferred_channel)
        if "heard_about_us" in given:
            fields["heard_about_us"] = normalize_heard_about_us(changes.heard_about_us)
        if "tags" in given:
            fields["tags"] = list(normalize_tags(changes.tags or ()))
        family_id = await resolve_family(self._families, academy_id, parent_id)
        if not fields:
            stored = await self._details.get(family_id)
            return stored or FamilyDetails(academy_id=academy_id, parent_id=family_id)
        return await self._details.upsert(
            family_id, changes=fields, updated_by=actor.user_id, updated_at=self._clock()
        )


def details_changes(values: Mapping[str, object]) -> DetailsChanges:
    """Build a ``DetailsChanges`` from a mapping of only the provided fields."""
    tags = values.get("tags")
    return DetailsChanges(
        provided=frozenset(values),
        address=values.get("address"),  # type: ignore[arg-type]
        preferred_channel=values.get("preferred_channel"),  # type: ignore[arg-type]
        heard_about_us=values.get("heard_about_us"),  # type: ignore[arg-type]
        tags=tuple(tags) if isinstance(tags, list | tuple) else None,
    )


def contact_changes(values: Mapping[str, object]) -> ContactChanges:
    """Build a ``ContactChanges`` from a mapping of only the provided fields."""
    return ContactChanges(
        provided=frozenset(values),
        name=values.get("name"),  # type: ignore[arg-type]
        relationship=values.get("relationship"),  # type: ignore[arg-type]
        email=values.get("email"),  # type: ignore[arg-type]
        phone=values.get("phone"),  # type: ignore[arg-type]
        gets_notices=values.get("gets_notices"),  # type: ignore[arg-type]
        gets_invoices=values.get("gets_invoices"),  # type: ignore[arg-type]
    )
