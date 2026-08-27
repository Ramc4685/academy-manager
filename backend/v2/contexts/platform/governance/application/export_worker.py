"""Non-destructive tenant export worker scaffolding."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from backend.v2.contexts.platform.governance.domain.errors import GovernanceRequestNotFound
from backend.v2.contexts.platform.governance.domain.models import TenantExportRequest


class TenantExportStore(Protocol):
    async def get_tenant_export_request(self, request_id: str) -> dict[str, Any] | None: ...
    async def update_tenant_export_request(
        self, request_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]: ...


class TenantExportArtifactWriter(Protocol):
    async def write_metadata(self, request: TenantExportRequest) -> dict[str, object]: ...


class LocalTenantExportArtifactWriter:
    """Writes local/test artifact metadata only.

    No tenant data is read or exported here. This gives staging and tests a
    runnable job path while production storage/export composition remains gated.
    """

    def __init__(self, *, base_uri: str = "local://tenant-exports") -> None:
        self._base_uri = base_uri.rstrip("/")

    async def write_metadata(self, request: TenantExportRequest) -> dict[str, object]:
        return {
            "storage": "local_test",
            "uri": (f"{self._base_uri}/{request.academy_id}/{request.export_request_id}.json"),
            "include_pii": request.include_pii,
            "record_counts": {},
            "destructive": False,
        }


class TenantExportWorker:
    """Runs the initial non-destructive export request lifecycle."""

    def __init__(
        self,
        *,
        store: TenantExportStore,
        artifact_writer: TenantExportArtifactWriter,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._artifact_writer = artifact_writer
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run(self, export_request_id: str) -> TenantExportRequest:
        existing = await self._store.get_tenant_export_request(export_request_id)
        if existing is None:
            raise GovernanceRequestNotFound(f"tenant export not found: {export_request_id}")

        request = TenantExportRequest(**existing)
        if request.status == "completed":
            return request

        now = self._clock()
        processing = TenantExportRequest(
            **await self._store.update_tenant_export_request(
                export_request_id,
                {"status": "processing", "updated_at": now},
            )
        )
        artifact_metadata = await self._artifact_writer.write_metadata(processing)
        completed_at = self._clock()
        retention_days = processing.retention_policy.get("export_artifact_retention_days", 7)
        if not isinstance(retention_days, int):
            retention_days = 7
        expires_at = completed_at + timedelta(days=retention_days)
        completed = await self._store.update_tenant_export_request(
            export_request_id,
            {
                "status": "completed",
                "artifact_metadata": artifact_metadata,
                "artifact_expires_at": expires_at,
                "completed_at": completed_at,
                "updated_at": completed_at,
            },
        )
        return TenantExportRequest(**completed)
