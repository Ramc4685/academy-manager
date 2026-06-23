"""Mongo-backed WaiverTemplate repository.

Templates are immutable once active. This repo only supports ``get`` (by id)
and ``get_active`` (most-recent active template, if any). Publishing /
superseding flows belong in a dedicated admin use case which is not part of
this Wave 4 prep slice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId as BsonObjectId

from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    AdminWaiverTemplateRecord,
)
from backend.v2.contexts.onboarding.domain.models import WaiverTemplate
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoWaiverTemplateRepository(TenantScopedRepository):
    collection_name = "waiver_templates"

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

    @classmethod
    def _to_domain(cls, doc: dict[str, Any]) -> WaiverTemplate:
        effective_from = cls._as_datetime(
            doc.get("effective_from")
            or doc.get("published_at")
            or doc.get("assigned_at")
            or doc.get("updated_at")
            or doc.get("created_at")
        )
        if effective_from is None:
            raise ValueError(
                f"waiver_templates row {doc.get('waiver_template_id')!r} is missing effective_from"
            )
        return WaiverTemplate(
            waiver_template_id=str(doc.get("waiver_template_id") or doc.get("_id")),
            academy_id=str(doc["academy_id"]),
            name=str(doc.get("name") or ""),
            version=str(doc["version"]),
            content_hash=str(doc["content_hash"]),
            body=str(doc.get("body") or ""),
            effective_from=effective_from,
            expires_at=cls._as_datetime(doc.get("expires_at")),
            status=cls._template_status(doc),
        )

    @classmethod
    def _to_record(cls, doc: dict[str, Any]) -> AdminWaiverTemplateRecord:
        updated_at = cls._as_datetime(doc.get("updated_at") or doc.get("created_at"))
        if updated_at is None:
            updated_at = datetime.now(UTC)
        return AdminWaiverTemplateRecord(
            waiver_template_id=str(doc.get("waiver_template_id") or doc.get("_id")),
            title=str(doc.get("name") or doc.get("title") or ""),
            body=str(doc.get("body") or doc.get("text") or doc.get("waiver_text") or ""),
            status=cls._template_status(doc),
            version=(str(doc["version"]) if doc.get("version") is not None else None),
            content_hash=(
                str(doc["content_hash"]) if doc.get("content_hash") is not None else None
            ),
            effective_from=cls._as_datetime(
                doc.get("effective_from")
                or doc.get("published_at")
                or doc.get("assigned_at")
                or doc.get("updated_at")
                or doc.get("created_at")
            ),
            published_at=cls._as_datetime(doc.get("published_at")),
            assigned_to_registration=bool(doc.get("assigned_to_registration") or False),
            assigned_at=cls._as_datetime(doc.get("assigned_at")),
            updated_at=updated_at,
        )

    @staticmethod
    def _template_status(doc: dict[str, Any]) -> str:
        status = str(doc.get("status") or "active")
        if status == "published":
            return "active"
        return status

    @staticmethod
    def _id_filter(waiver_template_id: str) -> dict[str, Any]:
        filters: list[dict[str, Any]] = [{"waiver_template_id": waiver_template_id}]
        if BsonObjectId.is_valid(waiver_template_id):
            filters.append({"_id": BsonObjectId(waiver_template_id)})
        return {"$or": filters}

    @staticmethod
    def _to_draft_document(template: AdminWaiverTemplateRecord) -> dict[str, Any]:
        return {
            "waiver_template_id": template.waiver_template_id,
            "name": template.title,
            "body": template.body,
            "status": template.status,
            "version": template.version,
            "content_hash": template.content_hash,
            "effective_from": template.effective_from,
            "published_at": template.published_at,
            "assigned_to_registration": template.assigned_to_registration,
            "assigned_at": template.assigned_at,
            "updated_at": template.updated_at,
        }

    async def get(self, waiver_template_id: str) -> WaiverTemplate | None:
        doc = await self._find_one(self._id_filter(waiver_template_id))
        return self._to_domain(doc) if doc else None

    async def get_active(self) -> WaiverTemplate | None:
        cursor = self._find_many(
            {"status": "active"},
            sort=[("effective_from", -1)],
            limit=1,
        )
        async for doc in cursor:
            return self._to_domain(doc)
        return None

    async def get_registration_template(self) -> AdminWaiverTemplateRecord | None:
        cursor = self._find_many(
            {"status": {"$in": ["active", "published"]}, "assigned_to_registration": True},
            sort=[("assigned_at", -1), ("effective_from", -1)],
            limit=1,
        )
        async for doc in cursor:
            return self._to_record(doc)
        return None

    async def list_templates(self) -> list[AdminWaiverTemplateRecord]:
        cursor = self._find_many(sort=[("updated_at", -1)])
        return [self._to_record(doc) async for doc in cursor]

    async def create_draft(self, template: AdminWaiverTemplateRecord) -> AdminWaiverTemplateRecord:
        await self._insert_one(self._to_draft_document(template))
        stored = await self.get_template(template.waiver_template_id)
        if stored is None:
            raise RuntimeError("Failed to store waiver template draft")
        return stored

    async def get_template(self, waiver_template_id: str) -> AdminWaiverTemplateRecord | None:
        doc = await self._find_one(self._id_filter(waiver_template_id))
        return self._to_record(doc) if doc else None

    async def publish_draft(
        self,
        *,
        waiver_template_id: str,
        version: str,
        content_hash: str,
        published_at: datetime,
    ) -> AdminWaiverTemplateRecord:
        academy_id = current_academy_id()
        await self.collection.update_many(
            {
                "academy_id": academy_id,
                "status": {"$in": ["active", "published"]},
                "waiver_template_id": {"$ne": waiver_template_id},
            },
            {"$set": {"status": "superseded", "updated_at": published_at}},
        )
        await self._update_one(
            {**self._id_filter(waiver_template_id), "status": "draft"},
            {
                "$set": {
                    "status": "active",
                    "version": version,
                    "content_hash": content_hash,
                    "effective_from": published_at,
                    "published_at": published_at,
                    "updated_at": published_at,
                }
            },
        )
        published = await self.get_template(waiver_template_id)
        if published is None:
            raise RuntimeError("Failed to publish waiver template draft")
        return published

    async def assign_to_registration(
        self,
        *,
        waiver_template_id: str,
        assigned_at: datetime,
    ) -> AdminWaiverTemplateRecord:
        academy_id = current_academy_id()
        await self.collection.update_many(
            {
                "academy_id": academy_id,
                "assigned_to_registration": True,
                "waiver_template_id": {"$ne": waiver_template_id},
            },
            {
                "$set": {
                    "assigned_to_registration": False,
                    "assigned_at": None,
                    "updated_at": assigned_at,
                }
            },
        )
        await self._update_one(
            {
                **self._id_filter(waiver_template_id),
                "status": {"$in": ["active", "published"]},
            },
            {
                "$set": {
                    "assigned_to_registration": True,
                    "assigned_at": assigned_at,
                    "updated_at": assigned_at,
                }
            },
        )
        assigned = await self.get_template(waiver_template_id)
        if assigned is None:
            raise RuntimeError("Failed to assign waiver template to registration")
        return assigned
