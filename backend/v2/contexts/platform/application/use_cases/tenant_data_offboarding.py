"""Tenant data export and purge dry-run (roadmap L9d).

Offboarding a tenant needs two things before anything is ever deleted: a
complete copy of the tenant's data, and a preview of exactly what a purge
would remove. This module provides both and nothing destructive:

* :meth:`TenantDataOffboardingService.export_tenant` streams a zip archive of
  every tenant-scoped collection, each filtered by ``academy_id``, plus a
  manifest of per-collection counts and a SHA-256 of every file. It holds one
  document and a small output buffer at a time, never the whole archive.
* :meth:`TenantDataOffboardingService.purge_dry_run` counts, per collection,
  what a purge of a *cancelled* tenant would delete and what it would keep.
  It returns a ``confirm_token`` derived from those counts; the (future,
  owner-confirmed) purge execution must be handed the same token, so data
  that changed after the preview cannot be purged on a stale preview.

Purge EXECUTION is deliberately not implemented. The owner-confirmed
procedure is in ``docs/runbooks/tenant-export-and-purge.md``.

Collections are discovered from the live database rather than from a
hand-kept list, so a collection added later is exported without anyone
remembering to register it. The only hand-kept lists are the exclusions
below, each with its reason; ``tests/unit/test_tenant_data_offboarding.py``
proves no tenant-owned collection from the tenant-scope guard ever lands in
them.

Both operations write a ``platform_audit_events`` row and fail closed: if the
audit row cannot be written the export is refused, because tenant data must
never leave without a trail. The export writes ``tenant.data_export_started``
before its first byte and ``tenant.data_exported`` (archive SHA-256, size,
counts) after its last; a started row with no exported row is an export that
was cut off, and its truncated zip has no central directory, so it fails to
open rather than passing for a complete copy.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from bson import json_util
from pydantic import BaseModel

from backend.v2.contexts.platform.application.ports import TenantLifecycleRepository
from backend.v2.contexts.platform.audit.application.use_cases import (
    RecordPlatformAuditEventCommand,
)
from backend.v2.contexts.platform.domain.errors import TenantInvalidTransition, TenantNotFound
from backend.v2.contexts.platform.domain.models import Tenant

#: Async callable that persists one platform_audit_events row. Unlike the
#: lifecycle recorder it must RAISE on failure: the caller fails closed.
StrictAuditRecorder = Callable[[RecordPlatformAuditEventCommand], Awaitable[object]]

ARCHIVE_FORMAT_VERSION = 1

#: Platform-owned collections. They carry an ``academy_id`` but record what
#: the PLATFORM did about the tenant (audit trails, governance requests,
#: support access, the platform's own subscription billing). They are not the
#: academy's data, so they are never exported to it, and a purge keeps them:
#: the trail of an offboarding must outlive the offboarded data.
PLATFORM_INTERNAL_COLLECTIONS: dict[str, str] = {
    "platform_audit_events": "platform audit trail; records this export and any purge",
    "platform_governance_audit_logs": "platform governance audit trail",
    "tenant_export_requests": "platform governance request records",
    "tenant_deletion_requests": "platform governance request records",
    "student_data_deletion_requests": "platform governance request records",
    "support_access_grants": "platform support access records",
    "support_impersonation_requests": "platform support access records",
    "platform_plans": "platform catalogue, not tenant data",
    "platform_tenant_subscriptions": "the platform's own billing of the academy",
}

#: Exported (they hold the tenant's rows) but kept by a purge.
RETAINED_ON_PURGE: dict[str, str] = {
    "academies": (
        "the tenant record stays as a cancelled tombstone so the slug and "
        "domain are not silently reused and the audit trail still resolves"
    ),
    "users": "a login identity can belong to several academies",
}


class CollectionCount(BaseModel, frozen=True):
    collection: str
    count: int


class TenantExportManifest(BaseModel, frozen=True):
    format_version: int
    academy_id: str
    tenant_status: str
    generated_at: datetime
    generated_by: str
    reason: str
    collections: list[CollectionCount]
    total_documents: int
    files: dict[str, str]  # archive path -> sha256 of the file


@dataclass(frozen=True)
class TenantExportStream:
    """A tenant export in flight: iterate ``chunks`` to get the zip bytes."""

    filename: str
    chunks: AsyncIterator[bytes]


#: Bytes buffered before a chunk is handed to the response.
EXPORT_CHUNK_BYTES = 256 * 1024


class _ZipSink(io.RawIOBase):
    """Write-only, non-seekable target for ``zipfile``: it collects what the
    archive writes until the generator drains it. Non-seekable makes
    ``zipfile`` use data descriptors, so nothing is ever rewritten."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def writable(self) -> bool:
        return True

    def write(self, data: Any) -> int:
        self._buffer += data
        return len(data)

    def pending(self) -> int:
        return len(self._buffer)

    def take(self) -> bytes:
        data = bytes(self._buffer)
        self._buffer.clear()
        return data


