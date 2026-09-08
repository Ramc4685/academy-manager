"""Mongo-backed parent waiver repository."""

from __future__ import annotations

from datetime import UTC, datetime
from secrets import token_urlsafe
from typing import Any

from bson import ObjectId as BsonObjectId

from backend.v2.contexts.onboarding.application.use_cases.parent_student_waivers import (
    ParentWaiverSignature,
    ParentWaiverStudent,
)
from backend.v2.contexts.onboarding.domain.models import WaiverSignature
from backend.v2.contexts.onboarding.infrastructure.mongo_waiver_template_repo import (
    MongoWaiverTemplateRepository,
)
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id

LIVE_ENROLLMENT_STATUSES: tuple[str, ...] = ("active", "paused")


async def student_ids_with_live_enrollment(
    db: Any, academy_id: str, student_ids: list[str]
) -> set[str]:
    """Return the subset of ``student_ids`` holding an active-or-paused enrollment.

    issue #651 invariant: waiver obligations follow live enrollments. A student
    whose every enrollment is cancelled / withdrawn owes no signature, while a
    paused student (still on the roster, issue #641) does. Shared by the parent
    waiver prompt and the admin waiver report so the two can never disagree.
    """
    if not student_ids:
        return set()
    cursor = db["enrollments"].find(
        {
            "academy_id": academy_id,
            "student_id": {"$in": student_ids},
            "status": {"$in": list(LIVE_ENROLLMENT_STATUSES)},
        },
        {"student_id": 1},
    )
    return {str(doc.get("student_id")) async for doc in cursor}


