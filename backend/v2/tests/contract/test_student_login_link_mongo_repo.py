"""Contract tests for the UIM12 student<->user link on the Mongo student repo/writer.

`link_student_user`'s conditional `$set` is the actual "one user per
student per academy" enforcement — this is the test that matters for the
invite-idempotency acceptance criterion.
"""

from __future__ import annotations

from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_writer import (
    MongoStudentWriter,
)


async def test_link_student_user_sets_link_when_unset(db, acad) -> None:
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "st-1",
            "full_name": "Alex Chen",
            "parent_id": "parent-1",
        }
    )
    writer = MongoStudentWriter(db)

    assert await writer.link_student_user("st-1", "user-1") == "linked"

    doc = await db["students"].find_one({"student_id": "st-1"})
    assert doc["student_user_id"] == "user-1"


async def test_link_student_user_rejects_second_link_idempotently(db, acad) -> None:
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "st-1",
            "full_name": "Alex Chen",
            "parent_id": "parent-1",
            "student_user_id": "user-1",
        }
    )
    writer = MongoStudentWriter(db)

    assert await writer.link_student_user("st-1", "user-2") == "student_already_linked"

    doc = await db["students"].find_one({"student_id": "st-1"})
    # The original link is untouched — a second invite never silently
    # re-links the student to a different user.
    assert doc["student_user_id"] == "user-1"


async def test_count_students_linked_to_user_sees_the_sibling(db, acad) -> None:
    """The pre-check that stops two siblings sharing one login."""
    await db["students"].insert_many(
        [
            {
                "academy_id": acad,
                "student_id": "st-a",
                "full_name": "Sibling A",
                "parent_id": "parent-1",
                "student_user_id": "user-family",
            },
            {
                "academy_id": acad,
                "student_id": "st-b",
                "full_name": "Sibling B",
                "parent_id": "parent-1",
            },
        ]
    )
    repo = MongoStudentRepository(db)

    # Inviting sibling B with the family email that already resolves to
    # `user-family` must see A's existing link.
    assert await repo.count_students_linked_to_user("user-family", excluding_student_id="st-b") == 1
    # A re-invite of A itself excludes A's own row, so it reads as "free"
    # (the student-side guard is what rejects that case).
    assert await repo.count_students_linked_to_user("user-family", excluding_student_id="st-a") == 0
    assert await repo.count_students_linked_to_user("nobody") == 0


async def test_get_by_student_user_id_resolves_within_tenant(db, acad) -> None:
    from backend.v2.shared.tenancy.context import tenant_scope

    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "st-1",
            "full_name": "Alex Chen",
            "parent_id": "parent-1",
            "student_user_id": "user-1",
        }
    )
    repo = MongoStudentRepository(db)

    # Already inside the `acad` fixture's tenant scope.
    found = await repo.get_by_student_user_id("user-1")
    assert found is not None
    assert found.student_id == "st-1"
    assert found.student_user_id == "user-1"

    # A student login can only ever resolve within the academy it was
    # provisioned in — a different tenant context must not see it.
    with tenant_scope("some-other-academy"):
        not_found = await repo.get_by_student_user_id("user-1")
    assert not_found is None


async def test_get_by_student_user_id_fails_closed_when_two_docs_match(db, acad) -> None:
    """A duplicate link must degrade to "no access", never to "wrong student".

    Migration 0150's unique index makes this state unreachable going
    forward, but data predating the index (or a direct DB edit) must not
    hand one sibling the other's schedule and progress.
    """
    await db["students"].insert_many(
        [
            {
                "academy_id": acad,
                "student_id": "st-a",
                "full_name": "Sibling A",
                "parent_id": "parent-1",
                "student_user_id": "user-shared",
            },
            {
                "academy_id": acad,
                "student_id": "st-b",
                "full_name": "Sibling B",
                "parent_id": "parent-1",
                "student_user_id": "user-shared",
            },
        ]
    )
    repo = MongoStudentRepository(db)

    assert await repo.get_by_student_user_id("user-shared") is None


async def test_get_by_student_user_id_returns_none_when_unlinked(db, acad) -> None:
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "st-1",
            "full_name": "Alex Chen",
            "parent_id": "parent-1",
        }
    )
    repo = MongoStudentRepository(db)

    found = await repo.get_by_student_user_id("user-1")

    assert found is None
