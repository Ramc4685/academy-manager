"""The audience resolver's family-contact expansion (People CRM Phase 4b).

A family contact with "Gets notices" on joins the family's notice audience;
one with it off never does; another academy's contact never does; an email
already in the list (the primary parent's) is not sent twice. The session
audience always expands; the selected audience expands only when the send
opts in, so a staff alert to a coach who is also a parent is never copied to
their family contact.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.communications.domain.models import (
    SelectedRecipientsAudience,
    SessionAudience,
)
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    FAMILY_CONTACT_RECIPIENT_PREFIX,
    MongoAudienceResolver,
)
from backend.v2.shared.tenancy.context import tenant_scope
from mongomock_motor import AsyncMongoMockClient

A = "acad-1"
B = "acad-2"


def _contact(
    contact_id: str,
    email: str | None,
    *,
    gets_notices: bool,
    parent_id: str = "parent-1",
    academy_id: str = A,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "academy_id": academy_id,
        "contact_id": contact_id,
        "parent_id": parent_id,
        "name": f"Contact {contact_id}",
        "relationship": "parent",
        "gets_notices": gets_notices,
        "gets_invoices": False,
        "created_at": contact_id,
    }
    if email:
        doc["email"] = email
    return doc


async def _seed(db: Any) -> None:
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": A,
                "enrollment_id": "enr-1",
                "session_id": "sess-1",
                "student_id": "stu-1",
                "status": "active",
            },
            {
                "academy_id": A,
                "enrollment_id": "enr-2",
                "session_id": "sess-1",
                "student_id": "stu-2",
                "status": "active",
            },
        ]
    )
    await db["students"].insert_many(
        [
            # Parent one is linked by the Firebase alias, parent two by user_id.
            {"academy_id": A, "student_id": "stu-1", "parent_id": "fb-uid-1"},
            {"academy_id": A, "student_id": "stu-2", "parent_id": "parent-2"},
        ]
    )
    await db["users"].insert_many(
        [
            {
                "academy_id": A,
                "user_id": "parent-1",
                "auth_uid": "fb-uid-1",
                "email": "Parent.One@example.test",
                "display_name": "Parent One",
            },
            {
                "academy_id": A,
                "user_id": "parent-2",
                "email": "parent.two@example.test",
                "display_name": "Parent Two",
            },
        ]
    )
    await db["family_contacts"].insert_many(
        [
            _contact("c-in", "second.one@example.test", gets_notices=True),
            _contact("c-off", "off.one@example.test", gets_notices=False),
            # Same address as the primary parent: never a second copy.
            _contact("c-same", "parent.one@example.test", gets_notices=True),
            _contact("c-nomail", None, gets_notices=True),
            # Another academy's row for the same family id: never read.
            _contact("c-other", "leak@example.test", gets_notices=True, academy_id=B),
            # Parent two's contact, opted in; also on parent one (dedupe).
            _contact("c-two", "shared@example.test", gets_notices=True, parent_id="parent-2"),
            _contact("c-shared", "SHARED@example.test", gets_notices=True),
        ]
    )


def _pairs(recipients: list[Any]) -> list[tuple[str, str | None]]:
    return [(r.user_id, r.email) for r in recipients]


async def test_session_audience_adds_only_opted_in_contacts_once() -> None:
    db = AsyncMongoMockClient()["audience-family-contacts-session"]
    await _seed(db)
    with tenant_scope(A):
        recipients = await MongoAudienceResolver(db).resolve_session_audience(
            SessionAudience(session_id="sess-1")
        )
    pairs = _pairs(recipients)
    users = [p for p in pairs if not p[0].startswith(FAMILY_CONTACT_RECIPIENT_PREFIX)]
    contacts = [p for p in pairs if p[0].startswith(FAMILY_CONTACT_RECIPIENT_PREFIX)]
    assert sorted(users) == [
        ("parent-1", "Parent.One@example.test"),
        ("parent-2", "parent.two@example.test"),
    ]
    # Rows are read in (parent_id, created_at) order, so the shared address
    # is kept once, from parent one's contact.
    assert contacts == [
        ("family_contact:c-in", "second.one@example.test"),
        ("family_contact:c-shared", "shared@example.test"),
    ]
    emails = [e.lower() for _, e in pairs if e]
    assert len(emails) == len(set(emails))
    assert "leak@example.test" not in emails
    assert "off.one@example.test" not in emails
    # Users come first; contacts are appended after them.
    assert pairs.index(contacts[0]) > max(pairs.index(u) for u in users)


async def test_contacts_of_another_academy_are_never_added() -> None:
    db = AsyncMongoMockClient()["audience-family-contacts-tenant"]
    await _seed(db)
    with tenant_scope(B):
        recipients = await MongoAudienceResolver(db).resolve_session_audience(
            SessionAudience(session_id="sess-1")
        )
    assert recipients == []


async def test_selected_audience_expands_only_when_the_send_opts_in() -> None:
    db = AsyncMongoMockClient()["audience-family-contacts-selected"]
    await _seed(db)
    resolver = MongoAudienceResolver(db)
    with tenant_scope(A):
        plain = await resolver.resolve_selected_audience(
            SelectedRecipientsAudience(user_ids=("parent-1",))
        )
        family = await resolver.resolve_selected_audience(
            SelectedRecipientsAudience(user_ids=("parent-1",), include_family_contacts=True)
        )
    assert _pairs(plain) == [("parent-1", "Parent.One@example.test")]
    # The selected parent stays first, so ``resolved[0]`` callers are unchanged.
    assert _pairs(family)[0] == ("parent-1", "Parent.One@example.test")
    assert sorted(_pairs(family)[1:]) == [
        ("family_contact:c-in", "second.one@example.test"),
        ("family_contact:c-shared", "shared@example.test"),
    ]


async def test_no_contacts_means_the_audience_is_unchanged() -> None:
    db = AsyncMongoMockClient()["audience-family-contacts-none"]
    await _seed(db)
    await db["family_contacts"].delete_many({})
    with tenant_scope(A):
        recipients = await MongoAudienceResolver(db).resolve_session_audience(
            SessionAudience(session_id="sess-1")
        )
    assert sorted(_pairs(recipients)) == [
        ("parent-1", "Parent.One@example.test"),
        ("parent-2", "parent.two@example.test"),
    ]