class MongoParentWaiverRepository(TenantScopedRepository):
    collection_name = "waiver_signatures"

    @staticmethod
    def _as_datetime(value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                return None
        return None

    async def get_required_template(self):
        academy_id = current_academy_id()
        cursor = self._db["waiver_templates"].find(
            {
                "academy_id": academy_id,
                "status": "active",
                "assigned_to_registration": True,
            },
            sort=[("assigned_at", -1), ("effective_from", -1)],
            limit=1,
        )
        async for doc in cursor:
            return MongoWaiverTemplateRepository._to_record(doc)
        return None

    async def list_active_students_for_parent(self, parent_id: str) -> list[ParentWaiverStudent]:
        # Split $or into two indexed queries — parent_user_id has no compound index,
        # so a single $or causes a collection scan on cold loads.
        academy_id = current_academy_id()
        base_filter = {"academy_id": academy_id, "is_deleted": {"$ne": True}, "status": "active"}
        docs_a = [
            doc
            async for doc in self._db["students"].find(
                {**base_filter, "parent_id": parent_id}, sort=[("full_name", 1)]
            )
        ]
        docs_b = [
            doc
            async for doc in self._db["students"].find(
                {**base_filter, "parent_user_id": parent_id}, sort=[("full_name", 1)]
            )
        ]
        seen: set[str] = set()
        merged: list[Any] = []
        for doc in docs_a + docs_b:
            k = str(doc.get("_id"))
            if k not in seen:
                seen.add(k)
                merged.append(doc)
        # issue #651: a waiver is only owed for a child who still attends.
        # Withdrawn / cancelled families were still being nagged to sign, so
        # keep only students with at least one active-or-paused enrollment
        # (the same join `MongoStudentRepository.has_active_enrollment` uses).
        merged = await self._with_live_enrollment(academy_id, merged)
        return [
            ParentWaiverStudent(
                student_id=str(doc.get("student_id") or doc.get("_id")),
                student_name=self._student_name(doc),
            )
            for doc in merged
        ]

    async def _with_live_enrollment(self, academy_id: str, student_docs: list[Any]) -> list[Any]:
        live = await student_ids_with_live_enrollment(
            self._db,
            academy_id,
            [str(doc.get("student_id") or doc.get("_id")) for doc in student_docs],
        )
        return [doc for doc in student_docs if str(doc.get("student_id") or doc.get("_id")) in live]

    async def latest_signatures_for_students(
        self, student_ids: list[str]
    ) -> dict[str, ParentWaiverSignature]:
        if not student_ids:
            return {}
        academy_id = current_academy_id()
        out: dict[str, ParentWaiverSignature] = {}
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
        for doc in signature_docs:
            student_id = str(doc.get("student_id") or "")
            if student_id and student_id not in out:
                out[student_id] = ParentWaiverSignature(
                    student_id=student_id,
                    waiver_template_id=str(doc.get("waiver_template_id") or "") or None,
                    content_hash=str(doc.get("content_hash") or "") or None,
                    signed_at=self._as_datetime(doc.get("signed_at")),
                )

        legacy_docs = [
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
        legacy_docs.sort(
            key=lambda doc: (
                self._as_datetime(doc.get("accepted_at")) or datetime.min.replace(tzinfo=UTC)
            ),
            reverse=True,
        )
        for doc in legacy_docs:
            student_id = str(doc.get("student_id") or "")
            if student_id and student_id not in out:
                out[student_id] = ParentWaiverSignature(
                    student_id=student_id,
                    waiver_template_id=str(doc.get("waiver_template_id") or "") or None,
                    waiver_version=str(doc.get("waiver_version") or "") or None,
                    content_hash=str(doc.get("content_hash") or doc.get("waiver_text_hash") or "")
                    or None,
                    signed_at=self._as_datetime(doc.get("accepted_at")),
                )
        return out

    async def save_signature(self, signature: WaiverSignature) -> None:
        artifact_id = signature.artifact_id or f"wa_{signature.waiver_signature_id}"
        now = datetime.now(UTC)
        template = await self._template_doc(signature.waiver_template_id)
        await self._store_artifact(
            signature=signature,
            artifact_id=artifact_id,
            template=template,
            now=now,
        )
        await self._ensure_share_link(
            signature=signature,
            artifact_id=artifact_id,
            now=now,
        )
        await self._update_one(
            {"waiver_signature_id": signature.waiver_signature_id},
            {
                "$set": {
                    "waiver_signature_id": signature.waiver_signature_id,
                    "waiver_template_id": signature.waiver_template_id,
                    "student_id": signature.student_id,
                    "parent_user_id": signature.parent_user_id,
                    "signed_at": signature.signed_at,
                    "signer_name": signature.signer_name,
                    "signer_email": str(signature.signer_email),
                    "content_hash": signature.content_hash,
                    "ip_address": signature.ip_address,
                    "user_agent": signature.user_agent,
                    "artifact_id": artifact_id,
                    "expires_at": signature.expires_at,
                }
            },
            upsert=True,
        )

    async def _template_doc(self, waiver_template_id: str) -> dict[str, Any] | None:
        filters: list[dict[str, Any]] = [{"waiver_template_id": waiver_template_id}]
        if BsonObjectId.is_valid(waiver_template_id):
            filters.append({"_id": BsonObjectId(waiver_template_id)})
        return await self._db["waiver_templates"].find_one(
            {"academy_id": current_academy_id(), "$or": filters}
        )

    async def _store_artifact(
        self,
        *,
        signature: WaiverSignature,
        artifact_id: str,
        template: dict[str, Any] | None,
        now: datetime,
    ) -> None:
        await self._db["waiver_artifacts"].update_one(
            {"academy_id": current_academy_id(), "artifact_id": artifact_id},
            {
                "$setOnInsert": {"created_at": now},
                "$set": {
                    "artifact_id": artifact_id,
                    "artifact_type": "signed_waiver",
                    "status": "stored",
                    "signature_id": signature.waiver_signature_id,
                    "waiver_template_id": signature.waiver_template_id,
                    "student_id": signature.student_id,
                    "parent_user_id": signature.parent_user_id,
                    "signed_at": signature.signed_at,
                    "signer_name": signature.signer_name,
                    "signer_email": str(signature.signer_email),
                    "template_title": (
                        str(template.get("name") or template.get("title") or "")
                        if template
                        else None
                    ),
                    "template_version": (str(template.get("version") or "") if template else None),
                    "content_hash": signature.content_hash,
                    "body": (
                        str(template.get("body") or template.get("text") or "")
                        if template
                        else None
                    ),
                    "updated_at": now,
                },
            },
            upsert=True,
        )

    async def _ensure_share_link(
        self,
        *,
        signature: WaiverSignature,
        artifact_id: str,
        now: datetime,
    ) -> None:
        existing = await self._db["waiver_share_links"].find_one(
            {
                "academy_id": current_academy_id(),
                "artifact_id": artifact_id,
                "status": "active",
            },
            {"_id": 1},
        )
        if existing is not None:
            return
        await self._db["waiver_share_links"].insert_one(
            {
                "academy_id": current_academy_id(),
                "share_link_id": f"wsl_{token_urlsafe(24)}",
                "artifact_id": artifact_id,
                "signature_id": signature.waiver_signature_id,
                "student_id": signature.student_id,
                "parent_user_id": signature.parent_user_id,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
        )

    @staticmethod
    def _student_name(doc: dict[str, Any]) -> str:
        first = str(doc.get("first_name") or "").strip()
        last = str(doc.get("last_name") or "").strip()
        return str(doc.get("full_name") or f"{first} {last}".strip() or "Unnamed student")