class PurgeDryRun(BaseModel, frozen=True):
    academy_id: str
    tenant_status: str
    cancelled_at: datetime | None
    generated_at: datetime
    would_delete: list[CollectionCount]
    would_retain: list[CollectionCount]
    total_to_delete: int
    confirm_token: str
    executed: bool = False


class TenantDataStore(Protocol):
    """Reads tenant-scoped documents from every tenant collection."""

    async def collection_names(self) -> list[str]: ...
    async def count(self, collection: str, academy_id: str) -> int: ...
    def documents(self, collection: str, academy_id: str) -> AsyncIterator[dict[str, Any]]: ...


def exportable_collections(names: list[str]) -> list[str]:
    """Every collection that may hold tenant rows, in a stable order."""
    return sorted(
        name
        for name in set(names)
        if not name.startswith("system.") and name not in PLATFORM_INTERNAL_COLLECTIONS
    )


def purge_confirm_token(academy_id: str, would_delete: list[CollectionCount]) -> str:
    """Deterministic token over the preview's counts.

    The purge executor must recompute it and refuse when it differs from the
    token the owner confirmed: any write after the preview changes a count
    and therefore the token.
    """
    body = academy_id + "|" + ",".join(f"{c.collection}={c.count}" for c in would_delete)
    return "purge_" + hashlib.sha256(body.encode()).hexdigest()[:24]


