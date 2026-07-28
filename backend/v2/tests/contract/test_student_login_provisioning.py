"""End-to-end provisioning-path tests for the student login (UIM12).

Exercises the real `_StudentLoginProvisionerAdapter` over mongomock with a
faked Firebase adapter, because the security-critical invariants live in
the *interaction* between the identity repo (Firebase user + membership),
the enrollment writer (the link), and the enrollment repo (the pre-check)
— not in any one of them alone.
"""

from __future__ import annotations

import pytest

from backend.v2.composition.admin import _StudentLoginProvisionerAdapter
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_writer import (
    MongoStudentWriter,
)
from backend.v2.contexts.identity.domain.errors import (
    StudentAlreadyLinked,
    StudentNotFound,
    UserAlreadyLinkedToStudent,
    UserOutsideAcademy,
)
from backend.v2.contexts.identity.infrastructure import mongo_user_repo as user_repo_module
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository


class _FakeFirebase:
    """Mirrors the real adapter's `(uid, created)` contract.

    Keyed by email so that inviting two students with the SAME email
    resolves to one uid — which is exactly the sibling collision the
    application-level guards have to catch.
    """

    def __init__(self) -> None:
        self.by_email: dict[str, str] = {}

    async def ensure_user(self, **kwargs: object) -> tuple[str, bool]:
        email = str(kwargs["email"])
        if email in self.by_email:
            return self.by_email[email], False
        uid = str(kwargs["uid"])
        self.by_email[email] = uid
        return uid, True


@pytest.fixture
def firebase(monkeypatch) -> _FakeFirebase:
    fake = _FakeFirebase()
    monkeypatch.setattr(user_repo_module, "get_firebase_admin_adapter", lambda: fake)
    return fake


def _adapter(db, academy_id: str) -> _StudentLoginProvisionerAdapter:
    return _StudentLoginProvisionerAdapter(
        MongoUserRepository(db, default_academy_id=academy_id),
        MongoStudentRepository(db),
        MongoStudentWriter(db),
    )


async def _seed_siblings(db, academy_id: str) -> None:
    await db["students"].insert_many(
        [
            {
                "academy_id": academy_id,
                "student_id": "st-a",
                "full_name": "Sibling A",
                "parent_id": "parent-1",
            },
            {
                "academy_id": academy_id,
                "student_id": "st-b",
                "full_name": "Sibling B",
                "parent_id": "parent-1",
            },
        ]
    )


async def test_two_students_cannot_share_one_login_via_the_family_email(db, acad, firebase) -> None:
    """The P1 leak: siblings invited with one shared family email.

    Without the user-side guard both students end up with the same
    `student_user_id`, and `/student/*` resolves to whichever doc Mongo
    returns first — each sibling seeing the other's schedule and passport.
    """
    await _seed_siblings(db, acad)
    adapter = _adapter(db, acad)

    first_uid = await adapter.ensure_student_login(
        student_id="st-a",
        email="family@example.com",
        display_name="Sibling A",
        academy_id=acad,
        actor_id="admin-1",
    )

    with pytest.raises(UserAlreadyLinkedToStudent):
        await adapter.ensure_student_login(
            student_id="st-b",
            email="family@example.com",
            display_name="Sibling B",
            academy_id=acad,
            actor_id="admin-1",
        )

    # Sibling B is left completely unlinked — no half-provisioned state on
    # the student doc, and A keeps the login.
    a = await db["students"].find_one({"student_id": "st-a"})
    b = await db["students"].find_one({"student_id": "st-b"})
    assert a["student_user_id"] == first_uid
    assert b.get("student_user_id") is None

    # And the invariant that actually matters: exactly one student in this
    # academy resolves to that user.
    linked = await db["students"].count_documents(
        {"academy_id": acad, "student_user_id": first_uid}
    )
    assert linked == 1


