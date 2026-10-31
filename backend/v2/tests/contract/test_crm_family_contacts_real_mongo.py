"""Family contacts on a real ``mongod`` (migration 0196 applied), end to end.

``real_db`` replays every migration, so the unique ``(academy_id, contact_id)``
index and the PARTIAL unique ``(academy_id, parent_id, email)`` index
(``{email: {$gt: ""}}``) are the production ones. Checks:

* academy B can neither read, change nor delete academy A's contacts, even by
  exact id; a duplicate contact id is refused by the index;
* one email per family (case-insensitive, stored lowercased), the same email
  is fine on another family, and contacts WITHOUT an email never collide;
* one details document per family (upsert), tenant-scoped;
* acceptance: a notice to a class reaches the opted-in second contact and
  nobody else (not the opted-out contact, not another academy's contact, not a
  second copy of the primary parent's address);
* the resolver's contact lookup and the family list are served by 0196 indexes.

Skipped without a ``mongod``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.communications.domain.models import SessionAudience
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    MongoAudienceResolver,
)
from backend.v2.contexts.crm.domain.errors import (
    DuplicateCrmRecordId,
    DuplicateFamilyContactEmail,
)
from backend.v2.contexts.crm.domain.family_contacts import FamilyContact
from backend.v2.contexts.crm.infrastructure.mongo_family_contacts_repo import (
    MongoFamilyContactRepository,
    MongoFamilyDetailsRepository,
)
from backend.v2.shared.tenancy import tenant_scope

A = "acad-contacts-a"
B = "acad-contacts-b"
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


def _contact(
    contact_id: str,
    *,
    parent_id: str = "p-1",
    email: str | None = None,
    phone: str | None = None,
    gets_notices: bool = False,
    at: datetime = NOW,
) -> FamilyContact:
    return FamilyContact(
        contact_id=contact_id,
        academy_id=B,  # forged: the repository must stamp the tenant instead
        parent_id=parent_id,
        name=f"Contact {contact_id}",
        email=email,
        phone=phone,
        phone_digits="".join(c for c in phone if c.isdigit()) if phone else None,
        gets_notices=gets_notices,
        created_by="u-1",
        created_at=at,
        updated_at=at,
    )


async def test_contacts_are_tenant_scoped_and_ids_unique(real_db: Any) -> None:
    with tenant_scope(A):
        repo = MongoFamilyContactRepository(real_db)
        stored = await repo.add(_contact("c-1", email="one@example.test"))
        with pytest.raises(DuplicateCrmRecordId):
            await repo.add(_contact("c-1", parent_id="p-2", email="other@example.test"))
    assert stored.academy_id == A
    row = await real_db["family_contacts"].find_one({"contact_id": "c-1"})
    assert row["academy_id"] == A
    assert "phone" not in row and "phone_digits" not in row  # empty = absent

    with tenant_scope(B):
        other = MongoFamilyContactRepository(real_db)
        assert await other.get("p-1", "c-1") is None
        assert await other.list_for_family("p-1") == []
        assert await other.update("p-1", "c-1", changes={"gets_notices": True}) is None
        assert await other.delete("p-1", "c-1") is False
        await other.add(_contact("c-1", email="one@example.test"))  # per-academy ids

    with tenant_scope(A):
        repo = MongoFamilyContactRepository(real_db)
        still = await repo.get("p-1", "c-1")
        assert still is not None and still.gets_notices is False
        assert await repo.get("p-other", "c-1") is None  # parent_id is always filtered


async def test_partial_unique_email_index_per_family(real_db: Any) -> None:
    with tenant_scope(A):
        repo = MongoFamilyContactRepository(real_db)
        await repo.add(_contact("c-1", email="dup@example.test"))
        with pytest.raises(DuplicateFamilyContactEmail):
            await repo.add(_contact("c-2", email="dup@example.test"))
        # Another family may use the same address.
        await repo.add(_contact("c-3", parent_id="p-2", email="dup@example.test"))
        # Contacts with no email store no field and never collide.
        await repo.add(_contact("c-4", phone="555-010-0001"))
        await repo.add(_contact("c-5", phone="555-010-0002", at=NOW + timedelta(seconds=1)))
        assert await repo.count_for_family("p-1") == 3

        # Setting an email that the family already has is refused too.
        with pytest.raises(DuplicateFamilyContactEmail):
            await repo.update("p-1", "c-4", changes={"email": "dup@example.test"})
        # Clearing an email unsets the field; two email-less rows still coexist.
        cleared = await repo.update("p-1", "c-1", changes={"email": None})
        assert cleared is not None and cleared.email is None
        doc = await real_db["family_contacts"].find_one({"contact_id": "c-1"})
        assert "email" not in doc
        # Now the address is free in this family again.
        moved = await repo.update("p-1", "c-4", changes={"email": "dup@example.test"})
        assert moved is not None and moved.email == "dup@example.test"
        listed = await repo.list_for_family("p-1")
        assert [c.contact_id for c in listed] == ["c-1", "c-4", "c-5"]
        assert await repo.delete("p-1", "c-5") is True
        assert await repo.delete("p-1", "c-5") is False

    with tenant_scope(B):
        # The same family id and email in another academy is a different row.
        await MongoFamilyContactRepository(real_db).add(_contact("c-9", email="dup@example.test"))


async def test_details_are_one_document_per_family_and_tenant_scoped(real_db: Any) -> None:
    with tenant_scope(A):
        repo = MongoFamilyDetailsRepository(real_db)
        assert await repo.get("p-1") is None
        first = await repo.upsert(
            "p-1",
            changes={"address": "1 Test Street", "tags": ["VIP"]},
            updated_by="u-1",
            updated_at=NOW,
        )
        assert first.academy_id == A and first.address == "1 Test Street"
        second = await repo.upsert(
            "p-1", changes={"preferred_channel": "sms"}, updated_by="u-2", updated_at=NOW
        )
        assert second.address == "1 Test Street" and second.preferred_channel == "sms"
        assert second.tags == ("VIP",) and second.updated_by == "u-2"
    assert await real_db["family_details"].count_documents({"parent_id": "p-1"}) == 1
    with tenant_scope(B):
        assert await MongoFamilyDetailsRepository(real_db).get("p-1") is None


async def test_a_class_notice_reaches_the_opted_in_contact_and_nobody_else(
    real_db: Any,
) -> None:
    await real_db["enrollments"].insert_one(
        {
            "academy_id": A,
            "enrollment_id": "enr-1",
            "session_id": "sess-1",
            "student_id": "stu-1",
            "status": "active",
        }
    )
    await real_db["students"].insert_one(
        {"academy_id": A, "student_id": "stu-1", "parent_id": "fb-uid-1"}
    )
    await real_db["users"].insert_one(
        {
            "academy_id": A,
            "user_id": "p-1",
            "auth_uid": "fb-uid-1",
            "email": "primary@example.test",
            "display_name": "Primary Testparent",
        }
    )
    with tenant_scope(A):
        repo = MongoFamilyContactRepository(real_db)
        await repo.add(_contact("c-in", email="second@example.test", gets_notices=True))
        await repo.add(_contact("c-off", email="quiet@example.test"))
        await repo.add(_contact("c-same", email="PRIMARY@example.test".lower(), gets_notices=True))
    with tenant_scope(B):
        await MongoFamilyContactRepository(real_db).add(
            _contact("c-leak", email="leak@example.test", gets_notices=True)
        )

    with tenant_scope(A):
        recipients = await MongoAudienceResolver(real_db).resolve_session_audience(
            SessionAudience(session_id="sess-1")
        )
    assert [(r.user_id, r.email) for r in recipients] == [
        ("p-1", "primary@example.test"),
        ("family_contact:c-in", "second@example.test"),
    ]


def _index_names(plan: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    if plan.get("indexName"):
        found.add(plan["indexName"])
    for key in ("inputStage", "queryPlan"):
        if isinstance(plan.get(key), dict):
            found |= _index_names(plan[key])
    for child in plan.get("inputStages", []) or []:
        found |= _index_names(child)
    return found


@pytest.mark.parametrize(
    ("filter_", "sort", "index"),
    [
        (
            {"academy_id": A, "parent_id": {"$in": ["p-1", "fb-uid-1"]}, "gets_notices": True},
            {"parent_id": 1, "created_at": 1},
            "family_contacts_academy_parent_created",
        ),
        (
            {"academy_id": A, "parent_id": "p-1"},
            {"created_at": 1},
            "family_contacts_academy_parent_created",
        ),
    ],
)
async def test_contact_lookups_use_their_indexes(
    real_db: Any, filter_: dict[str, Any], sort: dict[str, int], index: str
) -> None:
    explained = await real_db.command(
        "explain",
        {"find": "family_contacts", "filter": filter_, "sort": sort},
        verbosity="queryPlanner",
    )
    assert index in _index_names(explained["queryPlanner"]["winningPlan"])
