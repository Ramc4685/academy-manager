"""Mongo StudentQuery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bson import ObjectId as BsonObjectId

from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    AdminStudentPage,
    AdminStudentSummary,
    decode_student_cursor,
    encode_student_cursor,
    full_name_key,
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
        attendance_rate: float | None,
        dues_status: str,
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
            attendance_rate=attendance_rate,
            dues_status=dues_status,  # type: ignore[arg-type]
        )

    async def list_admin_students(
        self,
        *,
        search: str | None,
        status: str | None,
        limit: int,
        cursor: str | None,
    ) -> AdminStudentPage:
        academy_id = current_academy_id()
        docs = [
            doc
            async for doc in self._find_many(
                {}, sort=[("full_name", 1), ("last_name", 1), ("first_name", 1)]
            )
        ]

        # Collect all parent_ids to batch-lookup users
        parent_ids = list(
            {
                str(doc.get("parent_id") or doc.get("parent_user_id") or "")
                for doc in docs
                if doc.get("parent_id") or doc.get("parent_user_id")
            }
        )
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
                display = (
                    str(
                        user.get("display_name")
                        or f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                        or ""
                    )
                    or None
                )
                email = user.get("email")
                for key in (
                    str(user.get("user_id") or ""),
                    str(user.get("firebase_uid") or ""),
                    str(user["_id"]),
                ):
                    if key:
                        users_by_id[key] = {"name": display, "email": email}

        rows: list[dict[str, object]] = []
        search_key = full_name_key(search or "") if search else None
        for doc in docs:
            student_id = self._summary_id(doc)
            parent_raw = str(doc.get("parent_id") or doc.get("parent_user_id") or "")
            user_info = users_by_id.get(parent_raw) or {}
            student_name = self._full_name(doc)
            row_status = str(doc.get("status") or "active")
            row_key = full_name_key(student_name)
            haystack = " ".join(
                full_name_key(str(value))
                for value in (
                    student_name,
                    user_info.get("name") or "",
                    user_info.get("email") or "",
                )
            )
            if status and row_status != status:
                continue
            if search_key and search_key not in haystack:
                continue
            rows.append(
                {
                    "doc": doc,
                    "student_id": student_id,
                    "full_name_key": row_key,
                    "parent_raw": parent_raw,
                    "parent_name": user_info.get("name"),
                    "parent_email": user_info.get("email"),
                }
            )

        rows.sort(key=lambda row: (str(row["full_name_key"]), str(row["student_id"])))

        if cursor:
            decoded = decode_student_cursor(cursor)
            rows = [
                row
                for row in rows
                if (
                    str(row["full_name_key"]),
                    str(row["student_id"]),
                )
                > (decoded.full_name_key, decoded.student_id)
            ]

        page_rows = rows[: limit + 1]
        has_next = len(page_rows) > limit
        page_rows = page_rows[:limit]
        student_ids = [str(row["student_id"]) for row in page_rows]

        active_counts = await self._active_session_counts(academy_id, student_ids)
        attendance = await self._attendance_summaries(academy_id, student_ids)
        dues = await self._dues_statuses(academy_id, student_ids)

        students: list[AdminStudentSummary] = []
        for row in page_rows:
            doc = row["doc"]  # type: ignore[assignment]
            student_id = str(row["student_id"])
            att = attendance.get(student_id, {})
            students.append(
                self._to_admin_summary(
                    doc,  # type: ignore[arg-type]
                    active_session_count=active_counts.get(student_id, 0),
                    last_seen_at=att.get("last_seen_at"),
                    attendance_rate=att.get("attendance_rate"),  # type: ignore[arg-type]
                    dues_status=dues.get(student_id, "current"),
                    parent_name=row.get("parent_name"),  # type: ignore[arg-type]
                    parent_email=row.get("parent_email"),  # type: ignore[arg-type]
                )
            )

        next_cursor = None
        if has_next and page_rows:
            last = page_rows[-1]
            next_cursor = encode_student_cursor(
                str(last["full_name_key"]),
                str(last["student_id"]),
            )
        return AdminStudentPage(students=students, next_cursor=next_cursor)

    @staticmethod
    def _full_name(doc: dict[str, object]) -> str:
        first = str(doc.get("first_name") or "").strip()
        last = str(doc.get("last_name") or "").strip()
        raw = str(doc.get("full_name") or f"{first} {last}".strip() or "Unnamed student")
        return " ".join(raw.split())

    async def _active_session_counts(
        self,
        academy_id: str,
        student_ids: list[str],
    ) -> dict[str, int]:
        if not student_ids:
            return {}
        cursor = self._db["enrollments"].aggregate(
            [
                {
                    "$match": {
                        "academy_id": academy_id,
                        "student_id": {"$in": student_ids},
                        "status": "active",
                    }
                },
                {"$group": {"_id": "$student_id", "count": {"$sum": 1}}},
            ]
        )
        return {str(row["_id"]): int(row["count"]) async for row in cursor}

    async def _attendance_summaries(
        self,
        academy_id: str,
        student_ids: list[str],
    ) -> dict[str, dict[str, object]]:
        if not student_ids:
            return {}
        since = datetime.now(UTC) - timedelta(days=90)
        cursor = self._db["attendance"].aggregate(
            [
                {
                    "$match": {
                        "academy_id": academy_id,
                        "student_id": {"$in": student_ids},
                        "marked_at": {"$gte": since},
                    }
                },
                {
                    "$group": {
                        "_id": "$student_id",
                        "total": {"$sum": 1},
                        "attended": {
                            "$sum": {
                                "$cond": [
                                    {"$in": ["$status", ["present", "late"]]},
                                    1,
                                    0,
                                ]
                            }
                        },
                        "last_seen_at": {"$max": "$marked_at"},
                    }
                },
            ]
        )
        out: dict[str, dict[str, object]] = {}
        async for row in cursor:
            total = int(row.get("total") or 0)
            attended = int(row.get("attended") or 0)
            out[str(row["_id"])] = {
                "attendance_rate": attended / total if total else None,
                "last_seen_at": self._as_utc(row["last_seen_at"])
                if isinstance(row.get("last_seen_at"), datetime)
                else row.get("last_seen_at"),
            }
        return out

    async def _dues_statuses(
        self,
        academy_id: str,
        student_ids: list[str],
    ) -> dict[str, str]:
        if not student_ids:
            return {}
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=30)
        statuses = {student_id: "current" for student_id in student_ids}
        cursor = self._db["payments"].find(
            {
                "academy_id": academy_id,
                "student_id": {"$in": student_ids},
                "status": {"$in": ["pending", "failed", "expired"]},
                "is_deleted": {"$ne": True},
            }
        )
        async for doc in cursor:
            student_id = str(doc.get("student_id") or "")
            if self._payment_is_overdue(doc, now, cutoff):
                statuses[student_id] = "overdue"
            elif statuses.get(student_id) != "overdue":
                statuses[student_id] = "due"
        return statuses

    @staticmethod
    def _payment_is_overdue(
        doc: dict[str, object],
        now: datetime,
        cutoff: datetime,
    ) -> bool:
        if str(doc.get("status") or "") == "failed":
            return True
        due_at = doc.get("due_at") or doc.get("invoice_due_at") or doc.get("due_date")
        if isinstance(due_at, datetime):
            return MongoStudentRepository._as_utc(due_at) < now
        created_at = doc.get("created_at") or doc.get("invoice_created_at")
        return (
            isinstance(created_at, datetime) and MongoStudentRepository._as_utc(created_at) < cutoff
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
