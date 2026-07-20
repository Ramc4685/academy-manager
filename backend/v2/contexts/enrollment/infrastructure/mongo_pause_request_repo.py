"""Mongo pause request repository."""

from __future__ import annotations

from datetime import UTC, datetime

from bson import ObjectId as BsonObjectId

from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    PauseRequest,
)
from backend.v2.contexts.enrollment.domain.errors import EnrollmentNotFound
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoPauseRequestRepository(TenantScopedRepository):
    collection_name = "pause_requests"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> PauseRequest:
        return PauseRequest(
            pause_request_id=str(doc["pause_request_id"]),
            enrollment_id=str(doc["enrollment_id"]),
            parent_id=str(doc["parent_id"]),
            parent_name=_optional_str(doc.get("parent_name")),
            parent_email=_optional_str(doc.get("parent_email")),
            student_id=_optional_str(doc.get("student_id")),
            student_name=_optional_str(doc.get("student_name")),
            session_id=_optional_str(doc.get("session_id")),
            session_title=_optional_str(doc.get("session_title")),
            session_location=_optional_str(doc.get("session_location")),
            session_start_at=doc.get("session_start_at"),
            session_end_at=doc.get("session_end_at"),
            period=str(doc.get("period") or ""),
            pause_kind=doc.get("pause_kind", "fixed"),
            resume_on=doc.get("resume_on"),
            review_on=doc.get("review_on"),
            reason=str(doc.get("reason") or ""),
            status=doc.get("status", "pending"),
            created_at=doc["created_at"],
            decided_at=doc.get("decided_at"),
            decided_by=doc.get("decided_by"),
        )

    async def add(self, request: PauseRequest) -> None:
        doc = request.model_dump(mode="python")
        if request.resume_on is not None:
            doc["resume_on"] = request.resume_on.isoformat()
        if request.review_on is not None:
            doc["review_on"] = request.review_on.isoformat()
        await self._insert_one(doc)

    async def get(self, pause_request_id: str) -> PauseRequest | None:
        doc = await self._find_one({"pause_request_id": pause_request_id})
        return self._to_domain(doc) if doc else None

    async def list_for_parent(self, parent_id: str) -> list[PauseRequest]:
        cursor = self._find_many(
            {"parent_id": parent_id},
            sort=[("created_at", -1)],
            limit=100,
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_pending(self) -> list[PauseRequest]:
        cursor = self._find_many(
            {"status": "pending"},
            sort=[("created_at", 1)],
            limit=200,
        )
        return [await self._to_domain_with_context(doc) async for doc in cursor]

    async def approve(self, pause_request_id: str, *, admin_id: str) -> PauseRequest:
        request = await self.get(pause_request_id)
        if request is None:
            raise EnrollmentNotFound("pause request missing", pause_request_id=pause_request_id)
        now = datetime.now(UTC)
        await self._update_one(
            {"pause_request_id": pause_request_id},
            {"$set": {"status": "approved", "decided_at": now, "decided_by": admin_id}},
        )
        await self._db["enrollments"].update_one(
            {"academy_id": current_academy_id(), "enrollment_id": request.enrollment_id},
            {
                "$addToSet": {"skip_periods": request.period},
                "$set": {"updated_at": now},
            },
        )
        return request.model_copy(
            update={"status": "approved", "decided_at": now, "decided_by": admin_id}
        )

    async def decline(self, pause_request_id: str, *, admin_id: str) -> PauseRequest:
        request = await self.get(pause_request_id)
        if request is None:
            raise EnrollmentNotFound("pause request missing", pause_request_id=pause_request_id)
        now = datetime.now(UTC)
        await self._update_one(
            {"pause_request_id": pause_request_id},
            {"$set": {"status": "declined", "decided_at": now, "decided_by": admin_id}},
        )
        return request.model_copy(
            update={"status": "declined", "decided_at": now, "decided_by": admin_id}
        )

    async def enrollment_belongs_to_parent(self, enrollment_id: str, parent_id: str) -> bool:
        academy_id = current_academy_id()
        enrollment = await self._db["enrollments"].find_one(
            {"academy_id": academy_id, "enrollment_id": enrollment_id}
        )
        if not enrollment:
            return False
        student = await self._db["students"].find_one(
            {"academy_id": academy_id, "student_id": enrollment.get("student_id")}
        )
        return bool(
            student and str(student.get("parent_id") or student.get("parent_user_id")) == parent_id
        )

    async def _to_domain_with_context(self, doc: dict[str, object]) -> PauseRequest:
        academy_id = current_academy_id()
        request = self._to_domain(doc)

        # Try session-based enrollment first, then fall back to billing enrollment.
        enrollment = await self._db["enrollments"].find_one(
            {"academy_id": academy_id, "enrollment_id": request.enrollment_id}
        )
        billing_enrollment = None
        if enrollment is None:
            billing_enrollment = await self._db["student_billing_enrollments"].find_one(
                {
                    "academy_id": academy_id,
                    "$or": _id_or_value_filters(
                        request.enrollment_id,
                        "enrollment_id",
                        "billing_enrollment_id",
                        "student_billing_enrollment_id",
                    ),
                }
            )

        source = enrollment or billing_enrollment or {}
        student_id = _optional_str(source.get("student_id")) or request.student_id
        session_id = _optional_str(source.get("session_id")) or request.session_id
        session_type_id = _optional_str(source.get("session_type_id"))
        parent_id = (
            _optional_str(source.get("parent_id"))
            or _optional_str(source.get("parent_user_id"))
            or request.parent_id
        )

        student = None
        if student_id:
            student = await self._db["students"].find_one(
                {
                    "academy_id": academy_id,
                    "$or": _id_or_value_filters(student_id, "student_id"),
                }
            )
            parent_id = (
                _optional_str((student or {}).get("parent_id"))
                or _optional_str((student or {}).get("parent_user_id"))
                or parent_id
            )

        session = None
        if session_id:
            session = await self._db["sessions"].find_one(
                {
                    "academy_id": academy_id,
                    "$or": _id_or_value_filters(session_id, "session_id"),
                }
            )

        # For billing enrollments with no session, use the session type name as title.
        session_type = None
        if session is None and session_type_id:
            session_type = await self._db["session_types"].find_one(
                {
                    "academy_id": academy_id,
                    "$or": _id_or_value_filters(session_type_id, "session_type_id"),
                }
            )

        # Users collection is intentionally unscoped — do not filter by academy_id.
        parent = None
        if parent_id:
            parent = await self._db["users"].find_one(
                {
                    "$or": _id_or_value_filters(
                        parent_id,
                        "user_id",
                        "parent_id",
                        "firebase_uid",
                        "auth_uid",
                        "uid",
                    ),
                }
            )

        resolved_session_title = (
            request.session_title
            or _optional_str((session or {}).get("title"))
            or _optional_str((session_type or {}).get("name"))
        )

        return request.model_copy(
            update={
                "parent_name": request.parent_name or _display_name(parent),
                "parent_email": request.parent_email or _optional_str((parent or {}).get("email")),
                "student_id": student_id,
                "student_name": request.student_name or _student_name(student),
                "session_id": session_id,
                "session_title": resolved_session_title,
                "session_location": request.session_location
                or _optional_str((session or {}).get("location")),
                "session_start_at": request.session_start_at or (session or {}).get("start_at"),
                "session_end_at": request.session_end_at or (session or {}).get("end_at"),
            }
        )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _id_or_value_filters(value: str, *fields: str) -> list[dict[str, object]]:
    filters: list[dict[str, object]] = [{field: value} for field in fields]
    id_values: list[object] = [value]
    if BsonObjectId.is_valid(value):
        id_values.append(BsonObjectId(value))
    filters.append({"_id": {"$in": id_values}})
    return filters


def _student_name(doc: dict[str, object] | None) -> str | None:
    if not doc:
        return None
    first = str(doc.get("first_name") or "").strip()
    last = str(doc.get("last_name") or "").strip()
    return _optional_str(doc.get("full_name")) or _optional_str(f"{first} {last}")


def _display_name(doc: dict[str, object] | None) -> str | None:
    if not doc:
        return None
    first = str(doc.get("first_name") or "").strip()
    last = str(doc.get("last_name") or "").strip()
    return (
        _optional_str(doc.get("display_name"))
        or _optional_str(doc.get("name"))
        or _optional_str(f"{first} {last}")
    )
