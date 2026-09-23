"""Billing Setup parent roster: the composition bridge billing needs.

Moved out of ``composition/admin.py`` (at its line budget) when the roster
learned to group by canonical parent (Lane A verify #2). Billing may not
import enrollment or identity, so this module hands ``ListBillingSetup`` a
roster built from enrollment's paginated admin student directory, with the
stored parent references resolved through identity's
``MongoUserRepository.resolve_parent_aliases`` (one ``$in`` equality lookup
per alias field, never an ``$or`` across fields: #878/#894).

Why grouping matters: a family whose students store different references to
the same parent (``user_id`` on one child, ``firebase_uid`` on another) used
to become two Billing Setup rows, so "Invite all not invited (N)" on
``/admin/families`` counted that family twice and invited it twice. Each
family is now ONE row keyed by a stored reference the invite endpoint can
find (the canonical id when a student stores it, else the first stored
alias), with the other stored references in ``aliases`` so the use case can
read cards, balances and autopay filed under any of them.

``users`` is global; it is only asked about ids read from this academy's own
student rows (the directory is tenant-scoped), and every student query here
carries ``academy_id``.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.application.ports import BillingSetupStudent, ParentRosterEntry
from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    ListAdminStudents,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository


class BillingSetupRosterAdapter:
    """Bridges enrollment's admin student directory into the parent roster
    the Billing Setup page needs, one entry per canonical parent."""

    def __init__(self, list_students: ListAdminStudents, *, db: Any, users: MongoUserRepository):
        self._list_students = list_students
        self._db = db
        self._users = users

    async def _all_students(self) -> list[Any]:
        students: list[Any] = []
        cursor: str | None = None
        for _ in range(1000):  # safety cap against a runaway pagination loop
            page = await self._list_students.execute(limit=200, cursor=cursor)
            students.extend(page.students)
            if not page.next_cursor:
                break
            cursor = page.next_cursor
        return students

    async def list_parents(self, *, academy_id: str) -> list[ParentRosterEntry]:
        students = await self._all_students()
        raw_ids = list(dict.fromkeys(s.parent_id for s in students if s.parent_id))
        if not raw_ids:
            return []
        # One batched resolution for the whole roster (no N+1).
        resolved = await self._users.resolve_parent_aliases(raw_ids)
        groups: dict[str, list[str]] = {}
        for raw in raw_ids:
            found = resolved.get(raw)
            groups.setdefault(found.canonical_id if found is not None else raw, []).append(raw)
        first_student: dict[str, Any] = {}
        for student in students:
            if student.parent_id:
                first_student.setdefault(student.parent_id, student)
        entries: list[ParentRosterEntry] = []
        for canonical, raws in groups.items():
            # The row id must be one a student stores: the invite and detail
            # endpoints find the parent through the student rows.
            key = canonical if canonical in raws else raws[0]
            aliases = tuple(raw for raw in raws if raw != key)
            ordered = [key, *aliases]
            name = next(
                (first_student[r].parent_name for r in ordered if first_student[r].parent_name),
                None,
            )
            email = next(
                (first_student[r].parent_email for r in ordered if first_student[r].parent_email),
                None,
            )
            entries.append(
                ParentRosterEntry(
                    parent_id=key, parent_name=name or key, parent_email=email, aliases=aliases
                )
            )
        return entries

    async def students_for_parents(
        self, parent_ids: list[str], *, academy_id: str
    ) -> dict[str, list[BillingSetupStudent]]:
        wanted = set(parent_ids)
        result: dict[str, list[BillingSetupStudent]] = {}
        for student in await self._all_students():
            if student.parent_id in wanted:
                result.setdefault(student.parent_id, []).append(
                    BillingSetupStudent(student_id=student.student_id, full_name=student.full_name)
                )
        return result

    async def _direct_student_docs(self, parent_id: str) -> list[dict[str, Any]]:
        from backend.v2.shared.tenancy import current_academy_id

        cursor = self._db["students"].find(
            {
                "academy_id": current_academy_id(),
                "$or": [
                    {"parent_id": parent_id},
                    {"parent_user_id": parent_id},
                ],
            }
        )
        return [doc async for doc in cursor]

    async def get_parent(self, parent_id: str, *, academy_id: str) -> ParentRosterEntry | None:
        docs = await self._direct_student_docs(parent_id)
        if not docs:
            return None
        user = await self._users.get_billing_setup_parent(parent_id, academy_id=academy_id)
        if user is None:
            # The scoped student row authorizes use of the global roster
            # contact before a membership/login has been provisioned.
            user = await self._users.get_by_id(parent_id)
        first = docs[0]
        fallback_name = str(first.get("parent_name") or first.get("guardian_name") or parent_id)
        fallback_email = first.get("parent_email") or first.get("guardian_email")
        return ParentRosterEntry(
            parent_id=parent_id,
            parent_name=user.display_name if user else fallback_name,
            parent_email=str(user.email)
            if user
            else (str(fallback_email) if fallback_email else None),
        )

    async def students_for_parent(
        self, parent_id: str, *, academy_id: str
    ) -> list[BillingSetupStudent]:
        rows: list[BillingSetupStudent] = []
        for doc in await self._direct_student_docs(parent_id):
            full_name = str(
                doc.get("full_name")
                or f"{doc.get('first_name', '')} {doc.get('last_name', '')}".strip()
                or doc.get("name")
                or "Student"
            )
            rows.append(
                BillingSetupStudent(
                    student_id=str(doc.get("student_id") or doc["_id"]),
                    full_name=full_name,
                )
            )
        return rows
