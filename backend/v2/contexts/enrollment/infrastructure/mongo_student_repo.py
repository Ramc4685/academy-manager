"""Mongo StudentQuery."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from bson import ObjectId as BsonObjectId
from pymongo import ReturnDocument

from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    AdminStudentCurrentPaymentSummary,
    AdminStudentDetail,
    AdminStudentPage,
    AdminStudentParentChangeResult,
    AdminStudentParentSummary,
    AdminStudentPaymentSummary,
    AdminStudentRecentAttendance,
    AdminStudentSessionSummary,
    AdminStudentSummary,
    ChangeAdminStudentParentCommand,
    UpdateAdminStudentCommand,
    decode_student_cursor,
    encode_student_cursor,
    full_name_key,
)
from backend.v2.contexts.enrollment.domain.errors import (
    StudentParentInactive,
    StudentParentInvalidRole,
    StudentParentNotFound,
)
from backend.v2.contexts.enrollment.domain.models import Student
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id

log = logging.getLogger(__name__)


class MongoStudentRepository(TenantScopedRepository):
    collection_name = "students"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Student:
        return Student(
            student_id=str(doc["student_id"]),
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc["parent_id"]),
            full_name=str(doc["full_name"]),
            date_of_birth=(str(doc["date_of_birth"]) if doc.get("date_of_birth") else None),
            student_user_id=(str(doc["student_user_id"]) if doc.get("student_user_id") else None),
        )

    @staticmethod
    def _registration_name(value: object) -> str:
        return " ".join(str(value).casefold().split())

    async def find_registration_student(
        self,
        *,
        parent_id: str,
        full_name: str,
        date_of_birth: str | None,
    ) -> str | None:
        """Resolve a unique child without trusting a client-supplied id."""
        candidates = await self._registration_candidates(parent_id=parent_id, full_name=full_name)
        exact = [
            doc
            for doc in candidates
            if str(doc.get("date_of_birth") or "").strip() == (date_of_birth or "")
        ]
        if date_of_birth:
            return self._summary_id(exact[0]) if len(exact) == 1 else None
        # Missing DOB is safe only when one same-name legacy record also lacks
        # DOB. Multiple siblings or a dated record require manual review.
        undated = [doc for doc in candidates if not doc.get("date_of_birth")]
        return self._summary_id(undated[0]) if len(candidates) == len(undated) == 1 else None

    async def has_ambiguous_registration_match(
        self,
        *,
        parent_id: str,
        full_name: str,
        date_of_birth: str | None,
    ) -> bool:
        candidates = await self._registration_candidates(parent_id=parent_id, full_name=full_name)
        if not candidates:
            return False
        if date_of_birth:
            exact = [
                doc
                for doc in candidates
                if str(doc.get("date_of_birth") or "").strip() == date_of_birth
            ]
            # A unique exact DOB is safe. With no exact match, fully dated
            # candidates are known to be different children; undated legacy
            # candidates remain ambiguous because they cannot be disproved.
            return len(exact) > 1 or any(not doc.get("date_of_birth") for doc in candidates)
        return len(candidates) != 1 or any(doc.get("date_of_birth") for doc in candidates)

    async def _registration_candidates(
        self, *, parent_id: str, full_name: str
    ) -> list[dict[str, object]]:
        expected_name = self._registration_name(full_name)
        cursor = self._find_many({"$or": [{"parent_id": parent_id}, {"parent_user_id": parent_id}]})
        candidates: list[dict[str, object]] = []
        async for doc in cursor:
            stored_name = doc.get("full_name") or " ".join(
                str(doc.get(key) or "") for key in ("first_name", "last_name")
            )
            if self._registration_name(stored_name) != expected_name:
                continue
            candidates.append(doc)
        return candidates

    async def claim_registration(
        self,
        student_id: str,
        application_id: str,
        *,
        claim_token: str,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> bool:
        doc = await self._find_one_and_update(
            {
                "$and": [
                    self._id_filter(student_id),
                    {
                        "$or": [
                            {"registration_application_id": {"$exists": False}},
                            {"registration_application_id": None},
                            {
                                "registration_application_id": application_id,
                                "registration_claim_token": claim_token,
                            },
                            {"registration_claimed_at": {"$lte": stale_before}},
                            {"registration_claimed_at": {"$exists": False}},
                        ]
                    },
                ],
            },
            {
                "$set": {
                    "registration_application_id": application_id,
                    "registration_claim_token": claim_token,
                    "registration_claimed_at": claimed_at,
                }
            },
        )
        return doc is not None

    async def release_registration(
        self,
        student_id: str,
        application_id: str,
        *,
        claim_token: str,
    ) -> None:
        await self._update_one(
            {
                "$and": [
                    self._id_filter(student_id),
                    {
                        "registration_application_id": application_id,
                        "registration_claim_token": claim_token,
                    },
                ]
            },
            {
                "$unset": {
                    "registration_application_id": "",
                    "registration_claimed_at": "",
                    "registration_claim_token": "",
                }
            },
        )

    async def has_active_enrollment(
        self,
        student_id: str,
        *,
        exclude_enrollment_id: str | None = None,
    ) -> bool:
        filter_: dict[str, object] = {
            "student_id": student_id,
            "status": {"$in": ["active", "paused"]},
        }
        if exclude_enrollment_id is not None:
            filter_["enrollment_id"] = {"$ne": exclude_enrollment_id}
        enrollment = await self._find_one_in_collection(
            "enrollments",
            filter_,
        )
        return enrollment is not None

    async def by_ids(self, student_ids: list[str]) -> list[Student]:
        if not student_ids:
            return []
        cursor = self._find_many({"student_id": {"$in": student_ids}})
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_parent(self, parent_id: str) -> list[Student]:
        # Parent docs carry the parent id under either ``parent_id`` (newer) or
        # ``parent_user_id`` (legacy, pre-migration) — query both. Used by the
        # parent daily digest to fan out over a family's children.
        cursor = self._find_many({"$or": [{"parent_id": parent_id}, {"parent_user_id": parent_id}]})
        students: list[Student] = []
        async for doc in cursor:
            if "parent_id" not in doc and "parent_user_id" in doc:
                doc = {**doc, "parent_id": doc["parent_user_id"]}
            students.append(self._to_domain(doc))
        return students

    async def get_parent_user_doc(self, parent_id: str) -> dict[str, Any] | None:
        # Raw parent ``users`` doc (tenant-scoped), used by the parent daily
        # digest for portal-status + display-name. Lives in infrastructure so the
        # raw users read stays out of the composition layer. Mirrors the id
        # resolution in ``_parent_info`` (user_id / auth_uid / firebase_uid / _id).
        if not parent_id:
            return None
        academy_id = current_academy_id()
        or_filter: list[dict[str, object]] = [
            {"user_id": parent_id},
            {"auth_uid": parent_id},
            {"firebase_uid": parent_id},
        ]
        if BsonObjectId.is_valid(parent_id):
            or_filter.append({"_id": BsonObjectId(parent_id)})
        doc: dict[str, Any] | None = await self._db["users"].find_one(
            {"academy_id": academy_id, "$or": or_filter}
        )
        return doc

    async def get_by_student_user_id(self, student_user_id: str) -> Student | None:
        """UIM12: resolve the Student a login user_id is linked to.

        Used by the student BFF composition to turn `AuthClaims.user_id`
        into the caller's own `student_id`. Tenant-scoped like every other
        read here — a student login can only ever resolve within the
        academy the request was resolved for.

        **Fails closed on ambiguity.** If two student docs in this academy
        somehow carry the same `student_user_id` (the unique index in
        migration 0150 and the provisioning-path checks both exist to make
        this impossible), returning either one would show the signed-in
        student someone else's data. A duplicate degrades to "no access",
        never to "wrong student's data", and is logged loudly so the
        corrupt link is repaired rather than silently served.
        """
        if not student_user_id:
            return None
        docs = [doc async for doc in self._find_many({"student_user_id": student_user_id}, limit=2)]
        if not docs:
            return None
        if len(docs) > 1:
            log.warning(
                "student_user_id_ambiguous: %s student docs share student_user_id=%s in "
                "academy=%s; refusing to resolve (fail closed)",
                len(docs),
                student_user_id,
                current_academy_id(),
            )
            return None
        return self._to_domain(docs[0])

    async def count_students_linked_to_user(
        self, student_user_id: str, *, excluding_student_id: str | None = None
    ) -> int:
        """UIM12: how many students in this academy already link to this user.

        Used as the provisioning-path pre-check so an admin gets a clean
        409 *before* any Firebase account or membership is created. Counts
        rather than fetching, because the answer that matters is "more than
        zero" even when the link table is already corrupt (which is exactly
        the case `get_by_student_user_id` refuses to resolve).
        """
        if not student_user_id:
            return 0
        filter_: dict[str, object] = {"student_user_id": student_user_id}
        if excluding_student_id is not None:
            filter_["student_id"] = {"$ne": excluding_student_id}
        count: int = await self.collection.count_documents(self._scoped(filter_))
        return count

    async def get_for_parent(self, parent_id: str, student_id: str) -> Student | None:
        # legacy docs use parent_user_id; newer docs use parent_id — query both during migration
        doc = await self._find_one(
            {
                "student_id": student_id,
                "$or": [{"parent_id": parent_id}, {"parent_user_id": parent_id}],
            }
        )
        if doc and "parent_id" not in doc and "parent_user_id" in doc:
            doc = {**doc, "parent_id": doc["parent_user_id"]}
        return self._to_domain(doc) if doc else None

    @staticmethod
    def _summary_id(doc: dict[str, object]) -> str:
        return str(doc.get("student_id") or doc.get("_id"))

    @staticmethod
    def _id_filter(student_id: str) -> dict[str, object]:
        or_filter: list[dict[str, object]] = [{"student_id": student_id}]
        if BsonObjectId.is_valid(student_id):
            or_filter.append({"_id": BsonObjectId(student_id)})
        return {"$or": or_filter}

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
            last_seen_at=last_seen_at,
            attendance_rate=attendance_rate,
            dues_status=dues_status,
        )

    @classmethod
    def _to_admin_detail(
        cls,
        doc: dict[str, object],
        *,
        active_session_count: int,
        last_seen_at: object | None,
        attendance_rate: float | None,
        dues_status: str,
        parent_name: str | None = None,
        parent_email: str | None = None,
        parent_phone: str | None = None,
        enrolled_sessions: list[AdminStudentSessionSummary] | None = None,
        payment_history: list[AdminStudentPaymentSummary] | None = None,
        current_payment: AdminStudentCurrentPaymentSummary | None = None,
        outstanding_balance_cents: int = 0,
        waiver_status: str = "unknown",
        waiver_signed_at: datetime | None = None,
        waiver_version: str | None = None,
        recent_attendance: list[AdminStudentRecentAttendance] | None = None,
    ) -> AdminStudentDetail:
        summary = cls._to_admin_summary(
            doc,
            active_session_count=active_session_count,
            last_seen_at=last_seen_at,
            attendance_rate=attendance_rate,
            dues_status=dues_status,
            parent_name=parent_name,
            parent_email=parent_email,
        )
        raw_dob = doc.get("date_of_birth") or doc.get("dob")
        dob: date | None = None
        if isinstance(raw_dob, datetime):
            dob = raw_dob.date()
        elif isinstance(raw_dob, date):
            dob = raw_dob
        elif isinstance(raw_dob, str) and raw_dob:
            dob = date.fromisoformat(raw_dob[:10])
        raw_level = doc.get("level") if doc.get("level") is not None else doc.get("skill_level")
        return AdminStudentDetail(
            **summary.model_dump(),
            date_of_birth=dob,
            level=cls._optional_str(raw_level),
            notes=cls._optional_str(doc.get("notes")),
            parent_phone=parent_phone,
            parent_details=None,
            previous_experience=cls._optional_str(doc.get("previous_experience")),
            medical_notes=cls._optional_str(doc.get("medical_notes")),
            emergency_contact_name=cls._optional_str(doc.get("emergency_contact_name")),
            emergency_contact_phone=cls._optional_str(doc.get("emergency_contact_phone")),
            t_shirt_size=cls._optional_str(doc.get("t_shirt_size")),
            waiver_status=waiver_status,
            waiver_signed_at=waiver_signed_at,
            waiver_version=waiver_version,
            recent_attendance=recent_attendance or [],
            enrolled_sessions=enrolled_sessions or [],
            payment_history=payment_history or [],
            current_payment=current_payment,
            outstanding_balance_cents=outstanding_balance_cents,
        )

    async def get_admin_student(self, student_id: str) -> AdminStudentDetail | None:
        academy_id = current_academy_id()
        doc = await self._find_one(self._id_filter(student_id))
        if doc is None:
            return None
        resolved_id = self._summary_id(doc)
        parent_info = await self._parent_info(
            academy_id, str(doc.get("parent_id") or doc.get("parent_user_id") or "")
        )
        active_counts = await self._active_session_counts(academy_id, [resolved_id])
        attendance = await self._attendance_summaries(academy_id, [resolved_id])
        dues = await self._dues_statuses(academy_id, [resolved_id])
        enrolled_sessions = await self._admin_student_enrolled_sessions(
            academy_id=academy_id,
            student_id=resolved_id,
        )
        payment_history = await self._admin_student_payment_history(
            academy_id=academy_id,
            student_id=resolved_id,
            enrollment_ids=[
                session.enrollment_id for session in enrolled_sessions if session.enrollment_id
            ],
        )
        current_payment = self._admin_student_current_payment(
            payment_history=payment_history,
            enrolled_sessions=enrolled_sessions,
        )
        outstanding_balance_cents = self._admin_student_outstanding_balance(payment_history)
        waiver_status, waiver_signed_at, waiver_version = await self._waiver_summary(
            academy_id=academy_id,
            student_id=resolved_id,
            student_doc=doc,
        )
        recent_attendance = await self._recent_attendance(
            academy_id=academy_id,
            student_id=resolved_id,
        )
        att = attendance.get(resolved_id, {})
        return self._to_admin_detail(
            doc,
            active_session_count=active_counts.get(resolved_id, 0),
            last_seen_at=att.get("last_seen_at"),
            attendance_rate=att.get("attendance_rate"),  # type: ignore[arg-type]
            dues_status=dues.get(resolved_id, "current"),
            parent_name=parent_info.get("name"),
            parent_email=parent_info.get("email"),
            parent_phone=parent_info.get("phone"),
            enrolled_sessions=enrolled_sessions,
            payment_history=payment_history,
            current_payment=current_payment,
            outstanding_balance_cents=outstanding_balance_cents,
            waiver_status=waiver_status,
            waiver_signed_at=waiver_signed_at,
            waiver_version=waiver_version,
            recent_attendance=recent_attendance,
        )

    async def update_admin_student(
        self,
        student_id: str,
        command: UpdateAdminStudentCommand,
    ) -> AdminStudentDetail | None:
        academy_id = current_academy_id()
        before = await self._find_one(self._id_filter(student_id))
        if before is None:
            return None

        set_doc: dict[str, object] = {"updated_at": datetime.now(UTC)}
        if command.full_name is not None:
            set_doc["full_name"] = " ".join(command.full_name.split())
        if command.date_of_birth is not None:
            set_doc["date_of_birth"] = command.date_of_birth.isoformat()
        if command.status is not None:
            set_doc["status"] = command.status
        if command.parent_id is not None:
            set_doc["parent_id"] = command.parent_id
        if command.notes is not None:
            set_doc["notes"] = command.notes
        if command.previous_experience is not None:
            set_doc["previous_experience"] = command.previous_experience.strip() or None
        if command.medical_notes is not None:
            set_doc["medical_notes"] = command.medical_notes.strip() or None
        if command.emergency_contact_name is not None:
            set_doc["emergency_contact_name"] = command.emergency_contact_name.strip() or None
        if command.emergency_contact_phone is not None:
            set_doc["emergency_contact_phone"] = command.emergency_contact_phone.strip() or None
        if command.t_shirt_size is not None:
            set_doc["t_shirt_size"] = command.t_shirt_size.strip() or None

        changed = [
            key
            for key, value in set_doc.items()
            if key != "updated_at" and before.get(key) != value
        ]
        updated = await self.collection.find_one_and_update(
            self._scoped(self._id_filter(student_id)),
            {"$set": set_doc},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            return None
        if changed:
            await self._write_audit(
                academy_id=academy_id,
                actor_id=command.actor_id,
                action="student.edited",
                entity_id=self._summary_id(updated),
                reason=command.reason,
                changed_keys=changed,
                before=before,
                after=updated,
            )
        return await self.get_admin_student(self._summary_id(updated))

    async def change_admin_student_parent(
        self,
        student_id: str,
        command: ChangeAdminStudentParentCommand,
    ) -> AdminStudentParentChangeResult | None:
        academy_id = current_academy_id()
        before = await self._find_one(self._id_filter(student_id))
        if before is None:
            return None

        parent = await self._find_parent_for_change(academy_id, command.parent_id)
        if parent is None:
            raise StudentParentNotFound("parent not found")
        if not self._parent_is_active(parent):
            raise StudentParentInactive("parent is inactive", parent_id=command.parent_id)
        if not self._parent_has_parent_role(parent):
            raise StudentParentInvalidRole(
                "user does not have parent role", parent_id=command.parent_id
            )

        new_parent_id = self._canonical_parent_id(parent)
        old_parent_id = str(before.get("parent_id") or before.get("parent_user_id") or "")
        impact_counts = await self._parent_change_impact_counts(
            academy_id=academy_id,
            student_id=self._summary_id(before),
            old_parent_ids=self._parent_lookup_ids_from_student(before),
        )
        now = datetime.now(UTC)
        updated = await self.collection.find_one_and_update(
            self._scoped(self._id_filter(student_id)),
            {
                "$set": {
                    "parent_id": new_parent_id,
                    "parent_user_id": new_parent_id,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            return None

        await self._write_parent_change_audit(
            academy_id=academy_id,
            actor_id=command.actor_id,
            student_id=self._summary_id(updated),
            reason=command.reason,
            old_parent_id=old_parent_id or None,
            new_parent_id=new_parent_id,
            impact_counts=impact_counts,
            created_at=now,
        )
        return AdminStudentParentChangeResult(
            student_id=self._summary_id(updated),
            parent=AdminStudentParentSummary(
                parent_id=new_parent_id,
                display_name=self._parent_display_name(parent)
                or parent.get("email")
                or new_parent_id,
                email=str(parent.get("email") or ""),
                phone=str(parent.get("phone")) if parent.get("phone") is not None else None,
            ),
            previous_parent_id=old_parent_id or None,
            warnings=["Historical billing, waiver, credit, and waitlist rows were not rewritten."],
            impact_counts=impact_counts,
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
                        users_by_id[key] = {
                            "name": display,
                            "email": email,
                            "phone": user.get("phone"),
                        }

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
            doc = row["doc"]
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

    async def _admin_student_enrolled_sessions(
        self,
        *,
        academy_id: str,
        student_id: str,
    ) -> list[AdminStudentSessionSummary]:
        enrollments = [
            doc
            async for doc in self._db["enrollments"]
            .find(
                {
                    "academy_id": academy_id,
                    "student_id": student_id,
                    "status": "active",
                    "is_deleted": {"$ne": True},
                }
            )
            .sort([("enrolled_at", 1), ("created_at", 1), ("enrollment_id", 1)])
        ]
        session_ids = [
            str(doc.get("session_id")) for doc in enrollments if doc.get("session_id") is not None
        ]
        sessions_by_id = await self._sessions_by_id(academy_id, session_ids)
        rows: list[AdminStudentSessionSummary] = []
        for enrollment in enrollments:
            session_id = str(enrollment.get("session_id") or "")
            session = sessions_by_id.get(session_id) or {}
            rows.append(
                AdminStudentSessionSummary(
                    enrollment_id=str(enrollment.get("enrollment_id") or enrollment.get("_id")),
                    session_id=session_id,
                    session_title=str(
                        session.get("title") or session.get("name") or "Academy session"
                    ),
                    location=str(session.get("location") or "") or None,
                    start_at=self._coerce_datetime(session.get("start_at")),
                    end_at=self._coerce_datetime(session.get("end_at")),
                    status=str(enrollment.get("status") or "active"),
                    payment_mode=self._optional_str(enrollment.get("payment_mode")),
                    subscription_status=self._optional_str(
                        enrollment.get("subscription_status")
                        or enrollment.get("billing_status")
                        or enrollment.get("stripe_subscription_status")
                    ),
                    amount_cents=self._enrollment_session_amount_cents(enrollment, session),
                )
            )
        rows.sort(
            key=lambda row: (row.start_at or datetime.max.replace(tzinfo=UTC), row.session_id)
        )
        return rows

    async def _sessions_by_id(
        self,
        academy_id: str,
        session_ids: list[str],
    ) -> dict[str, dict[str, object]]:
        if not session_ids:
            return {}
        object_ids = [
            BsonObjectId(session_id)
            for session_id in session_ids
            if BsonObjectId.is_valid(session_id)
        ]
        filters: list[dict[str, object]] = [{"session_id": {"$in": session_ids}}]
        if object_ids:
            filters.append({"_id": {"$in": object_ids}})
        cursor = self._db["sessions"].find({"academy_id": academy_id, "$or": filters})
        sessions: dict[str, dict[str, object]] = {}
        async for session in cursor:
            for key in (session.get("session_id"), session.get("_id")):
                if key is not None:
                    sessions[str(key)] = session
        return sessions

    async def _admin_student_payment_history(
        self,
        *,
        academy_id: str,
        student_id: str,
        enrollment_ids: list[str] | None = None,
    ) -> list[AdminStudentPaymentSummary]:
        payment_owner_filters: list[dict[str, object]] = [{"student_id": student_id}]
        if enrollment_ids:
            payment_owner_filters.append({"enrollment_id": {"$in": enrollment_ids}})
        cursor = self._db["payments"].aggregate(
            [
                {
                    "$match": {
                        "academy_id": academy_id,
                        "$or": payment_owner_filters,
                        "is_deleted": {"$ne": True},
                    }
                },
                {
                    "$addFields": {
                        "_admin_sort_at": {"$ifNull": ["$created_at", "$invoice_created_at"]},
                        "_admin_sort_payment_id": {"$ifNull": ["$payment_id", ""]},
                    }
                },
                {
                    "$sort": {
                        "_admin_sort_at": -1,
                        "_admin_sort_payment_id": -1,
                        "_id": -1,
                    }
                },
                {"$limit": 200},
                {"$project": {"_admin_sort_at": 0, "_admin_sort_payment_id": 0}},
            ]
        )
        docs = [doc async for doc in cursor]

        # New one-off checkout payments are ledger-native (Phase 5 freeze):
        # they live in ledger_payments with payment_origin="legacy_payment"
        # instead of the legacy payments collection. Union them in.
        seen_payment_ids = {str(doc.get("payment_id") or doc.get("_id") or "") for doc in docs}
        ledger_shape_cursor = self._db["ledger_payments"].find(
            {
                "academy_id": academy_id,
                "payment_origin": "legacy_payment",
                "$or": payment_owner_filters,
                "is_deleted": {"$ne": True},
            },
            sort=[("created_at", -1)],
            limit=200,
        )
        async for doc in ledger_shape_cursor:
            if str(doc.get("payment_id") or "") not in seen_payment_ids:
                docs.append(doc)

        # Billing-ledger invoices (autopay / Stripe subscription) live in a
        # separate collection. Include enrollment-owned invoices and prefer the
        # ledger shim over a matching transition-only legacy Payment projection.
        invoice_owner_filters: list[dict[str, object]] = [{"student_id": student_id}]
        if enrollment_ids:
            invoice_owner_filters.append({"enrollment_id": {"$in": enrollment_ids}})
        invoice_cursor = self._db["invoices"].find(
            {
                "academy_id": academy_id,
                "$or": invoice_owner_filters,
                "status": {"$nin": ["void"]},
                "is_deleted": {"$ne": True},
            }
        )
        invoice_docs = [inv_doc async for inv_doc in invoice_cursor]
        invoice_provider_keys: set[str] = {
            key
            for inv_doc in invoice_docs
            for key in (inv_doc.get("stripe_invoice_id"),)
            if isinstance(key, str) and key
        }
        if invoice_provider_keys:
            docs = [
                doc
                for doc in docs
                if str(doc.get("stripe_payment_intent_id") or "") not in invoice_provider_keys
                and str(doc.get("stripe_invoice_id") or "") not in invoice_provider_keys
            ]
        covered_invoice_ids: set[str] = {
            str(doc["invoice_id"]) for doc in docs if doc.get("invoice_id")
        }
        for inv_doc in invoice_docs:
            inv_id = str(inv_doc.get("invoice_id") or inv_doc.get("_id") or "")
            if inv_id and inv_id not in covered_invoice_ids:
                covered_invoice_ids.add(inv_id)
                docs.append(self._invoice_doc_to_payment_doc(inv_doc))

        docs.sort(
            key=lambda doc: (
                self._coerce_datetime(doc.get("created_at") or doc.get("invoice_created_at"))
                or datetime.min.replace(tzinfo=UTC),
                str(doc.get("payment_id") or doc.get("_id") or ""),
            ),
            reverse=True,
        )
        return [self._to_admin_student_payment_summary(doc) for doc in docs]

    @staticmethod
    def _invoice_doc_to_payment_doc(inv_doc: dict[str, object]) -> dict[str, object]:
        """Shim a billing-ledger invoice doc into the payment-summary shape."""
        total = int(inv_doc.get("total_cents") or inv_doc.get("subtotal_cents") or 0)
        balance = int(inv_doc.get("balance_due_cents") or 0)
        return {
            "payment_id": str(inv_doc.get("invoice_id") or inv_doc.get("_id")),
            "student_id": inv_doc.get("student_id"),
            "period": inv_doc.get("period"),
            "amount_cents": total,
            "gross_amount_cents": total,
            "final_amount_cents": total,
            "paid_amount_cents": max(total - balance, 0),
            "balance_due_cents": balance,
            "status": str(inv_doc.get("status") or "open"),
            "payment_method": "autopay",
            "stripe_invoice_id": inv_doc.get("stripe_invoice_id"),
            "created_at": inv_doc.get("created_at"),
        }

    @classmethod
    def _to_admin_student_payment_summary(
        cls,
        doc: dict[str, object],
    ) -> AdminStudentPaymentSummary:
        amount_cents = cls._amount_cents(doc)
        paid_amount_cents = cls._paid_amount_cents(doc, amount_cents)
        balance_due_cents = cls._balance_due_cents(doc, amount_cents, paid_amount_cents)
        created_at = cls._coerce_datetime(doc.get("created_at") or doc.get("invoice_created_at"))
        return AdminStudentPaymentSummary(
            payment_id=str(doc.get("payment_id") or doc.get("_id")),
            session_id=cls._optional_str(doc.get("session_id")),
            period=cls._optional_str(doc.get("period") or doc.get("billing_period")),
            amount_cents=amount_cents,
            paid_amount_cents=paid_amount_cents,
            balance_due_cents=balance_due_cents,
            status=str(doc.get("status") or "pending"),
            payment_method=cls._optional_str(doc.get("payment_method")),
            invoice_number=cls._optional_str(doc.get("invoice_number")),
            paid_at=cls._coerce_datetime(doc.get("paid_at")),
            stripe_invoice_id=cls._optional_str(doc.get("stripe_invoice_id")),
            stripe_payment_intent_id=cls._optional_str(doc.get("stripe_payment_intent_id")),
            created_at=created_at or datetime.now(UTC),
        )

    @staticmethod
    def _admin_student_current_payment(
        *,
        payment_history: list[AdminStudentPaymentSummary],
        enrolled_sessions: list[AdminStudentSessionSummary],
    ) -> AdminStudentCurrentPaymentSummary | None:
        open_statuses = {
            "open",
            "unpaid",
            "partially_paid",
            "partial",
            "pending",
            "failed",
            "expired",
        }
        for payment in payment_history:
            if payment.status in open_statuses and payment.balance_due_cents > 0:
                return AdminStudentCurrentPaymentSummary(
                    amount_cents=payment.balance_due_cents,
                    source="invoice",
                    status=payment.status,
                    period=payment.period,
                    payment_id=payment.payment_id,
                    session_id=payment.session_id,
                )
        return None

    @staticmethod
    def _admin_student_outstanding_balance(
        payment_history: list[AdminStudentPaymentSummary],
    ) -> int:
        open_statuses = {
            "open",
            "unpaid",
            "partially_paid",
            "partial",
            "pending",
            "failed",
            "expired",
        }
        return sum(
            max(payment.balance_due_cents, 0)
            for payment in payment_history
            if payment.status in open_statuses and payment.balance_due_cents > 0
        )

    async def _waiver_summary(
        self,
        *,
        academy_id: str,
        student_id: str,
        student_doc: dict[str, object],
    ) -> tuple[str, datetime | None, str | None]:
        tenant_filter = {
            "$or": [
                {"academy_id": academy_id},
                {"academy_id": {"$exists": False}},
                {"academy_id": None},
            ]
        }
        signature_docs = [
            doc
            async for doc in self._db["waiver_signatures"]
            .find(
                {
                    "student_id": student_id,
                    "is_deleted": {"$ne": True},
                    **tenant_filter,
                }
            )
            .sort([("signed_at", -1), ("created_at", -1), ("_id", -1)])
            .limit(1)
        ]
        if signature_docs:
            doc = signature_docs[0]
            template_id = self._optional_str(
                doc.get("waiver_template_id") or doc.get("waiver_version_id")
            )
            version = await self._waiver_version_label(academy_id, template_id)
            return (
                "signed",
                self._coerce_datetime(doc.get("signed_at") or doc.get("created_at")),
                self._optional_str(doc.get("waiver_version") or version),
            )

        acceptance_docs = [
            doc
            async for doc in self._db["waiver_acceptances"]
            .find(
                {
                    "student_id": student_id,
                    "is_deleted": {"$ne": True},
                    **tenant_filter,
                }
            )
            .sort([("accepted_at", -1), ("created_at", -1), ("_id", -1)])
            .limit(1)
        ]
        if acceptance_docs:
            doc = acceptance_docs[0]
            version_id = self._optional_str(
                doc.get("waiver_version_id") or doc.get("waiver_template_id")
            )
            version = await self._waiver_version_label(academy_id, version_id)
            return (
                "signed",
                self._coerce_datetime(doc.get("accepted_at") or doc.get("created_at")),
                self._optional_str(doc.get("waiver_version") or doc.get("version") or version),
            )

        if student_doc.get("waiver_accepted") is True:
            return (
                "signed",
                self._coerce_datetime(
                    student_doc.get("waiver_accepted_at") or student_doc.get("waiver_date")
                ),
                self._optional_str(student_doc.get("waiver_version")),
            )
        return ("missing", None, None)

    async def _waiver_version_label(
        self,
        academy_id: str,
        waiver_id: str | None,
    ) -> str | None:
        if not waiver_id:
            return None
        filters: list[dict[str, object]] = [
            {"waiver_version_id": waiver_id},
            {"waiver_template_id": waiver_id},
            {"waiver_id": waiver_id},
        ]
        if BsonObjectId.is_valid(waiver_id):
            filters.append({"_id": BsonObjectId(waiver_id)})
        doc = await self._db["waiver_versions"].find_one(
            {
                "$and": [
                    {
                        "$or": [
                            {"academy_id": academy_id},
                            {"academy_id": {"$exists": False}},
                            {"academy_id": None},
                        ]
                    },
                    {"$or": filters},
                ]
            }
        )
        if doc is None:
            return None
        return self._optional_str(doc.get("version") or doc.get("name") or doc.get("title"))

    async def _recent_attendance(
        self,
        *,
        academy_id: str,
        student_id: str,
    ) -> list[AdminStudentRecentAttendance]:
        cursor = (
            self._db["attendance"]
            .find(
                {
                    "academy_id": academy_id,
                    "student_id": student_id,
                    "is_deleted": {"$ne": True},
                }
            )
            .sort([("marked_at", -1), ("date", -1), ("_id", -1)])
            .limit(10)
        )
        rows: list[AdminStudentRecentAttendance] = []
        async for doc in cursor:
            rows.append(
                AdminStudentRecentAttendance(
                    session_id=self._optional_str(doc.get("session_id")),
                    date=self._attendance_date_label(doc.get("date")),
                    status=str(doc.get("status") or "unknown"),
                    marked_at=self._coerce_datetime(doc.get("marked_at")),
                )
            )
        return rows

    @staticmethod
    def _attendance_date_label(value: object | None) -> str | None:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if value is None:
            return None
        text = str(value)
        return text[:10] if text else None

    @classmethod
    def _enrollment_session_amount_cents(
        cls,
        enrollment: dict[str, object],
        session: dict[str, object],
    ) -> int | None:
        enrollment_amount = cls._explicit_amount_cents(enrollment)
        if enrollment_amount is not None:
            return max(enrollment_amount, 0)
        session_amount = cls._explicit_amount_cents(session)
        if session_amount is not None:
            return max(session_amount, 0)
        return None

    @staticmethod
    def _optional_str(value: object | None) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text or None

    @classmethod
    def _explicit_amount_cents(cls, doc: dict[str, object]) -> int | None:
        return cls._cents_value(
            doc,
            (
                "final_amount_cents",
                "amount_cents",
                "gross_amount_cents",
                "monthly_price_cents",
                "price_cents",
            ),
            ("final_amount", "amount"),
        )

    @classmethod
    def _amount_cents(cls, doc: dict[str, object]) -> int:
        final_amount = cls._cents_value(doc, ("final_amount_cents",), ("final_amount",))
        if final_amount is not None:
            return max(final_amount, 0)
        amount = cls._cents_value(
            doc,
            ("amount_cents", "gross_amount_cents", "monthly_price_cents", "price_cents"),
            ("amount", "gross_amount", "monthly_price", "price"),
        )
        if amount is None:
            return 0
        return max(amount - cls._discount_cents(doc), 0)

    @classmethod
    def _paid_amount_cents(cls, doc: dict[str, object], amount_cents: int) -> int:
        for key in ("paid_amount_cents", "amount_received_cents"):
            if doc.get(key) is not None:
                return max(int(doc[key]), 0)
        if str(doc.get("status") or "") in {"paid", "succeeded"}:
            return max(amount_cents - cls._refunded_cents(doc), 0)
        return 0

    @staticmethod
    def _balance_due_cents(
        doc: dict[str, object],
        amount_cents: int,
        paid_amount_cents: int,
    ) -> int:
        if str(doc.get("status") or "") in {"paid", "succeeded"}:
            return 0
        if doc.get("balance_due_cents") is not None:
            return max(int(doc["balance_due_cents"]), 0)
        return max(amount_cents - paid_amount_cents, 0)

    @staticmethod
    def _cents_value(
        doc: dict[str, object],
        cents_keys: tuple[str, ...],
        decimal_keys: tuple[str, ...],
    ) -> int | None:
        for key in cents_keys:
            if doc.get(key) is not None:
                return int(doc[key])
        for key in decimal_keys:
            if doc.get(key) is not None:
                return round(float(doc[key]) * 100)  # type: ignore[arg-type]
        return None

    @classmethod
    def _discount_cents(cls, doc: dict[str, object]) -> int:
        return max(cls._cents_value(doc, ("discount_cents",), ("discount",)) or 0, 0)

    @classmethod
    def _refunded_cents(cls, doc: dict[str, object]) -> int:
        return max(cls._cents_value(doc, ("refunded_cents",), ("refunded",)) or 0, 0)

    @staticmethod
    def _coerce_datetime(value: object | None) -> datetime | None:
        if isinstance(value, datetime):
            return MongoStudentRepository._as_utc(value)
        if isinstance(value, str) and value:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return MongoStudentRepository._as_utc(parsed)
        return None

    async def _parent_info(self, academy_id: str, parent_id: str) -> dict[str, str | None]:
        if not parent_id:
            return {}
        or_filter: list[dict[str, object]] = [
            {"user_id": parent_id},
            {"firebase_uid": parent_id},
        ]
        if BsonObjectId.is_valid(parent_id):
            or_filter.append({"_id": BsonObjectId(parent_id)})
        user = await self._db["users"].find_one({"academy_id": academy_id, "$or": or_filter})
        if user is None:
            return {}
        return {
            "name": str(
                user.get("display_name")
                or f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                or ""
            )
            or None,
            "email": str(user.get("email")) if user.get("email") is not None else None,
            "phone": str(user.get("phone")) if user.get("phone") is not None else None,
        }

    async def _find_parent_for_change(
        self,
        academy_id: str,
        parent_id: str,
    ) -> dict[str, Any] | None:
        return await self._db["users"].find_one(
            {"academy_id": academy_id, **self._user_id_filter(parent_id)}
        )

    @staticmethod
    def _user_id_filter(user_id: str) -> dict[str, object]:
        ids: list[object] = [user_id]
        if BsonObjectId.is_valid(user_id):
            ids.append(BsonObjectId(user_id))
        return {
            "$or": [
                {"user_id": user_id},
                {"auth_uid": user_id},
                {"firebase_uid": user_id},
                {"_id": {"$in": ids}},
            ]
        }

    @staticmethod
    def _parent_is_active(user: dict[str, Any]) -> bool:
        status = str(user.get("status") or "active")
        return (
            status not in {"inactive", "disabled", "deleted"}
            and user.get("is_active", True) is not False
        )

    @staticmethod
    def _parent_has_parent_role(user: dict[str, Any]) -> bool:
        roles = user.get("roles")
        if isinstance(roles, str):
            normalized_roles = {roles}
        elif isinstance(roles, list | tuple | set):
            normalized_roles = {str(role) for role in roles}
        else:
            normalized_roles = set()
        role = user.get("role")
        if role is not None:
            normalized_roles.add(str(role))
        return "parent" in normalized_roles

    @staticmethod
    def _canonical_parent_id(user: dict[str, Any]) -> str:
        return str(
            user.get("user_id") or user.get("firebase_uid") or user.get("auth_uid") or user["_id"]
        )

    @staticmethod
    def _parent_display_name(user: dict[str, Any]) -> str | None:
        value = (
            str(
                user.get("display_name")
                or f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                or ""
            )
            or None
        )
        return value

    @staticmethod
    def _parent_lookup_ids_from_student(student: dict[str, Any]) -> list[str]:
        return list(
            dict.fromkeys(
                str(value)
                for value in (student.get("parent_id"), student.get("parent_user_id"))
                if value
            )
        )

    async def _parent_change_impact_counts(
        self,
        *,
        academy_id: str,
        student_id: str,
        old_parent_ids: list[str],
    ) -> dict[str, int]:
        if not old_parent_ids:
            return {"payments": 0, "waivers": 0, "credits": 0, "waitlist": 0}
        query = {
            "academy_id": academy_id,
            "student_id": student_id,
            "$or": [
                {"parent_id": {"$in": old_parent_ids}},
                {"parent_user_id": {"$in": old_parent_ids}},
            ],
        }
        return {
            "payments": await self._db["invoices"].count_documents(query),
            "waivers": await self._db["waiver_acceptances"].count_documents(query),
            "credits": await self._db["account_credit_ledger"].count_documents(query),
            "waitlist": await self._db["waitlist"].count_documents(query),
        }

    async def _write_audit(
        self,
        *,
        academy_id: str,
        actor_id: str,
        action: str,
        entity_id: str,
        reason: str,
        changed_keys: list[str],
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        from backend.v2.shared.ids import new_ulid

        def pick(doc: dict[str, Any]) -> dict[str, Any]:
            return {key: doc.get(key) for key in changed_keys}

        await self._db["audit_logs"].insert_one(
            {
                "audit_id": str(new_ulid()),
                "academy_id": academy_id,
                "actor_id": actor_id,
                "action": action,
                "entity_type": "student",
                "entity_id": entity_id,
                "reason": reason,
                "changed_keys": changed_keys,
                "before": pick(before),
                "after": pick(after),
                "created_at": datetime.now(UTC),
            }
        )

    async def _write_parent_change_audit(
        self,
        *,
        academy_id: str,
        actor_id: str,
        student_id: str,
        reason: str,
        old_parent_id: str | None,
        new_parent_id: str,
        impact_counts: dict[str, int],
        created_at: datetime,
    ) -> None:
        from backend.v2.shared.ids import new_ulid

        await self._db["audit_logs"].insert_one(
            {
                "audit_id": str(new_ulid()),
                "academy_id": academy_id,
                "actor_id": actor_id,
                "action": "student.parent_changed",
                "entity_type": "student",
                "entity_id": student_id,
                "reason": reason,
                "old_parent_id": old_parent_id,
                "new_parent_id": new_parent_id,
                "impact_counts": impact_counts,
                "created_at": created_at,
            }
        )

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
        invoice_cursor = self._db["invoices"].find(
            {
                "academy_id": academy_id,
                "student_id": {"$in": student_ids},
                "status": {"$in": ["open", "partially_paid", "draft"]},
                "balance_due_cents": {"$gt": 0},
                "is_deleted": {"$ne": True},
            }
        )
        invoice_keys: set[str] = set()
        async for doc in invoice_cursor:
            invoice_keys.update(
                str(value)
                for value in (
                    doc.get("invoice_id"),
                    doc.get("invoice_number"),
                    doc.get("stripe_invoice_id"),
                    doc.get("stripe_payment_intent_id"),
                )
                if value
            )
            student_id = str(doc.get("student_id") or "")
            if self._invoice_is_overdue(doc, now, cutoff):
                statuses[student_id] = "overdue"
            elif statuses.get(student_id) != "overdue":
                statuses[student_id] = "due"

        cursor = self._db["payments"].find(
            {
                "academy_id": academy_id,
                "student_id": {"$in": student_ids},
                "status": {"$in": ["pending", "failed", "expired"]},
                "is_deleted": {"$ne": True},
            }
        )
        async for doc in cursor:
            payment_keys = {
                str(value)
                for value in (
                    doc.get("invoice_id"),
                    doc.get("invoice_number"),
                    doc.get("payment_id"),
                    doc.get("stripe_invoice_id"),
                    doc.get("stripe_payment_intent_id"),
                )
                if value
            }
            if payment_keys & invoice_keys:
                continue
            student_id = str(doc.get("student_id") or "")
            if self._payment_is_overdue(doc, now, cutoff):
                statuses[student_id] = "overdue"
            elif statuses.get(student_id) != "overdue":
                statuses[student_id] = "due"
        return statuses

    @staticmethod
    def _invoice_is_overdue(
        doc: dict[str, object],
        now: datetime,
        cutoff: datetime,
    ) -> bool:
        due_at = doc.get("due_at") or doc.get("due_date")
        if isinstance(due_at, datetime):
            return MongoStudentRepository._as_utc(due_at) < now
        created_at = doc.get("created_at")
        return (
            isinstance(created_at, datetime) and MongoStudentRepository._as_utc(created_at) < cutoff
        )

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
