"""Mongo-backed admin waiver read model."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId as BsonObjectId

from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    AdminWaiverAcceptance,
    AdminWaiverData,
    AdminWaiverDocument,
    AdminWaiverStudent,
)
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoAdminWaiverRepository(TenantScopedRepository):
    """Loads raw admin waiver data from students, users, and waiver documents."""

    collection_name = "waiver_acceptances"

    async def load_admin_waiver_data(self) -> AdminWaiverData:
        academy_id = current_academy_id()
        waiver_docs = await self._waiver_documents(academy_id)
        active = waiver_docs[0] if waiver_docs else None
        version_info = self._version_info_by_id(waiver_docs)

        students = await self._student_docs(academy_id)
        parent_map = await self._parents_by_id(academy_id, students)
        acceptances = await self._latest_acceptance_by_student(academy_id, students, version_info)

        student_rows: list[AdminWaiverStudent] = []
        for doc in students:
            student_id = str(doc.get("student_id") or doc.get("_id"))
            parent_id = str(doc.get("parent_id") or doc.get("parent_user_id") or "")
            parent = parent_map.get(parent_id, {})
            student_rows.append(
                AdminWaiverStudent(
                    student_id=student_id,
                    full_name=self._student_name(doc),
                    parent_id=parent_id,
                    parent_name=parent.get("name"),
                    parent_email=parent.get("email"),
                )
            )

        return AdminWaiverData(
            active_waiver=active,
            students=student_rows,
            acceptances_by_student=acceptances,
        )

    async def list_admin_waivers(self) -> AdminWaiverData:
        """Backward-compatible adapter for older local callers."""
        return await self.load_admin_waiver_data()

    async def _waiver_documents(self, academy_id: str) -> list[AdminWaiverDocument]:
        docs: list[dict[str, Any]] = [
            doc async for doc in self._db["waivers"].find({"academy_id": academy_id})
        ]
        if not docs:
            docs = [
                doc
                async for doc in self._db["waiver_versions"].find(
                    {"academy_id": academy_id, "is_active": {"$ne": False}}
                )
            ]
        if not docs:
            docs = [
                doc
                async for doc in self._db["waiver_versions"].find(
                    {"academy_id": {"$exists": False}, "is_active": {"$ne": False}}
                )
            ]

        waivers = [
            AdminWaiverDocument(
                waiver_id=str(doc.get("waiver_id") or doc.get("_id")),
                version=str(doc.get("version") or ""),
                content_hash=str(doc.get("content_hash") or doc.get("waiver_text_hash") or "")
                or None,
                effective_from=self._as_datetime(
                    doc.get("effective_from")
                    or doc.get("effective_at")
                    or doc.get("effective_date")
                    or doc.get("created_at")
                ),
            )
            for doc in docs
        ]
        return sorted(
            waivers,
            key=lambda waiver: waiver.effective_from or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

    async def _student_docs(self, academy_id: str) -> list[dict[str, Any]]:
        cursor = self._db["students"].find(
            {
                "academy_id": academy_id,
                "is_deleted": {"$ne": True},
                "$or": [
                    {"status": "active"},
                    {"status": None},
                    {"status": {"$exists": False}},
                ],
            }
        )
        return sorted(
            [doc async for doc in cursor],
            key=lambda doc: (
                self._student_name(doc).lower(),
                str(doc.get("student_id") or doc.get("_id")),
            ),
        )

    async def _parents_by_id(
        self,
        academy_id: str,
        students: list[dict[str, Any]],
    ) -> dict[str, dict[str, str | None]]:
        parent_ids = list(
            {
                str(doc.get("parent_id") or doc.get("parent_user_id") or "")
                for doc in students
                if doc.get("parent_id") or doc.get("parent_user_id")
            }
        )
        if not parent_ids:
            return {}
        oid_ids = [
            BsonObjectId(parent_id) for parent_id in parent_ids if BsonObjectId.is_valid(parent_id)
        ]
        or_filter: list[dict[str, object]] = [
            {"user_id": {"$in": parent_ids}},
            {"firebase_uid": {"$in": parent_ids}},
        ]
        if oid_ids:
            or_filter.append({"_id": {"$in": oid_ids}})
        out: dict[str, dict[str, str | None]] = {}
        cursor = self._db["users"].find({"academy_id": academy_id, "$or": or_filter})
        async for user in cursor:
            name = (
                str(
                    user.get("display_name")
                    or f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                    or ""
                )
                or None
            )
            email = str(user.get("email") or "") or None
            for key in (
                str(user.get("user_id") or ""),
                str(user.get("firebase_uid") or ""),
                str(user.get("_id") or ""),
            ):
                if key:
                    out[key] = {"name": name, "email": email}
        return out

    @staticmethod
    def _version_info_by_id(
        waiver_docs: list[AdminWaiverDocument],
    ) -> dict[str, tuple[str | None, str | None]]:
        return {
            doc.waiver_id: (doc.version, doc.content_hash) for doc in waiver_docs if doc.waiver_id
        }

    async def _latest_acceptance_by_student(
        self,
        academy_id: str,
        students: list[dict[str, Any]],
        version_info: dict[str, tuple[str | None, str | None]],
    ) -> dict[str, AdminWaiverAcceptance]:
        student_ids = [str(doc.get("student_id") or doc.get("_id")) for doc in students]
        out: dict[str, AdminWaiverAcceptance] = {}
        if not student_ids:
            return out

        docs = [
            doc
            async for doc in self._db["waiver_acceptances"].find(
                {
                    "student_id": {"$in": student_ids},
                    "is_deleted": {"$ne": True},
                    "$or": [
                        {"academy_id": academy_id},
                        {"academy_id": {"$exists": False}},
                        {"academy_id": None},
                    ],
                }
            )
        ]
        docs.sort(
            key=lambda doc: (
                self._as_datetime(doc.get("accepted_at")) or datetime.min.replace(tzinfo=UTC)
            ),
            reverse=True,
        )
        for doc in docs:
            student_id = str(doc.get("student_id") or "")
            if student_id and student_id not in out:
                out[student_id] = self._to_acceptance(doc, version_info)

        for doc in students:
            student_id = str(doc.get("student_id") or doc.get("_id"))
            if student_id in out or doc.get("waiver_accepted") is not True:
                continue
            out[student_id] = AdminWaiverAcceptance(
                student_id=student_id,
                parent_id=str(doc.get("parent_id") or doc.get("parent_user_id") or ""),
                accepted_by_user_id=(
                    str(doc.get("waiver_accepted_by")) if doc.get("waiver_accepted_by") else None
                ),
                waiver_version=str(doc.get("waiver_version") or "") or None,
                content_hash=str(doc.get("waiver_text_hash") or doc.get("content_hash") or "")
                or None,
                accepted_at=self._as_datetime(
                    doc.get("waiver_accepted_at") or doc.get("waiver_date")
                ),
            )
        return out

    def _to_acceptance(
        self,
        doc: dict[str, Any],
        version_info: dict[str, tuple[str | None, str | None]],
    ) -> AdminWaiverAcceptance:
        waiver_version_id = str(doc.get("waiver_version_id") or "")
        version, content_hash = version_info.get(waiver_version_id, (None, None))
        return AdminWaiverAcceptance(
            student_id=str(doc.get("student_id") or ""),
            parent_id=str(doc.get("parent_id") or doc.get("parent_user_id") or ""),
            accepted_by_user_id=(
                str(doc.get("accepted_by_user_id")) if doc.get("accepted_by_user_id") else None
            ),
            waiver_version=str(doc.get("waiver_version") or doc.get("version") or version or "")
            or None,
            content_hash=str(
                doc.get("content_hash") or doc.get("waiver_text_hash") or content_hash or ""
            )
            or None,
            accepted_at=self._as_datetime(doc.get("accepted_at")),
        )

    @staticmethod
    def _student_name(doc: dict[str, Any]) -> str:
        first = str(doc.get("first_name") or "").strip()
        last = str(doc.get("last_name") or "").strip()
        return " ".join(
            str(doc.get("full_name") or f"{first} {last}".strip() or "Unnamed student").split()
        )

    @staticmethod
    def _as_datetime(value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                return None
        return None
