"""``crm_contacts`` reads and writes are scoped by ``academy_id`` (#880 guard-test pattern).

A contact created under academy A must be invisible to every read issued
under academy B, even by its exact ``contact_id`` or ``dedupe_key``, and the
row must carry A's id however the caller built the domain object.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

from mongomock_motor import AsyncMongoMockClient

from backend.v2.contexts.crm.application.use_cases.create_contact import (
    CreateContact,
    CreateContactCommand,
)
from backend.v2.contexts.crm.domain.models import CrmContact
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

_M0192 = importlib.import_module("backend.v2.migrations.0192_crm_contacts")

ACADEMY_ID = "acad-crm-a"
OTHER = "acad-crm-b"


async def test_reads_from_another_academy_see_nothing() -> None:
    db = AsyncMongoMockClient()["crm_scope_test"]
    await _M0192.up(db)

    with tenant_scope(ACADEMY_ID):
        created = await CreateContact(MongoCrmContactRepository(db)).execute(
            CreateContactCommand(name="Scoped Lead", source="website", email="scoped@example.test")
        )
    contact = created.contact

    with tenant_scope(OTHER):
        other = MongoCrmContactRepository(db)
        assert await other.get(contact.contact_id) is None
        assert await other.find_by_dedupe_key(contact.dedupe_key) is None
        assert await other.list_by_pipeline_status() == []
        assert await other.list_by_pipeline_status("lead") == []

    with tenant_scope(ACADEMY_ID):
        mine = MongoCrmContactRepository(db)
        assert await mine.get(contact.contact_id) == contact
        assert await mine.find_by_dedupe_key(contact.dedupe_key) == contact


async def test_write_stamps_the_tenant_not_the_callers_academy_id() -> None:
    db = AsyncMongoMockClient()["crm_scope_test"]
    await _M0192.up(db)
    now = datetime(2026, 9, 23, tzinfo=UTC)
    forged = CrmContact(
        contact_id="c-forged",
        academy_id=OTHER,  # a caller must never be able to pick the tenant
        name="Forged Lead",
        email="forged@example.test",
        source="other",
        dedupe_key="k-forged",
        created_at=now,
        updated_at=now,
    )
    with tenant_scope(ACADEMY_ID):
        stored, created = await MongoCrmContactRepository(db).add_if_absent(forged)

    assert created is True
    assert stored.academy_id == ACADEMY_ID
    row = await db["crm_contacts"].find_one({"contact_id": "c-forged"})
    assert row["academy_id"] == ACADEMY_ID
    with tenant_scope(OTHER):
        assert await MongoCrmContactRepository(db).get("c-forged") is None
