"""Mongo-backed admin waiver read model."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId as BsonObjectId

from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    AdminWaiverAcceptance,
    AdminWaiverData,
    AdminWaiverDocument,
    AdminWaiverSignatureDetail,
    AdminWaiverStudent,
    AdminWaiverTemplateDetail,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_parent_waiver_repo import (
    student_ids_with_live_enrollment,
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

    async def get_template_detail(self, waiver_id: str) -> AdminWaiverTemplateDetail | None:
        academy_id = current_academy_id()
        doc = await self._template_doc(academy_id, waiver_id)
        if doc is None:
            return None
        title = str(doc.get("name") or doc.get("title") or doc.get("version") or "Waiver")
        return AdminWaiverTemplateDetail(
            waiver_id=str(doc.get("waiver_template_id") or doc.get("waiver_id") or doc.get("_id")),
            title=title,
            version=str(doc.get("version") or ""),
            status=self._template_status(doc),
            body=str(doc.get("body") or doc.get("text") or doc.get("waiver_text") or "") or None,
            content_hash=str(doc.get("content_hash") or doc.get("waiver_text_hash") or "") or None,
            effective_from=self._as_datetime(
                doc.get("effective_from")
                or doc.get("effective_at")
                or doc.get("effective_date")
                or doc.get("published_at")
                or doc.get("assigned_at")
                or doc.get("updated_at")
                or doc.get("created_at")
            ),
            assigned_to_registration=bool(doc.get("assigned_to_registration") or False),
            assigned_at=self._as_datetime(doc.get("assigned_at")),
        )

    async def get_signature_detail(self, signature_id: str) -> AdminWaiverSignatureDetail | None:
        academy_id = current_academy_id()
        detail = await self._signature_detail_from_signature(academy_id, signature_id)
        if detail is not None:
            return detail
        detail = await self._signature_detail_from_acceptance(academy_id, signature_id)
        if detail is not None:
            return detail
        if signature_id.startswith("student:"):
            return await self._signature_detail_from_student(
                academy_id,
                signature_id.removeprefix("student:"),
            )
        return None

    async def _waiver_documents(self, academy_id: str) -> list[AdminWaiverDocument]:
        docs: list[dict[str, Any]] = [
            doc async for doc in self._db["waiver_templates"].find({"academy_id": academy_id})
        ]
        if not docs:
            docs = [doc async for doc in self._db["waivers"].find({"academy_id": academy_id})]
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
                waiver_id=str(
                    doc.get("waiver_template_id") or doc.get("waiver_id") or doc.get("_id")
                ),
                version=str(doc.get("version") or ""),
                title=str(doc.get("name") or doc.get("title") or "") or None,
                body=str(doc.get("body") or doc.get("text") or doc.get("waiver_text") or "")
                or None,
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
        docs = [doc async for doc in cursor]
        # issue #651: mirror the parent waiver prompt — only students with an
        # active-or-paused enrollment owe a waiver, so the admin report must
        # not list withdrawn / cancelled children as "pending signature".
        live = await student_ids_with_live_enrollment(
            self._db,
            academy_id,
            [str(doc.get("student_id") or doc.get("_id")) for doc in docs],
        )
        docs = [doc for doc in docs if str(doc.get("student_id") or doc.get("_id")) in live]
        return sorted(
            docs,
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

        signature_docs = [
            doc
            async for doc in self._db["waiver_signatures"].find(
                {
                    "academy_id": academy_id,
                    "student_id": {"$in": student_ids},
                    "is_deleted": {"$ne": True},
                }
            )
        ]
        signature_docs.sort(
            key=lambda doc: (
                self._as_datetime(doc.get("signed_at")) or datetime.min.replace(tzinfo=UTC)
            ),
            reverse=True,
        )
        share_links_by_artifact = await self._share_links_by_artifact(academy_id, signature_docs)
        for doc in signature_docs:
            student_id = str(doc.get("student_id") or "")
            if student_id and student_id not in out:
                out[student_id] = self._to_signature_acceptance(
                    doc,
                    version_info,
                    share_links_by_artifact,
                )

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
                signature_id=f"student:{student_id}",
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

    async def _share_links_by_artifact(
        self,
        academy_id: str,
        signature_docs: list[dict[str, Any]],
    ) -> dict[str, str]:
        artifact_ids = sorted(
            {str(doc.get("artifact_id") or "") for doc in signature_docs if doc.get("artifact_id")}
        )
        if not artifact_ids:
            return {}
        out: dict[str, str] = {}
        cursor = self._db["waiver_share_links"].find(
            {
                "academy_id": academy_id,
                "artifact_id": {"$in": artifact_ids},
                "status": "active",
            }
        )
        async for doc in cursor:
            artifact_id = str(doc.get("artifact_id") or "")
            share_link_id = str(doc.get("share_link_id") or "")
            if artifact_id and share_link_id:
                out[artifact_id] = share_link_id
        return out

    async def _template_doc(self, academy_id: str, waiver_id: str) -> dict[str, Any] | None:
        filters = self._id_filters(waiver_id, "waiver_template_id", "waiver_id")
        for collection in ("waiver_templates", "waivers", "waiver_versions"):
            doc = await self._db[collection].find_one(
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
            if doc is not None:
                return doc
        return None

    async def _signature_detail_from_signature(
        self, academy_id: str, signature_id: str
    ) -> AdminWaiverSignatureDetail | None:
        doc = await self._db["waiver_signatures"].find_one(
            {"waiver_signature_id": signature_id, "academy_id": academy_id}
        )
        if doc is None:
            return None
        template_id = str(doc.get("waiver_template_id") or "") or None
        template = await self._template_doc(academy_id, template_id) if template_id else None
        return await self._signature_detail(
            academy_id=academy_id,
            signature_id=str(doc.get("waiver_signature_id")),
            student_id=str(doc.get("student_id") or ""),
            parent_id=str(doc.get("parent_user_id") or ""),
            signed_at=self._as_datetime(doc.get("signed_at")),
            signer_name=str(doc.get("signer_name") or "") or None,
            signer_email=str(doc.get("signer_email") or "") or None,
            waiver_template_id=template_id,
            waiver_title=(
                str(template.get("name") or template.get("title") or "") if template else None
            )
            or None,
            waiver_version=str(template.get("version") or "") if template else None,
            content_hash=str(doc.get("content_hash") or "") or None,
            artifact_id=str(doc.get("artifact_id") or "") or None,
        )

    async def _signature_detail_from_acceptance(
        self, academy_id: str, signature_id: str
    ) -> AdminWaiverSignatureDetail | None:
        doc = await self._db["waiver_acceptances"].find_one(
            {
                "$and": [
                    {
                        "$or": [
                            {"academy_id": academy_id},
                            {"academy_id": {"$exists": False}},
                            {"academy_id": None},
                        ]
                    },
                    {"$or": self._id_filters(signature_id, "waiver_acceptance_id")},
                ]
            }
        )
        if doc is None:
            return None
        template_id = (
            str(doc.get("waiver_version_id") or doc.get("waiver_template_id") or "") or None
        )
        template = await self._template_doc(academy_id, template_id) if template_id else None
        return await self._signature_detail(
            academy_id=academy_id,
            signature_id=str(doc.get("waiver_acceptance_id") or doc.get("_id")),
            student_id=str(doc.get("student_id") or ""),
            parent_id=str(doc.get("parent_id") or doc.get("parent_user_id") or ""),
            signed_at=self._as_datetime(doc.get("accepted_at")),
            signer_name=str(doc.get("signer_name") or "") or None,
            signer_email=str(doc.get("signer_email") or "") or None,
            waiver_template_id=template_id,
            waiver_title=(
                str(template.get("name") or template.get("title") or "") if template else None
            )
            or None,
            waiver_version=str(
                doc.get("waiver_version")
                or doc.get("version")
                or (template.get("version") if template else "")
                or ""
            )
            or None,
            content_hash=str(doc.get("content_hash") or doc.get("waiver_text_hash") or "") or None,
            artifact_id=str(doc.get("artifact_id") or "") or None,
        )

    async def _signature_detail_from_student(
        self, academy_id: str, student_id: str
    ) -> AdminWaiverSignatureDetail | None:
        student = await self._db["students"].find_one(
            {"academy_id": academy_id, "student_id": student_id, "waiver_accepted": True}
        )
        if student is None and BsonObjectId.is_valid(student_id):
            student = await self._db["students"].find_one(
                {"academy_id": academy_id, "_id": BsonObjectId(student_id), "waiver_accepted": True}
            )
        if student is None:
            return None
        return await self._signature_detail(
            academy_id=academy_id,
            signature_id=f"student:{student_id}",
            student_id=student_id,
            parent_id=str(student.get("parent_id") or student.get("parent_user_id") or ""),
            signed_at=self._as_datetime(
                student.get("waiver_accepted_at") or student.get("waiver_date")
            ),
            signer_name=None,
            signer_email=None,
            waiver_template_id=None,
            waiver_title=None,
            waiver_version=str(student.get("waiver_version") or "") or None,
            content_hash=str(student.get("waiver_text_hash") or student.get("content_hash") or "")
            or None,
            artifact_id=None,
        )

    async def _signature_detail(
        self,
        *,
        academy_id: str,
        signature_id: str,
        student_id: str,
        parent_id: str,
        signed_at: datetime | None,
        signer_name: str | None,
        signer_email: str | None,
        waiver_template_id: str | None,
        waiver_title: str | None,
        waiver_version: str | None,
        content_hash: str | None,
        artifact_id: str | None,
    ) -> AdminWaiverSignatureDetail | None:
        if signed_at is None:
            return None
        student = await self._student_by_id(academy_id, student_id)
        parent_map = await self._parents_by_id(academy_id, [{"parent_id": parent_id}])
        parent = parent_map.get(parent_id, {})
        artifact_status, share_status, share_link_id, gap_note = await self._artifact_state(
            academy_id=academy_id,
            artifact_id=artifact_id,
            signature_id=signature_id,
        )
        return AdminWaiverSignatureDetail(
            signature_id=signature_id,
            student_id=student_id,
            student_name=self._student_name(student) if student else "Unknown student",
            parent_id=parent_id,
            parent_name=parent.get("name"),
            parent_email=parent.get("email"),
            signed_at=signed_at,
            signer_name=signer_name,
            signer_email=signer_email,
            waiver_template_id=waiver_template_id,
            waiver_title=waiver_title,
            waiver_version=waiver_version,
            content_hash=content_hash,
            artifact_id=artifact_id,
            share_link_id=share_link_id,
            artifact_status=artifact_status,
            share_status=share_status,
            gap_note=gap_note,
        )

    async def _artifact_state(
        self,
        *,
        academy_id: str,
        artifact_id: str | None,
        signature_id: str,
    ) -> tuple[str, str, str | None, str]:
        if not artifact_id:
            return (
                "unavailable",
                "unavailable",
                None,
                "Signed waiver artifact/share links are not implemented yet.",
            )
        artifact = await self._db["waiver_artifacts"].find_one(
            {
                "academy_id": academy_id,
                "artifact_id": artifact_id,
                "signature_id": signature_id,
            }
        )
        artifact_status = (
            str(artifact.get("status") or "stored") if artifact else "stored_reference"
        )
        share = await self._db["waiver_share_links"].find_one(
            {
                "academy_id": academy_id,
                "artifact_id": artifact_id,
                "signature_id": signature_id,
                "status": "active",
            }
        )
        share_status = "available" if share else "unavailable"
        share_link_id = str(share.get("share_link_id") or "") if share else None
        if artifact and share:
            gap_note = (
                "Signed waiver artifact metadata is stored and an authorized share link is active."
            )
        elif artifact:
            gap_note = (
                "Signed waiver artifact metadata is stored; no active share link is available."
            )
        else:
            gap_note = (
                "Signed waiver has an artifact reference, but stored artifact metadata is missing."
            )
        return artifact_status, share_status, share_link_id or None, gap_note

    async def _student_by_id(self, academy_id: str, student_id: str) -> dict[str, Any] | None:
        doc = await self._db["students"].find_one(
            {"academy_id": academy_id, "student_id": student_id}
        )
        if doc is None and BsonObjectId.is_valid(student_id):
            doc = await self._db["students"].find_one(
                {"academy_id": academy_id, "_id": BsonObjectId(student_id)}
            )
        return doc

    @staticmethod
    def _id_filters(value: str, *field_names: str) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = [{field: value} for field in field_names]
        if BsonObjectId.is_valid(value):
            filters.append({"_id": BsonObjectId(value)})
        return filters

    @staticmethod
    def _template_status(doc: dict[str, Any]) -> str:
        status = str(doc.get("status") or "active")
        if status == "published":
            return "active"
        return status

    def _to_acceptance(
        self,
        doc: dict[str, Any],
        version_info: dict[str, tuple[str | None, str | None]],
    ) -> AdminWaiverAcceptance:
        waiver_version_id = str(doc.get("waiver_version_id") or "")
        version, content_hash = version_info.get(waiver_version_id, (None, None))
        return AdminWaiverAcceptance(
            signature_id=str(doc.get("waiver_acceptance_id") or doc.get("_id")),
            student_id=str(doc.get("student_id") or ""),
            parent_id=str(doc.get("parent_id") or doc.get("parent_user_id") or ""),
            accepted_by_user_id=(
                str(doc.get("accepted_by_user_id")) if doc.get("accepted_by_user_id") else None
            ),
            waiver_template_id=waiver_version_id or None,
            waiver_version=str(doc.get("waiver_version") or doc.get("version") or version or "")
            or None,
            content_hash=str(
                doc.get("content_hash") or doc.get("waiver_text_hash") or content_hash or ""
            )
            or None,
            accepted_at=self._as_datetime(doc.get("accepted_at")),
            signer_name=str(doc.get("signer_name") or "") or None,
            signer_email=str(doc.get("signer_email") or "") or None,
            artifact_id=str(doc.get("artifact_id") or "") or None,
        )

    def _to_signature_acceptance(
        self,
        doc: dict[str, Any],
        version_info: dict[str, tuple[str | None, str | None]],
        share_links_by_artifact: dict[str, str],
    ) -> AdminWaiverAcceptance:
        template_id = str(doc.get("waiver_template_id") or "")
        version, template_hash = version_info.get(template_id, (None, None))
        artifact_id = str(doc.get("artifact_id") or "") or None
        return AdminWaiverAcceptance(
            signature_id=str(doc.get("waiver_signature_id") or doc.get("_id")),
            student_id=str(doc.get("student_id") or ""),
            parent_id=str(doc.get("parent_user_id") or ""),
            accepted_by_user_id=str(doc.get("parent_user_id") or "") or None,
            waiver_template_id=template_id or None,
            waiver_version=version,
            content_hash=str(doc.get("content_hash") or template_hash or "") or None,
            accepted_at=self._as_datetime(doc.get("signed_at")),
            signer_name=str(doc.get("signer_name") or "") or None,
            signer_email=str(doc.get("signer_email") or "") or None,
            artifact_id=artifact_id,
            share_link_id=share_links_by_artifact.get(artifact_id or ""),
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
