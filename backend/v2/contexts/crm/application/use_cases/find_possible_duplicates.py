"""``FindPossibleDuplicates``: the People CRM duplicate warning (spec §4 "Real forms", Phase 4c).

Asked by the Add family (Add parent), Add user and Add contact forms when an
email or phone field loses focus. Answers "does this look like someone this
academy already has?" with at most :data:`MAX_DUPLICATE_MATCHES` matches. A
warning only: nothing is merged, nothing is refused.

Sources, all inside the caller's academy:

1. the family index (parents with an account or a roster-only parent):
   in memory, built from this academy's own rows (email, phone, exact name);
2. family contacts (second parents, guardians): one equality lookup per
   field and per phone spelling (migration 0197 indexes);
3. users with an active membership here (staff, and parents already found in
   1 are skipped): identity's lookup by normalised email;
4. inquiries (``crm_contacts``): one equality lookup per field and spelling.

The academy comes from the request's tenant (the repositories read it from
the tenant context; the family index and the member lookup are handed the
same id), so another academy's people are never looked at. Queries are
merged in code, never an ``$or`` (#878/#894). Contact details in the answer
are masked. A failing family index is skipped, not an error: the warning is
best effort and must never block the form.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

from backend.v2.contexts.crm.application.family_index import FamilyIndexUnavailable
from backend.v2.contexts.crm.application.ports import (
    AcademyMemberLookup,
    CrmContactLookup,
    FamilyContactLookup,
    FamilyIndexSource,
)
from backend.v2.contexts.crm.domain.duplicates import (
    MAX_DUPLICATE_MATCHES,
    DuplicateKind,
    DuplicateMatch,
    DuplicateProbe,
    MatchedOn,
    build_probe,
    family_record_matches,
    mask_email,
    mask_phone,
)
from backend.v2.contexts.crm.domain.family_contacts import FamilyContact
from backend.v2.contexts.crm.domain.family_index import FamilyIndex
from backend.v2.contexts.crm.domain.models import CrmContact

log = logging.getLogger(__name__)

#: Rows read per lookup: enough to fill the answer after de-duplication.
_LOOKUP_LIMIT = MAX_DUPLICATE_MATCHES


@dataclass(frozen=True)
class DuplicateCheckQuery:
    email: str | None = None
    phone: str | None = None
    name: str | None = None


def family_link(family_id: str) -> str:
    return f"/admin/families/{quote(family_id, safe='')}"


def user_link(user_id: str) -> str:
    return f"/admin/users/{quote(user_id, safe='')}"


class _Collector:
    """Keeps the first match per record, merging the reasons it matched."""

    def __init__(self) -> None:
        self._order: list[tuple[DuplicateKind, str]] = []
        self._matches: dict[tuple[DuplicateKind, str], DuplicateMatch] = {}

    def add(self, match: DuplicateMatch) -> None:
        key = (match.kind, match.record_id)
        existing = self._matches.get(key)
        if existing is None:
            self._order.append(key)
            self._matches[key] = match
            return
        merged = tuple(dict.fromkeys((*existing.matched_on, *match.matched_on)))
        self._matches[key] = DuplicateMatch(
            kind=existing.kind,
            record_id=existing.record_id,
            display_name=existing.display_name,
            email_masked=existing.email_masked,
            phone_masked=existing.phone_masked,
            link=existing.link,
            matched_on=merged,
        )

    def result(self) -> list[DuplicateMatch]:
        ordered = [self._matches[key] for key in self._order]
        # A contact match (email or phone) is stronger than a same-name match.
        ordered.sort(key=lambda match: match.matched_on == ("name",))
        return ordered[:MAX_DUPLICATE_MATCHES]


class FindPossibleDuplicates:
    def __init__(
        self,
        *,
        families: FamilyIndexSource,
        family_contacts: FamilyContactLookup,
        members: AcademyMemberLookup,
        inquiries: CrmContactLookup,
    ) -> None:
        self._families = families
        self._family_contacts = family_contacts
        self._members = members
        self._inquiries = inquiries

    async def execute(self, academy_id: str, query: DuplicateCheckQuery) -> list[DuplicateMatch]:
        probe = build_probe(email=query.email, phone=query.phone, name=query.name)
        if probe.is_empty:
            return []
        found = _Collector()
        index = await self._family_index(academy_id)
        if index is not None:
            self._match_families(index, probe, found)
        await self._match_family_contacts(probe, found)
        await self._match_member(academy_id, probe, index, found)
        await self._match_inquiries(probe, found)
        return found.result()

    async def _family_index(self, academy_id: str) -> FamilyIndex | None:
        try:
            return await self._families.build(academy_id)
        except FamilyIndexUnavailable:
            log.warning("duplicate check: family index unavailable; families skipped")
            return None

    @staticmethod
    def _match_families(index: FamilyIndex, probe: DuplicateProbe, found: _Collector) -> None:
        for record in index.families:
            matched = family_record_matches(record, probe)
            if not matched:
                continue
            found.add(
                DuplicateMatch(
                    kind="family",
                    record_id=record.family_id,
                    display_name=record.parent_name or "Unnamed family",
                    email_masked=mask_email(record.email),
                    phone_masked=mask_phone(record.phone),
                    link=family_link(record.family_id),
                    matched_on=matched,
                )
            )

    async def _match_family_contacts(self, probe: DuplicateProbe, found: _Collector) -> None:
        batches: list[tuple[MatchedOn, list[FamilyContact]]] = []
        if probe.email is not None:
            batches.append(("email", await self._family_contacts.find_by_email(probe.email)))
        for spelling in probe.phone_variants:
            rows = await self._family_contacts.find_by_phone_digits(spelling)
            batches.append(("phone", rows))
        for reason, rows in batches:
            for contact in rows:
                found.add(
                    DuplicateMatch(
                        kind="family_contact",
                        record_id=contact.contact_id,
                        display_name=contact.name,
                        email_masked=mask_email(contact.email),
                        phone_masked=mask_phone(contact.phone_digits),
                        link=family_link(contact.parent_id),
                        matched_on=(reason,),
                    )
                )

    async def _match_member(
        self,
        academy_id: str,
        probe: DuplicateProbe,
        index: FamilyIndex | None,
        found: _Collector,
    ) -> None:
        if probe.email is None:
            return
        member = await self._members.find_member_by_email(academy_id, probe.email)
        if member is None:
            return
        if index is not None and member.user_id in index.family_by_alias:
            return  # already reported as their family
        found.add(
            DuplicateMatch(
                kind="user",
                record_id=member.user_id,
                display_name=member.display_name or "Unnamed user",
                email_masked=mask_email(member.email),
                phone_masked=mask_phone(member.phone),
                link=user_link(member.user_id),
                matched_on=("email",),
            )
        )

    async def _match_inquiries(self, probe: DuplicateProbe, found: _Collector) -> None:
        batches: list[tuple[MatchedOn, list[CrmContact]]] = []
        if probe.email is not None:
            batches.append(("email", await self._inquiries.find_by_email(probe.email)))
        for spelling in probe.phone_variants:
            batches.append(("phone", await self._inquiries.find_by_phone_digits(spelling)))
        for reason, rows in batches:
            for contact in rows:
                family_id = contact.linked_family_id or contact.converted_parent_id
                found.add(
                    DuplicateMatch(
                        kind="inquiry",
                        record_id=contact.contact_id,
                        display_name=contact.name,
                        email_masked=mask_email(contact.email),
                        phone_masked=mask_phone(contact.phone_digits),
                        link=family_link(family_id) if family_id else None,
                        matched_on=(reason,),
                    )
                )
