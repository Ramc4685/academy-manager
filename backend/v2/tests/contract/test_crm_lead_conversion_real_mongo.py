"""``MarkLeadEnrolled`` on a real ``mongod`` (AI strategy Phase 1, item #1).

``real_db`` replays every migration, so the ``crm_contacts`` indexes are the
production ones. Checks, against the real ``MongoCrmContactRepository``:

* approval marks every contact of the academy with the parent's email
  ``enrolled`` with ``converted_parent_id`` and ``linked_family_id``, case
  and whitespace in the application's email notwithstanding;
* another academy's contact with the same email, a contact with another
  email, and a contact already ``enrolled`` are untouched;
* the inquiry conversion report now counts the converted lead;
* no email or no match writes nothing.

Skipped without a ``mongod``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from backend.v2.contexts.crm.application.use_cases.create_contact import (
    CreateContact,
    CreateContactCommand,
)
from backend.v2.contexts.crm.application.use_cases.lead_conversion import MarkLeadEnrolled
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.shared.tenancy import tenant_scope

A = "acad-lead-conv-a"
B = "acad-lead-conv-b"
NOW = datetime(2026, 11, 4, 18, 30, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)


def _cmd(name: str, email: str) -> CreateContactCommand:
    return CreateContactCommand(
        name=name, source="whatsapp_or_phone", email=email, created_by="staff-1"
    )


async def test_approval_enrolls_the_parents_inquiries_in_their_academy_only(
    real_db: Any,
) -> None:
    repo = MongoCrmContactRepository(real_db)
    create = CreateContact(repo, clock=lambda: NOW)
    with tenant_scope(A):
        first = (await create.execute(_cmd("Sample Parent", "parent@example.com"))).contact
        again = (await create.execute(_cmd("Sample Parent", "Parent@Example.com"))).contact
        other_email = (await create.execute(_cmd("Someone Else", "else@example.com"))).contact
        already = (await create.execute(_cmd("Earlier Family", "parent@example.com"))).contact
        await real_db["crm_contacts"].update_one(
            {"academy_id": A, "contact_id": already.contact_id},
            {"$set": {"pipeline_status": "enrolled", "converted_parent_id": "parent-old"}},
        )
    with tenant_scope(B):
        other_academy = (await create.execute(_cmd("Same Email", "parent@example.com"))).contact

    with tenant_scope(A):
        changed = await MarkLeadEnrolled(repo, clock=lambda: LATER).execute(
            parent_user_id="parent-1",
            parent_email="  Parent@Example.COM ",
            application_id="app-1",
        )
    assert changed == 2

    async def _row(contact_id: str) -> dict[str, Any]:
        doc = await real_db["crm_contacts"].find_one({"contact_id": contact_id})
        assert doc is not None
        return doc

    for contact in (first, again):
        doc = await _row(contact.contact_id)
        assert doc["pipeline_status"] == "enrolled"
        assert doc["converted_parent_id"] == "parent-1"
        assert doc["linked_family_id"] == "parent-1"
        assert doc["updated_at"].replace(tzinfo=UTC) == LATER
    assert (await _row(other_email.contact_id))["pipeline_status"] == "lead"
    untouched = await _row(already.contact_id)
    assert untouched["converted_parent_id"] == "parent-old"
    assert untouched.get("linked_family_id") is None
    foreign = await _row(other_academy.contact_id)
    assert foreign["pipeline_status"] == "lead"
    assert foreign.get("converted_parent_id") is None

    with tenant_scope(A):
        counts = await repo.count_by_source_and_status(
            created_from=NOW - timedelta(days=1), created_before=LATER + timedelta(days=1)
        )
    assert ("whatsapp_or_phone", "enrolled", 3) in counts
    assert ("whatsapp_or_phone", "lead", 1) in counts


async def test_no_email_or_no_match_writes_nothing(real_db: Any) -> None:
    repo = MongoCrmContactRepository(real_db)
    with tenant_scope(A):
        lead = (
            await CreateContact(repo, clock=lambda: NOW).execute(
                _cmd("Sample Parent", "parent@example.com")
            )
        ).contact
        use_case = MarkLeadEnrolled(repo, clock=lambda: LATER)
        assert (
            await use_case.execute(
                parent_user_id="parent-1", parent_email=None, application_id="app-1"
            )
            == 0
        )
        assert (
            await use_case.execute(
                parent_user_id="parent-1", parent_email="nobody@example.com", application_id="app-1"
            )
            == 0
        )
    doc = await real_db["crm_contacts"].find_one({"contact_id": lead.contact_id})
    assert doc is not None
    assert doc["pipeline_status"] == "lead"
    assert doc["updated_at"].replace(tzinfo=UTC) == NOW
