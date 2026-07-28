"""Unique index for the student<->user login link (UIM12).

``Student.student_user_id`` is the authoritative link between a roster
student and the identity user allowed to sign in as them. Two students in
one academy sharing a ``student_user_id`` is the critical failure mode for
this feature: ``get_by_student_user_id`` would resolve to whichever doc
Mongo returned first, and the signed-in student would see the *other*
student's name, schedule, and skill passport.

The index is the last line of defence behind the application-level checks
in the provisioning path (``composition/admin.py``) and the conditional
``$set`` in ``MongoStudentWriter.link_student_user``.

``partialFilterExpression`` (not ``sparse``) restricts uniqueness to docs
where the field is an actual string: the overwhelming majority of student
docs have no login and would otherwise all collide on ``null``.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0150"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    students = db["students"]
    # Normalize any explicit nulls to "absent" first so the partial filter
    # cannot be tripped by a doc that stored null rather than omitting it.
    await students.update_many({"student_user_id": None}, {"$unset": {"student_user_id": ""}})
    await students.create_index(
        [("academy_id", 1), ("student_user_id", 1)],
        unique=True,
        partialFilterExpression={"student_user_id": {"$type": "string"}},
        name="student_user_id_unique_per_academy",
    )
