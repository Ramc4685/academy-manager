"""Mongo persistence for SaaS platform governance requests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pymongo import ReturnDocument


class MongoGovernanceStore:
    """Persists platform governance records in dedicated platform collections."""

    def __init__(self, db: Any) -> None:
        self._tenant_exports = db["tenant_export_requests"]
        self._tenant_deletions = db["tenant_deletion_requests"]
        self._student_deletions = db["student_data_deletion_requests"]
        self._support_access = db["support_access_grants"]
        self._support_impersonation = db["support_impersonation_requests"]
        self._audit_logs = db["platform_governance_audit_logs"]

    async def create_tenant_export_request(self, request: dict[str, Any]) -> dict[str, Any]:
        await self._tenant_exports.insert_one(dict(request))
        return self._clean(request)

    async def get_tenant_export_request(self, request_id: str) -> dict[str, Any] | None:
        doc = await self._tenant_exports.find_one({"export_request_id": request_id})
        return self._clean(doc) if doc else None

    async def list_tenant_export_requests(
        self, academy_id: str | None = None
    ) -> list[dict[str, Any]]:
        return await self._list(
            self._tenant_exports,
            {"academy_id": academy_id} if academy_id else {},
        )

    async def update_tenant_export_request(
        self, request_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        doc = await self._tenant_exports.find_one_and_update(
            {"export_request_id": request_id},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            raise KeyError(request_id)
        return self._clean(doc)

    async def create_tenant_deletion_request(self, request: dict[str, Any]) -> dict[str, Any]:
        await self._tenant_deletions.insert_one(dict(request))
        return self._clean(request)

    async def list_tenant_deletion_requests(
        self, academy_id: str | None = None
    ) -> list[dict[str, Any]]:
        return await self._list(
            self._tenant_deletions,
            {"academy_id": academy_id} if academy_id else {},
        )

    async def create_student_data_deletion_request(self, request: dict[str, Any]) -> dict[str, Any]:
        await self._student_deletions.insert_one(dict(request))
        return self._clean(request)

    async def list_student_data_deletion_requests(
        self, academy_id: str | None = None
    ) -> list[dict[str, Any]]:
        return await self._list(
            self._student_deletions,
            {"academy_id": academy_id} if academy_id else {},
        )

    async def create_support_access_grant(self, grant: dict[str, Any]) -> dict[str, Any]:
        await self._support_access.insert_one(dict(grant))
        return self._clean(grant)

    async def list_support_access_grants(
        self, academy_id: str | None = None
    ) -> list[dict[str, Any]]:
        return await self._list(
            self._support_access,
            {"academy_id": academy_id} if academy_id else {},
        )

    async def revoke_support_access_grant(
        self, grant_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        doc = await self._support_access.find_one_and_update(
            {"support_access_grant_id": grant_id},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )
        return self._clean(doc) if doc else None

    async def create_support_impersonation_request(self, request: dict[str, Any]) -> dict[str, Any]:
        await self._support_impersonation.insert_one(dict(request))
        return self._clean(request)

    async def list_support_impersonation_requests(
        self, academy_id: str | None = None
    ) -> list[dict[str, Any]]:
        return await self._list(
            self._support_impersonation,
            {"academy_id": academy_id} if academy_id else {},
        )

    async def get_request_status(self, request_id: str) -> dict[str, Any] | None:
        for request_type, collection, id_field in self._request_collections():
            doc = await collection.find_one({id_field: request_id})
            if doc:
                return {
                    "request_id": str(doc[id_field]),
                    "request_type": request_type,
                    "academy_id": str(doc["academy_id"]),
                    "status": str(doc["status"]),
                }
        return None

    async def append_audit_log(self, audit: dict[str, Any]) -> dict[str, Any]:
        await self._audit_logs.insert_one(dict(audit))
        return self._clean(audit)

    async def list_audit_logs(self, academy_id: str | None = None) -> list[dict[str, Any]]:
        return await self._list(
            self._audit_logs,
            {"academy_id": academy_id} if academy_id else {},
        )

    async def _list(self, collection: Any, query: dict[str, Any]) -> list[dict[str, Any]]:
        cursor = collection.find(query).sort("created_at", -1)
        return [self._clean(doc) async for doc in cursor]

    def _request_collections(self) -> list[tuple[str, Any, str]]:
        return [
            ("tenant_export", self._tenant_exports, "export_request_id"),
            ("tenant_deletion", self._tenant_deletions, "deletion_request_id"),
            ("student_data_deletion", self._student_deletions, "student_deletion_request_id"),
            ("support_access", self._support_access, "support_access_grant_id"),
            (
                "support_impersonation",
                self._support_impersonation,
                "impersonation_request_id",
            ),
        ]

    @staticmethod
    def _clean(doc: dict[str, Any]) -> dict[str, Any]:
        cleaned = dict(doc)
        cleaned.pop("_id", None)
        return {key: MongoGovernanceStore._normalize(value) for key, value in cleaned.items()}

    @staticmethod
    def _normalize(value: Any) -> Any:
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        if isinstance(value, dict):
            return {key: MongoGovernanceStore._normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [MongoGovernanceStore._normalize(item) for item in value]
        return value
