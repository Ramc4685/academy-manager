"""Family contacts and family details use cases, over fakes that mirror the stores.

The fakes (``tests/fixtures/crm_family_contacts_fakes.py``) enforce the
tenant ContextVar, the unique contact id and the partial per-family email
index the Mongo repositories do.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.crm.application.use_cases.family_contacts import (
    AddFamilyContact,
    ContactDraft,
    DeleteFamilyContact,
    GetFamilyDetails,
    ListFamilyContacts,
    UpdateFamilyContact,
    UpdateFamilyDetails,
    contact_changes,
    details_changes,
)
from backend.v2.contexts.crm.application.use_cases.family_notes import Actor
from backend.v2.contexts.crm.domain.errors import (
    DuplicateFamilyContactEmail,
    FamilyContactNotFound,
    FamilyNotFound,
    InvalidFamilyContact,
    InvalidFamilyDetails,
    TooManyFamilyContacts,
)
from backend.v2.contexts.crm.domain.family_contacts import MAX_CONTACTS_PER_FAMILY
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.fixtures.crm_family_contacts_fakes import (
    FakeFamilyContactRepository,
    FakeFamilyDetailsRepository,
)
from backend.v2.tests.fixtures.crm_family_fakes import FakeFamilyDirectory

A = "acad-a"
B = "acad-b"
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)
ACTOR = Actor(user_id="u-admin", roles=("admin",))


class World:
    def __init__(self) -> None:
        self.families = FakeFamilyDirectory()
        self.families.add(A, "p-1", "Testparent One", "fb-p-1")
        self.families.add(B, "p-b", "Testparent Bee")
        self.contacts = FakeFamilyContactRepository()
        self.details = FakeFamilyDetailsRepository()
        ids = (f"c-{n}" for n in itertools.count(1))
        self.list = ListFamilyContacts(self.contacts, self.families)
        self.add = AddFamilyContact(
            self.contacts, self.families, clock=lambda: NOW, new_id=lambda: next(ids)
        )
        self.update = UpdateFamilyContact(self.contacts, self.families, clock=lambda: NOW)
        self.delete = DeleteFamilyContact(self.contacts, self.families)
        self.get_details = GetFamilyDetails(self.details, self.families)
        self.update_details = UpdateFamilyDetails(self.details, self.families, clock=lambda: NOW)


@pytest.fixture
def world() -> World:
    return World()


async def test_add_defaults_both_switches_off_and_lands_on_the_canonical_family(
    world: World,
) -> None:
    with tenant_scope(A):
        row = await world.add.execute(
            academy_id=A,
            parent_id="fb-p-1",
            draft=ContactDraft(name="  Second   Testparent ", email=" Second@Example.TEST "),
            actor=ACTOR,
        )
        assert row.parent_id == "p-1"
        assert row.name == "Second Testparent"
        assert row.email == "second@example.test"
        assert row.gets_notices is False and row.gets_invoices is False
        assert row.created_by == "u-admin"
        family_id, rows = await world.list.execute(academy_id=A, parent_id="p-1")
    assert family_id == "p-1"
    assert [r.contact_id for r in rows] == [row.contact_id]


async def test_validation_errors_name_the_field(world: World) -> None:
    cases = [
        (ContactDraft(name="  "), "name"),
        (ContactDraft(name="X", email="not-an-email"), "email"),
        (ContactDraft(name="X", phone="call me"), "phone"),
        (ContactDraft(name="X"), "email"),  # neither email nor phone
        (ContactDraft(name="X", relationship="boss", email="x@example.test"), "relationship"),
        (ContactDraft(name="X", phone="555-010-0002", gets_notices=True), "gets_notices"),
        (ContactDraft(name="X", phone="555-010-0002", gets_invoices=True), "gets_invoices"),
    ]
    with tenant_scope(A):
        for draft, field in cases:
            with pytest.raises(InvalidFamilyContact) as err:
                await world.add.execute(academy_id=A, parent_id="p-1", draft=draft, actor=ACTOR)
            assert err.value.details["field"] == field, draft


async def test_duplicate_email_in_one_family_is_rejected_but_blank_emails_are_not(
    world: World,
) -> None:
    with tenant_scope(A):
        await world.add.execute(
            academy_id=A,
            parent_id="p-1",
            draft=ContactDraft(name="One", email="dup@example.test"),
            actor=ACTOR,
        )
        with pytest.raises(DuplicateFamilyContactEmail):
            await world.add.execute(
                academy_id=A,
                parent_id="p-1",
                draft=ContactDraft(name="Two", email="DUP@example.test"),
                actor=ACTOR,
            )
        for name in ("Phone A", "Phone B"):
            await world.add.execute(
                academy_id=A,
                parent_id="p-1",
                draft=ContactDraft(name=name, phone="555-010-0003"),
                actor=ACTOR,
            )
        _, rows = await world.list.execute(academy_id=A, parent_id="p-1")
    assert len(rows) == 3


async def test_update_toggles_switches_and_clears_email(world: World) -> None:
    with tenant_scope(A):
        row = await world.add.execute(
            academy_id=A,
            parent_id="p-1",
            draft=ContactDraft(name="One", email="one@example.test", phone="555-010-0004"),
            actor=ACTOR,
        )
        on = await world.update.execute(
            academy_id=A,
            parent_id="p-1",
            contact_id=row.contact_id,
            changes=contact_changes({"gets_notices": True}),
            actor=ACTOR,
        )
        assert on.gets_notices is True and on.gets_invoices is False
        # Clearing the email while Gets notices is on would leave nothing to send to.
        with pytest.raises(InvalidFamilyContact) as err:
            await world.update.execute(
                academy_id=A,
                parent_id="p-1",
                contact_id=row.contact_id,
                changes=contact_changes({"email": None}),
                actor=ACTOR,
            )
        assert err.value.details["field"] == "gets_notices"
        cleared = await world.update.execute(
            academy_id=A,
            parent_id="p-1",
            contact_id=row.contact_id,
            changes=contact_changes({"email": "", "gets_notices": False}),
            actor=ACTOR,
        )
        assert cleared.email is None and cleared.phone == "555-010-0004"
        unchanged = await world.update.execute(
            academy_id=A,
            parent_id="p-1",
            contact_id=row.contact_id,
            changes=contact_changes({}),
            actor=ACTOR,
        )
        assert unchanged == cleared


async def test_cap_on_contacts_per_family(world: World) -> None:
    with tenant_scope(A):
        for n in range(MAX_CONTACTS_PER_FAMILY):
            await world.add.execute(
                academy_id=A,
                parent_id="p-1",
                draft=ContactDraft(name=f"C{n}", phone="555-010-0005"),
                actor=ACTOR,
            )
        with pytest.raises(TooManyFamilyContacts):
            await world.add.execute(
                academy_id=A,
                parent_id="p-1",
                draft=ContactDraft(name="One more", phone="555-010-0005"),
                actor=ACTOR,
            )


async def test_other_academy_family_and_contact_are_not_found(world: World) -> None:
    with tenant_scope(A):
        row = await world.add.execute(
            academy_id=A,
            parent_id="p-1",
            draft=ContactDraft(name="One", email="one@example.test"),
            actor=ACTOR,
        )
        with pytest.raises(FamilyNotFound):
            await world.list.execute(academy_id=A, parent_id="p-b")
    with tenant_scope(B):
        with pytest.raises(FamilyNotFound):
            await world.list.execute(academy_id=B, parent_id="p-1")
        # Academy B's own family cannot reach A's contact by id either.
        with pytest.raises(FamilyContactNotFound):
            await world.update.execute(
                academy_id=B,
                parent_id="p-b",
                contact_id=row.contact_id,
                changes=contact_changes({"gets_notices": True}),
                actor=ACTOR,
            )
        with pytest.raises(FamilyContactNotFound):
            await world.delete.execute(
                academy_id=B, parent_id="p-b", contact_id=row.contact_id, actor=ACTOR
            )
    with tenant_scope(A):
        await world.delete.execute(
            academy_id=A, parent_id="p-1", contact_id=row.contact_id, actor=ACTOR
        )
        _, rows = await world.list.execute(academy_id=A, parent_id="p-1")
        assert rows == []


async def test_details_default_empty_then_partial_updates(world: World) -> None:
    with tenant_scope(A):
        empty = await world.get_details.execute(academy_id=A, parent_id="fb-p-1")
        assert empty.parent_id == "p-1" and empty.address is None and empty.tags == ()
        saved = await world.update_details.execute(
            academy_id=A,
            parent_id="p-1",
            changes=details_changes(
                {
                    "address": " 1 Test Street ",
                    "preferred_channel": "sms",
                    "tags": ["VIP", "vip", " sibling ", ""],
                }
            ),
            actor=ACTOR,
        )
        assert saved.address == "1 Test Street"
        assert saved.preferred_channel == "sms"
        assert saved.tags == ("VIP", "sibling")
        assert saved.updated_by == "u-admin"
        again = await world.update_details.execute(
            academy_id=A,
            parent_id="p-1",
            changes=details_changes({"heard_about_us": "A friend", "address": None}),
            actor=ACTOR,
        )
        assert again.address is None
        assert again.heard_about_us == "A friend"
        assert again.preferred_channel == "sms"
        with pytest.raises(InvalidFamilyDetails) as err:
            await world.update_details.execute(
                academy_id=A,
                parent_id="p-1",
                changes=details_changes({"preferred_channel": "pigeon"}),
                actor=ACTOR,
            )
        assert err.value.details["field"] == "preferred_channel"
    with tenant_scope(B):
        with pytest.raises(FamilyNotFound):
            await world.get_details.execute(academy_id=B, parent_id="p-1")
