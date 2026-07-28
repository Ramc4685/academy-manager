"""StudentWriter — upsert by student_id."""

from __future__ import annotations

from typing import Literal

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.enrollment.domain.models import Student
from backend.v2.shared.tenancy import TenantScopedRepository

# Outcome of `link_student_user`. The two failure modes are deliberately
# distinct: they are different bugs with different admin-facing messages
# (this student already has a login vs. this email/user is already another
# student's login), and conflating them was the P1 review finding.
StudentUserLinkOutcome = Literal["linked", "student_already_linked", "user_already_linked"]


class MongoStudentWriter(TenantScopedRepository):
    collection_name = "students"

    async def upsert(self, student: Student) -> None:
        doc = student.model_dump(mode="python")
        await self._update_one(
            {"student_id": student.student_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )

    async def link_student_user(self, student_id: str, user_id: str) -> StudentUserLinkOutcome:
        """Atomically link a student to their own login `user_id` (UIM12).

        Enforces "one user per student per academy" at write time, in both
        directions — the review found the original version only guarded one:

        * **student side** — the conditional filter only matches when
          `student_user_id` is absent or empty, so a second invite against
          an already-linked student is a no-op (`modified_count == 0`)
          rather than silently overwriting the existing link.
        * **user side** — the unique partial index
          `student_user_id_unique_per_academy` (migration 0150) makes the
          write fail with `DuplicateKeyError` if another student in this
          academy already holds this `user_id`. Without this, two siblings
          invited with the same family email would both link to one user
          and each would see the other's schedule and progress.

        The index is what makes this race-safe: two concurrent invites
        cannot both win, whatever the application-level pre-checks saw.
        """
        filter_ = self._scoped(
            {
                "student_id": student_id,
                "$or": [
                    {"student_user_id": {"$exists": False}},
                    {"student_user_id": None},
                    {"student_user_id": ""},
                ],
            }
        )
        try:
            result = await self.collection.update_one(
                filter_, {"$set": {"student_user_id": user_id}}
            )
        except DuplicateKeyError:
            return "user_already_linked"
        return "linked" if result.modified_count == 1 else "student_already_linked"
