"""SaaS tenant-isolation guardrails for TenantScopedRepository.

These tests pin the shared repository contract that SaaS code relies on:
every tenant-owned read/write/delete must be scoped by the request tenant,
and missing tenant context is a hard error.
"""

from __future__ import annotations

import pytest

from backend.v2.shared.tenancy import TenantScopedRepository, tenant_scope
from backend.v2.shared.tenancy.context import TenantContextUnset


class ProbeTenantRepository(TenantScopedRepository):
    collection_name = "saas_guardrail_docs"

    async def add(self, doc: dict[str, object]):
        return await self._insert_one(doc)

    async def get(self, doc_id: str) -> dict[str, object] | None:
        return await self._find_one({"doc_id": doc_id})

    async def update_status(self, doc_id: str, status: str):
        return await self._update_one({"doc_id": doc_id}, {"$set": {"status": status}})

    async def delete(self, doc_id: str):
        return await self._delete_one({"doc_id": doc_id})


@pytest.mark.asyncio
async def test_missing_tenant_context_raises(db) -> None:
    from backend.v2.shared.tenancy.context import _current as tenant_context_var

    repo = ProbeTenantRepository(db)
    token = tenant_context_var.set(None)
    try:
        with pytest.raises(TenantContextUnset, match="No academy_id in context"):
            await repo.get("doc-1")
    finally:
        tenant_context_var.reset(token)


@pytest.mark.asyncio
async def test_read_under_academy_a_does_not_see_academy_b_docs(db) -> None:
    await db["saas_guardrail_docs"].insert_many(
        [
            {"academy_id": "academy-a", "doc_id": "visible-to-a", "status": "active"},
            {"academy_id": "academy-b", "doc_id": "visible-to-b", "status": "active"},
        ]
    )

    repo = ProbeTenantRepository(db)

    with tenant_scope("academy-a"):
        assert await repo.get("visible-to-a") is not None
        assert await repo.get("visible-to-b") is None


@pytest.mark.asyncio
async def test_insert_under_academy_a_is_scoped_to_current_tenant(db) -> None:
    repo = ProbeTenantRepository(db)

    with tenant_scope("academy-a"):
        await repo.add({"doc_id": "new-doc", "status": "active"})

    assert await db["saas_guardrail_docs"].find_one(
        {"academy_id": "academy-a", "doc_id": "new-doc"}
    )
    assert (
        await db["saas_guardrail_docs"].find_one({"academy_id": "academy-b", "doc_id": "new-doc"})
        is None
    )


@pytest.mark.asyncio
async def test_update_under_academy_a_does_not_mutate_academy_b_docs(db) -> None:
    await db["saas_guardrail_docs"].insert_many(
        [
            {"academy_id": "academy-a", "doc_id": "shared-doc", "status": "pending"},
            {"academy_id": "academy-b", "doc_id": "shared-doc", "status": "pending"},
        ]
    )

    repo = ProbeTenantRepository(db)

    with tenant_scope("academy-a"):
        result = await repo.update_status("shared-doc", "updated-by-a")

    assert result.matched_count == 1
    academy_a = await db["saas_guardrail_docs"].find_one(
        {"academy_id": "academy-a", "doc_id": "shared-doc"}
    )
    academy_b = await db["saas_guardrail_docs"].find_one(
        {"academy_id": "academy-b", "doc_id": "shared-doc"}
    )
    assert academy_a["status"] == "updated-by-a"
    assert academy_b["status"] == "pending"


@pytest.mark.asyncio
async def test_delete_under_academy_a_does_not_delete_academy_b_docs(db) -> None:
    await db["saas_guardrail_docs"].insert_many(
        [
            {"academy_id": "academy-a", "doc_id": "shared-doc", "status": "active"},
            {"academy_id": "academy-b", "doc_id": "shared-doc", "status": "active"},
        ]
    )

    repo = ProbeTenantRepository(db)

    with tenant_scope("academy-a"):
        result = await repo.delete("shared-doc")

    assert result.deleted_count == 1
    assert (
        await db["saas_guardrail_docs"].find_one(
            {"academy_id": "academy-a", "doc_id": "shared-doc"}
        )
        is None
    )
    assert (
        await db["saas_guardrail_docs"].find_one(
            {"academy_id": "academy-b", "doc_id": "shared-doc"}
        )
        is not None
    )
