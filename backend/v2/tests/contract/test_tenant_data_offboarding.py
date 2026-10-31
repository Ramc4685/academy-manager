"""L9d on a real mongod: tenant export and purge dry-run.

Every collection the tenant-scope guard calls tenant-owned is seeded for two
academies. The export of A must carry every one of them and no row of B; the
purge dry-run must refuse a tenant that is not cancelled, count without
deleting, and leave both tenants' data exactly as it was. Synthetic data only.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.platform.application.use_cases.tenant_data_offboarding import (
    TenantDataOffboardingService,
)
from backend.v2.contexts.platform.audit.application.use_cases import (
    PlatformAuditService,
    RecordPlatformAuditEventCommand,
)
from backend.v2.contexts.platform.audit.infrastructure.mongo_platform_audit_repo import (
    MongoPlatformAuditRepository,
)
from backend.v2.contexts.platform.domain.errors import TenantInvalidTransition
from backend.v2.contexts.platform.infrastructure.mongo_tenant_data_store import (
    MongoTenantDataStore,
)
from backend.v2.contexts.platform.infrastructure.mongo_tenant_lifecycle_repo import (
    MongoTenantLifecycleRepository,
)
from backend.v2.tests.test_no_raw_tenant_mongo_access import TENANT_OWNED_COLLECTIONS

A = "acad_export_alpha"
B = "acad_export_bravo"
_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def _academy(academy_id: str, status: str) -> dict[str, Any]:
    return {
        "academy_id": academy_id,
        "display_name": f"Synthetic Club {academy_id[-5:]}",
        "slug": academy_id.replace("_", "-"),
        "primary_domain": f"{academy_id.replace('_', '-')}.example.test",
        "status": status,
        "plan_code": "starter",
        "fee_model": "flat_monthly",
        "created_by": "platform-admin",
        "updated_by": "platform-admin",
        "created_at": _NOW,
        "updated_at": _NOW,
    }


async def _unique_fields(db: Any, name: str) -> list[str]:
    """Key fields of every unique index, so seeded rows never collide."""
    info = await db[name].index_information()
    fields: set[str] = set()
    for spec in info.values():
        if spec.get("unique"):
            fields.update(key for key, _ in spec["key"] if key not in ("_id", "academy_id"))
    return sorted(fields)


def _set_path(doc: dict[str, Any], dotted: str, value: str) -> None:
    head, _, rest = dotted.partition(".")
    if not rest:
        doc.setdefault(head, value)
        return
    child = doc.setdefault(head, {})
    if isinstance(child, dict):
        _set_path(child, rest, value)


async def _seed(db: Any, *, a_status: str = "active") -> None:
    await db["academies"].insert_one(_academy(A, a_status), bypass_document_validation=True)
    await db["academies"].insert_one(_academy(B, "active"), bypass_document_validation=True)
    for name in sorted(TENANT_OWNED_COLLECTIONS):
        unique_fields = await _unique_fields(db, name)
        for academy in (A, B):
            doc: dict[str, Any] = {
                "academy_id": academy,
                "synthetic_marker": f"{academy}:{name}",
                "created_at": _NOW,
            }
            for field in unique_fields:
                _set_path(doc, field, f"{academy}-{name}-{field}")
            await db[name].insert_one(doc, bypass_document_validation=True)
    # A platform-owned row about A: never exported, always retained.
    await db["platform_audit_events"].insert_one(
        {"academy_id": A, "action": "tenant.created", "synthetic_marker": f"{A}:audit"},
        bypass_document_validation=True,
    )


def _service(db: Any, recorder: Any = None) -> TenantDataOffboardingService:
    audit = PlatformAuditService(audit_events=MongoPlatformAuditRepository(db))

    async def _record(command: RecordPlatformAuditEventCommand) -> object:
        return await audit.record_event(command)

    return TenantDataOffboardingService(
        tenants=MongoTenantLifecycleRepository(db),
        data=MongoTenantDataStore(db),
        audit_recorder=recorder or _record,
        clock=lambda: _NOW,
    )


async def _snapshot(db: Any) -> dict[str, int]:
    names = await db.list_collection_names()
    return {
        name: await db[name].count_documents({})
        for name in sorted(names)
        if not name.startswith("system.")
    }


@pytest.mark.asyncio
async def test_export_of_a_contains_every_tenant_collection_and_no_b_rows(real_db) -> None:
    await _seed(real_db)

    archive = await _service(real_db).export_tenant(
        A, actor_user_id="platform-admin", reason="academy asked for its data"
    )

    with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
        bodies = {name: zf.read(name).decode() for name in names}

    for collection in TENANT_OWNED_COLLECTIONS:
        assert f"collections/{collection}.jsonl" in names, collection
    assert "collections/academies.jsonl" in names
    assert "collections/platform_audit_events.jsonl" not in names
    for body in bodies.values():
        assert B not in body
    assert manifest["academy_id"] == A
    counts = {row["collection"]: row["count"] for row in manifest["collections"]}
    assert all(counts[c] == 1 for c in TENANT_OWNED_COLLECTIONS)
    assert manifest["total_documents"] == len(TENANT_OWNED_COLLECTIONS) + 1
    assert set(manifest["files"]) == names - {"manifest.json"}

    audit = await real_db["platform_audit_events"].find_one({"action": "tenant.data_exported"})
    assert audit is not None
    assert audit["academy_id"] == A
    assert audit["after_snapshot"]["archive_sha256"] == archive.sha256


@pytest.mark.asyncio
async def test_export_is_refused_when_the_audit_row_cannot_be_written(real_db) -> None:
    await _seed(real_db)

    async def _broken(command: RecordPlatformAuditEventCommand) -> object:
        raise RuntimeError("audit store down")

    with pytest.raises(RuntimeError, match="audit store down"):
        await _service(real_db, recorder=_broken).export_tenant(
            A, actor_user_id="platform-admin", reason="academy asked for its data"
        )


@pytest.mark.asyncio
async def test_purge_dry_run_refuses_a_tenant_that_is_not_cancelled(real_db) -> None:
    await _seed(real_db, a_status="active")

    with pytest.raises(TenantInvalidTransition):
        await _service(real_db).purge_dry_run(A, actor_user_id="platform-admin")

    assert (
        await real_db["platform_audit_events"].count_documents({"action": "tenant.purge_dry_run"})
        == 0
    )


@pytest.mark.asyncio
async def test_purge_dry_run_counts_without_deleting_anything(real_db) -> None:
    await _seed(real_db, a_status="cancelled")
    before = await _snapshot(real_db)

    result = await _service(real_db).purge_dry_run(A, actor_user_id="platform-admin")

    deleted = {row.collection: row.count for row in result.would_delete}
    retained = {row.collection: row.count for row in result.would_retain}
    assert deleted == {name: 1 for name in TENANT_OWNED_COLLECTIONS}
    assert retained["academies"] == 1
    assert retained["platform_audit_events"] == 1
    assert result.total_to_delete == len(TENANT_OWNED_COLLECTIONS)
    assert result.executed is False
    assert result.confirm_token.startswith("purge_")

    after = await _snapshot(real_db)
    # Only the dry-run's own audit row was added.
    after["platform_audit_events"] -= 1
    assert after == before
    audit = await real_db["platform_audit_events"].find_one({"action": "tenant.purge_dry_run"})
    assert audit is not None
    assert audit["after_snapshot"]["confirm_token"] == result.confirm_token
    assert audit["after_snapshot"]["executed"] is False


@pytest.mark.asyncio
async def test_confirm_token_changes_when_tenant_data_changes(real_db) -> None:
    await _seed(real_db, a_status="cancelled")
    service = _service(real_db)
    first = await service.purge_dry_run(A, actor_user_id="platform-admin")

    await real_db["students"].insert_one(
        {"academy_id": A, "synthetic_marker": "late write"}, bypass_document_validation=True
    )
    second = await service.purge_dry_run(A, actor_user_id="platform-admin")

    assert first.confirm_token != second.confirm_token