class TenantDataOffboardingService:
    def __init__(
        self,
        *,
        tenants: TenantLifecycleRepository,
        data: TenantDataStore,
        audit_recorder: StrictAuditRecorder,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._tenants = tenants
        self._data = data
        self._audit_recorder = audit_recorder
        self._clock = clock or (lambda: datetime.now(UTC))

    async def _tenant(self, academy_id: str) -> Tenant:
        tenant = await self._tenants.get_by_id(academy_id)
        if tenant is None:
            raise TenantNotFound(f"tenant not found: {academy_id}")
        return tenant

    async def _emit_audit(
        self,
        *,
        actor_user_id: str,
        academy_id: str,
        action: str,
        after: dict[str, Any],
        request_id: str | None,
        ip_address: str | None,
    ) -> None:
        """Write the audit row. Raises on failure: callers fail closed."""
        await self._audit_recorder(
            RecordPlatformAuditEventCommand(
                actor_user_id=actor_user_id,
                academy_id=academy_id,
                platform_actor_role="platform_admin",
                action=action,
                entity_type="tenant",
                entity_id=academy_id,
                before_snapshot=None,
                after_snapshot=after,
                request_id=request_id,
                ip_address=ip_address,
            )
        )

    async def export_tenant(
        self,
        academy_id: str,
        *,
        actor_user_id: str,
        reason: str,
        request_id: str | None = None,
        ip_address: str | None = None,
    ) -> TenantExportStream:
        tenant = await self._tenant(academy_id)
        now = self._clock()
        # Fail closed BEFORE any byte: no trail, no export.
        await self._emit_audit(
            actor_user_id=actor_user_id,
            academy_id=academy_id,
            action="tenant.data_export_started",
            after={"reason": reason, "tenant_status": tenant.status},
            request_id=request_id,
            ip_address=ip_address,
        )
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        return TenantExportStream(
            filename=f"tenant-export-{academy_id}-{stamp}.zip",
            chunks=self._export_chunks(
                tenant,
                now=now,
                actor_user_id=actor_user_id,
                reason=reason,
                request_id=request_id,
                ip_address=ip_address,
            ),
        )

    async def _export_chunks(
        self,
        tenant: Tenant,
        *,
        now: datetime,
        actor_user_id: str,
        reason: str,
        request_id: str | None,
        ip_address: str | None,
    ) -> AsyncIterator[bytes]:
        academy_id = tenant.academy_id
        sink = _ZipSink()
        archive_sha = hashlib.sha256()
        archive_bytes = 0
        counts: list[CollectionCount] = []
        files: dict[str, str] = {}

        def drain() -> bytes:
            nonlocal archive_bytes
            data = sink.take()
            archive_sha.update(data)
            archive_bytes += len(data)
            return data

        with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in exportable_collections(await self._data.collection_names()):
                docs = self._data.documents(name, academy_id).__aiter__()
                doc = await anext(docs, None)
                if doc is None:
                    continue
                path = f"collections/{name}.jsonl"
                file_sha = hashlib.sha256()
                count = 0
                with archive.open(path, "w", force_zip64=True) as entry:
                    while doc is not None:
                        if doc.get("academy_id") != academy_id:
                            # Defence in depth: the store filters by academy_id,
                            # but nothing of another tenant may ever be archived.
                            raise RuntimeError(f"export store returned a foreign row from {name}")
                        line = (
                            json_util.dumps(doc, json_options=json_util.RELAXED_JSON_OPTIONS) + "\n"
                        ).encode()
                        entry.write(line)
                        file_sha.update(line)
                        count += 1
                        if sink.pending() >= EXPORT_CHUNK_BYTES:
                            yield drain()
                        doc = await anext(docs, None)
                files[path] = file_sha.hexdigest()
                counts.append(CollectionCount(collection=name, count=count))
            manifest = TenantExportManifest(
                format_version=ARCHIVE_FORMAT_VERSION,
                academy_id=academy_id,
                tenant_status=tenant.status,
                generated_at=now,
                generated_by=actor_user_id,
                reason=reason,
                collections=counts,
                total_documents=sum(c.count for c in counts),
                files=files,
            )
            archive.writestr("manifest.json", manifest.model_dump_json(indent=2))
        # Closing the archive wrote the central directory into the sink. Audit
        # BEFORE yielding it: without the directory the zip cannot be opened,
        # so a failed completion audit leaves the client nothing usable.
        final = drain()
        await self._emit_audit(
            actor_user_id=actor_user_id,
            academy_id=academy_id,
            action="tenant.data_exported",
            after={
                "reason": reason,
                "tenant_status": tenant.status,
                "archive_sha256": archive_sha.hexdigest(),
                "archive_bytes": archive_bytes,
                "total_documents": manifest.total_documents,
                "collection_counts": {c.collection: c.count for c in counts},
            },
            request_id=request_id,
            ip_address=ip_address,
        )
        yield final

    async def purge_dry_run(
        self,
        academy_id: str,
        *,
        actor_user_id: str,
        request_id: str | None = None,
        ip_address: str | None = None,
    ) -> PurgeDryRun:
        tenant = await self._tenant(academy_id)
        if tenant.status != "cancelled":
            raise TenantInvalidTransition(
                "a purge can only be previewed for a cancelled tenant",
                academy_id=academy_id,
                status=tenant.status,
            )
        would_delete: list[CollectionCount] = []
        would_retain: list[CollectionCount] = []
        names = set(await self._data.collection_names())
        for name in exportable_collections(list(names)):
            count = await self._data.count(name, academy_id)
            if count == 0:
                continue
            row = CollectionCount(collection=name, count=count)
            (would_retain if name in RETAINED_ON_PURGE else would_delete).append(row)
        for name in sorted(names & set(PLATFORM_INTERNAL_COLLECTIONS)):
            count = await self._data.count(name, academy_id)
            if count:
                would_retain.append(CollectionCount(collection=name, count=count))
        token = purge_confirm_token(academy_id, would_delete)
        result = PurgeDryRun(
            academy_id=academy_id,
            tenant_status=tenant.status,
            cancelled_at=tenant.cancelled_at,
            generated_at=self._clock(),
            would_delete=would_delete,
            would_retain=would_retain,
            total_to_delete=sum(c.count for c in would_delete),
            confirm_token=token,
        )
        await self._emit_audit(
            actor_user_id=actor_user_id,
            academy_id=academy_id,
            action="tenant.purge_dry_run",
            after={
                "confirm_token": token,
                "total_to_delete": result.total_to_delete,
                "would_delete": {c.collection: c.count for c in would_delete},
                "would_retain": {c.collection: c.count for c in would_retain},
                "executed": False,
            },
            request_id=request_id,
            ip_address=ip_address,
        )
        return result
