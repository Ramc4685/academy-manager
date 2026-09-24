"""L9d: the export/purge collection classification cannot drop tenant data.

Collections are discovered from the live database, so the only way a
tenant-owned collection escapes the export is by landing in an exclusion
list. These tests pin that no collection the tenant-scope guard calls
tenant-owned is ever excluded from the export or retained by a purge.
"""

from __future__ import annotations

from backend.v2.contexts.platform.application.use_cases.tenant_data_offboarding import (
    PLATFORM_INTERNAL_COLLECTIONS,
    RETAINED_ON_PURGE,
    CollectionCount,
    exportable_collections,
    purge_confirm_token,
)
from backend.v2.tests.test_no_raw_tenant_mongo_access import (
    GLOBAL_COLLECTIONS,
    TENANT_OWNED_COLLECTIONS,
)


def test_no_tenant_owned_collection_is_excluded_from_export() -> None:
    assert not (TENANT_OWNED_COLLECTIONS & set(PLATFORM_INTERNAL_COLLECTIONS))
    assert set(exportable_collections(sorted(TENANT_OWNED_COLLECTIONS))) == (
        TENANT_OWNED_COLLECTIONS
    )


def test_no_tenant_owned_collection_is_retained_by_a_purge() -> None:
    assert not (TENANT_OWNED_COLLECTIONS & set(RETAINED_ON_PURGE))


def test_retained_collections_are_global_or_the_tenant_record() -> None:
    # Only rows that outlive the tenant by design may be kept by a purge.
    assert set(RETAINED_ON_PURGE) <= GLOBAL_COLLECTIONS


def test_exportable_collections_skips_system_and_platform_internal() -> None:
    names = ["students", "system.views", "platform_audit_events", "students", "invoices"]
    assert exportable_collections(names) == ["invoices", "students"]


def test_confirm_token_changes_when_any_count_changes() -> None:
    rows = [CollectionCount(collection="students", count=3)]
    same = [CollectionCount(collection="students", count=3)]
    more = [CollectionCount(collection="students", count=4)]
    assert purge_confirm_token("acad_x", rows) == purge_confirm_token("acad_x", same)
    assert purge_confirm_token("acad_x", rows) != purge_confirm_token("acad_x", more)
    assert purge_confirm_token("acad_x", rows) != purge_confirm_token("acad_y", rows)