async def test_reinviting_the_same_student_is_rejected(db, acad, firebase) -> None:
    await _seed_siblings(db, acad)
    adapter = _adapter(db, acad)
    await adapter.ensure_student_login(
        student_id="st-a",
        email="a@example.com",
        display_name="Sibling A",
        academy_id=acad,
        actor_id="admin-1",
    )

    with pytest.raises(StudentAlreadyLinked):
        await adapter.ensure_student_login(
            student_id="st-a",
            email="a-new@example.com",
            display_name="Sibling A",
            academy_id=acad,
            actor_id="admin-1",
        )


async def test_unknown_student_is_rejected_before_any_side_effect(db, acad, firebase) -> None:
    adapter = _adapter(db, acad)

    with pytest.raises(StudentNotFound):
        await adapter.ensure_student_login(
            student_id="nope",
            email="a@example.com",
            display_name="Nobody",
            academy_id=acad,
            actor_id="admin-1",
        )

    assert firebase.by_email == {}
    assert await db["academy_memberships"].count_documents({}) == 0


async def test_email_belonging_to_another_academys_user_is_refused(db, acad, firebase) -> None:
    """The P2 leak: attaching a stranger's existing account.

    The email resolves to a real person in another academy who already has
    a working password. Linking them would hand them an active `student`
    membership here plus a straight-in login to this student's data.
    """
    await _seed_siblings(db, acad)
    await db["users"].insert_one(
        {
            "user_id": "outsider-uid",
            "firebase_uid": "outsider-uid",
            "email": "outsider@example.com",
            "normalized_email": "outsider@example.com",
            "display_name": "Someone Else",
            "academy_id": "some-other-academy",
            "status": "active",
            "is_active": True,
        }
    )
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "m-out",
            "academy_id": "some-other-academy",
            "user_id": "outsider-uid",
            "roles": ["parent"],
            "status": "active",
        }
    )
    adapter = _adapter(db, acad)

    with pytest.raises(UserOutsideAcademy):
        await adapter.ensure_student_login(
            student_id="st-a",
            email="outsider@example.com",
            display_name="Sibling A",
            academy_id=acad,
            actor_id="admin-1",
        )

    # No membership granted in this academy, and no link stamped.
    assert await db["academy_memberships"].count_documents({"academy_id": acad}) == 0
    student = await db["students"].find_one({"student_id": "st-a"})
    assert student.get("student_user_id") is None


async def test_email_belonging_to_an_existing_member_is_allowed(db, acad, firebase) -> None:
    """The legitimate case P2 must not break: an adult learner who already
    has a parent account in THIS academy gains a student login too."""
    await _seed_siblings(db, acad)
    await db["users"].insert_one(
        {
            "user_id": "member-uid",
            "firebase_uid": "member-uid",
            "email": "member@example.com",
            "normalized_email": "member@example.com",
            "display_name": "Adult Learner",
            "academy_id": acad,
            "status": "active",
            "is_active": True,
        }
    )
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "m-in",
            "academy_id": acad,
            "user_id": "member-uid",
            "roles": ["parent"],
            "status": "active",
        }
    )
    adapter = _adapter(db, acad)

    uid = await adapter.ensure_student_login(
        student_id="st-a",
        email="member@example.com",
        display_name="Adult Learner",
        academy_id=acad,
        actor_id="admin-1",
    )

    assert uid == "member-uid"
    membership = await db["academy_memberships"].find_one(
        {"academy_id": acad, "user_id": "member-uid"}
    )
    # Keeps the parent role, gains student.
    assert set(membership["roles"]) == {"parent", "student"}


async def test_invite_reason_is_recorded_on_the_audit_row(db, acad, firebase) -> None:
    await _seed_siblings(db, acad)
    adapter = _adapter(db, acad)

    await adapter.ensure_student_login(
        student_id="st-a",
        email="a@example.com",
        display_name="Sibling A",
        academy_id=acad,
        actor_id="admin-1",
        reason="parent asked for teen portal access",
    )

    audit = await db["audit_logs"].find_one({"action": "student.login_provisioned"})
    assert audit is not None
    assert audit["actor_id"] == "admin-1"
    assert "parent asked for teen portal access" in audit["reason"]
