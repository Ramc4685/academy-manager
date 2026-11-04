"""StudentWriter — upsert by student_id."""

from __future__ import annotations

from datetime import UTC, datetime
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
        """Write the WHOLE student model.

        Only safe for callers that legitimately own the full profile — today
        that is registration approval (whose `_merged_student` fetches the
        existing student first and only overwrites a field when the incoming
        application value is non-blank, issue #755) and the checkout confirm
        path (which always mints a fresh id, so its upsert is always an
        insert). Everything else must use `ensure_exists`: this `$set`
        re-sends every unsupplied optional field as `None`, and on an existing
        student that erases date_of_birth, emergency_contact_name,
        emergency_contact_phone, medical_notes and `student_user_id` — the
        last of which silently drops the partial index entry from migration
        0150 and locks the student out of their own login (issue #610).
        """
        doc = student.model_dump(mode="python")
        await self._update_one(
            {"student_id": student.student_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )

    async def ensure_exists(self, student: Student) -> bool:
        """Insert the student if absent; leave an existing row untouched.

        `$setOnInsert` only, and deliberately naming just the identity fields
        — no profile field appears in the update document at all, so there is
        no way for this path to clobber one.

        Returns True when a row was created.

        `DuplicateKeyError` is deliberately NOT swallowed. Migration 0010 built
        `student_id_unique` on the bare `student_id` field — globally unique,
        not per-academy — while this filter is tenant-scoped, so a students doc
        owned by another academy (or a legacy pre-tenancy row) makes the filter
        miss, the upsert degrade to an insert, and Mongo reject it with E11000.
        That was the actual production 500 in #610. Returning False there would
        be worse than raising: the caller would go on to create an enrollment
        pointing at a student that does not exist in this tenant. Migration
        0160 scopes the index; until then the caller releases its seat and
        surfaces a 409.
        """
        result = await self._update_one(
            {"student_id": student.student_id},
            {
                "$setOnInsert": {
                    "student_id": student.student_id,
                    "parent_id": student.parent_id,
                    "full_name": student.full_name,
                    "status": "active",
                    "created_at": datetime.now(UTC),
                }
            },
            upsert=True,
        )
        return bool(getattr(result, "upserted_id", None))

    async def ensure_imported(
        self,
        *,
        student_id: str,
        parent_id: str,
        full_name: str,
        date_of_birth: str | None,
        parent_name: str | None,
        parent_email: str | None,
        parent_phone: str | None,
        import_batch_id: str,
        imported_by: str,
    ) -> bool:
        """Insert a student from a CSV import (roadmap L8a) if its id is absent.

        Same contract as `ensure_exists`: `$setOnInsert` only, so an
        existing row is never changed, and a repeated call with the same id
        (a retried or resumed commit) inserts nothing. The `parent_*` roster
        fields are how a family without a users document is known (the
        family index, Billing Setup's invite); they are written only when
        given. `import_batch_id` records where the row came from.

        Returns True when a row was created.
        """
        doc: dict[str, object] = {
            "student_id": student_id,
            "parent_id": parent_id,
            "full_name": full_name,
            "status": "active",
            "import_batch_id": import_batch_id,
            "imported_by": imported_by,
            "created_at": datetime.now(UTC),
        }
        optional = {
            "date_of_birth": date_of_birth,
            "parent_name": parent_name,
            "parent_email": parent_email,
            "parent_phone": parent_phone,
        }
        doc.update({key: value for key, value in optional.items() if value is not None})
        result = await self._update_one(
            {"student_id": student_id}, {"$setOnInsert": doc}, upsert=True
        )
        return bool(getattr(result, "upserted_id", None))

    async def link_student_user(self, student_id: str, user_id: str) -> StudentUserLinkOutcome:
        """Atomically link a student to their own login `user_id` (UIM12).

        Enforces "one user per student per academy" at write time, in both
        directions — the review found the original version only guarded one:

        * **student side** — the conditional filter only matches when
          `student_user_id` is absent or empty, so a second invite against
          an already-linked student is a no-op (`modified_count == 0`)
          rather than silently overwriting the existing link.
        * **user side** — the unique partial index
          `student_user_id_per_academy_uq` (migration 0150, re-shaped by
          0188) makes the
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
