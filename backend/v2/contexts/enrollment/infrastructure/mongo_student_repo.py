"""Mongo StudentQuery."""

from __future__ import annotations

from bson import ObjectId as BsonObjectId

from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    AdminStudentSummary,
)
from backend.v2.contexts.enrollment.domain.models import Student
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoStudentRepository(TenantScopedRepository):
    collection_name = "students"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Student:
        return Student(
            student_id=str(doc["student_id"]),
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc["parent_id"]),
            full_name=str(doc["full_name"]),
        )

    async def by_ids(self, student_ids: list[str]) -> list[Student]:
        if not student_ids:
            return []
        cursor = self._find_many({"student_id": {"$in": student_ids}})
        return [self._to_domain(doc) async for doc in cursor]

    @staticmethod
    def _summary_id(doc: dict[str, object]) -> str:
        return str(doc.get("student_id") or doc.get("_id"))

    @classmethod
    def _to_admin_summary(
        cls,
        doc: dict[str, object],
        *,
        active_session_count: int,
        last_seen_at: object | None,
        parent_name: str | None = None,
        parent_email: str | None = None,
    ) -> AdminStudentSummary:
        first = str(doc.get("first_name") or "").strip()
        last = str(doc.get("last_name") or "").strip()
        full_name = str(doc.get("full_name") or f"{first} {last}".strip() or "Unnamed student")
        return AdminStudentSummary(
            student_id=cls._summary_id(doc),
            full_name=full_name,
            parent_id=str(doc.get("parent_id") or doc.get("parent_user_id") or ""),
            parent_name=parent_name,
            parent_email=parent_email,
            status=str(doc.get("status") or "active"),
            active_session_count=active_session_count,
            last_seen_at=last_seen_at,  # type: ignore[arg-type]
        )

    async def list_admin_students(self) -> list[AdminStudentSummary]:
        academy_id = current_academy_id()
        docs = [doc async for doc in self._find_many(
            {}, sort=[("full_name", 1), ("last_name", 1), ("first_name", 1)]
        )]

        # Collect all parent_ids to batch-lookup users
        parent_ids = list({
            str(doc.get("parent_id") or doc.get("parent_user_id") or "")
            for doc in docs
            if doc.get("parent_id") or doc.get("parent_user_id")
        })
        users_by_id: dict[str, dict[str, object]] = {}
        if parent_ids:
            oid_ids = [BsonObjectId(p) for p in parent_ids if BsonObjectId.is_valid(p)]
            or_filter: list[dict[str, object]] = [
                {"user_id": {"$in": parent_ids}},
                {"firebase_uid": {"$in": parent_ids}},
            ]
            if oid_ids:
                or_filter.append({"_id": {"$in": oid_ids}})
            user_cursor = self._db["users"].find({"academy_id": academy_id, "$or": or_filter})
            async for user in user_cursor:
                display = str(
                    user.get("display_name")
                    or f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                    or ""
                ) or None
                email = user.get("email")
                for key in (
                    str(user.get("user_id") or ""),
                    str(user.get("firebase_uid") or ""),
                    str(user["_id"]),
                ):
                    if key:
                        users_by_id[key] = {"name": display, "email": email}

        students: list[AdminStudentSummary] = []
        for doc in docs:
            student_id = self._summary_id(doc)
            parent_raw = str(doc.get("parent_id") or doc.get("parent_user_id") or "")
            user_info = users_by_id.get(parent_raw) or {}
            active_session_count = await self._db["enrollments"].count_documents(
                {
                    "academy_id": academy_id,
                    "student_id": student_id,
                    "status": "active",
                }
            )
            latest_attendance = await self._db["attendance"].find_one(
                {
                    "academy_id": academy_id,
                    "student_id": student_id,
                },
                sort=[("marked_at", -1)],
            )
            students.append(
                self._to_admin_summary(
                    doc,
                    active_session_count=active_session_count,
                    last_seen_at=latest_attendance.get("marked_at") if latest_attendance else None,
                    parent_name=user_info.get("name"),  # type: ignore[arg-type]
                    parent_email=user_info.get("email"),  # type: ignore[arg-type]
                )
            )
        return students
