"""Per-academy invoice prefix against a real mongod (Settings overhaul Phase 1 PR 2).

The guarantees here lean on things mongomock does not enforce: the global
partial unique index on ``billing_settings.invoice_number_prefix`` and the
migration that sets BLNO's prefix explicitly. Covers:

- BLNO's invoice numbers are byte-identical before and after (``BLNO-...``);
- a second academy gets its own prefix and its own numbers;
- the tenant settings save can neither write nor clobber the prefix;
- two academies can never hold the same prefix;
- the platform override locks once the academy has a numbered invoice;
- migration 0206 is explicit about BLNO, re-derives the old persisted default
  for everyone else, and is idempotent.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.platform_billing_identity import (
    compose_invoice_prefix_assigner,
    compose_platform_billing_identity,
)
from backend.v2.contexts.billing.application.use_cases.add_invoice_line import (
    AddInvoiceLine,
    AddInvoiceLineCommand,
)
from backend.v2.contexts.billing.application.use_cases.invoice_prefix import (
    SetInvoicePrefixCommand,
)
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.domain.errors import (
    InvoicePrefixLocked,
    InvoicePrefixTaken,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_counter_repo import (
    MongoBillingCounterRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.shared.tenancy import tenant_scope

migration = importlib.import_module("backend.v2.migrations.0206_invoice_prefix_per_academy")

BLNO = "acad_blno_badminton"
ACE = "acad_ace"
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
INDEX = "billing_settings_invoice_number_prefix_unique"


async def _academy(db: Any, academy_id: str, slug: str) -> None:
    await db["academies"].insert_one(
        {"academy_id": academy_id, "slug": slug, "display_name": slug, "status": "active"}
    )


async def _add_line(db: Any, academy_id: str, parent: str, period: str = "2026-09") -> Any:
    use_case = AddInvoiceLine(
        ledger=MongoBillingLedgerRepository(db, clock=lambda: NOW),
        counters=MongoBillingCounterRepository(db),
        settings=MongoBillingSettingsRepository(db),
        clock=lambda: NOW,
    )
    with tenant_scope(academy_id):
        result = await use_case.execute(
            AddInvoiceLineCommand(
                student_id=f"student-{parent}",
                period=period,
                academy_id=academy_id,
                parent_id=parent,
                description="September tuition",
                line_type="tuition",
                quantity=1,
                unit_amount_cents=7_000,
            )
        )
    return result.invoice


async def _prefix(db: Any, academy_id: str) -> str | None:
    doc = await db["billing_settings"].find_one({"academy_id": academy_id})
    return (doc or {}).get("invoice_number_prefix")


async def test_blno_numbers_unchanged_and_second_academy_gets_its_own(real_db) -> None:
    await _academy(real_db, BLNO, "blno")
    await migration.up(real_db)
    await _academy(real_db, ACE, "ace-badminton")
    assert (
        await compose_invoice_prefix_assigner(real_db).execute(academy_id=ACE, slug="ace-badminton")
        == "ACE"
    )

    blno_first = await _add_line(real_db, BLNO, "p1")
    blno_second = await _add_line(real_db, BLNO, "p2")
    ace_first = await _add_line(real_db, ACE, "p3")

    assert blno_first.invoice_number == "BLNO-2026-09-0001"
    assert blno_second.invoice_number == "BLNO-2026-09-0002"
    assert ace_first.invoice_number == "ACE-2026-09-0001"


async def test_tenant_settings_save_never_writes_or_clobbers_the_prefix(real_db) -> None:
    repo = MongoBillingSettingsRepository(real_db)
    with tenant_scope(ACE):
        # A settings save from an academy with no prefix must not persist one
        # (it used to persist the "BLNO" default into every document).
        await repo.upsert(BillingSettings(academy_id=ACE, ach_discount_enabled=True))
        assert "invoice_number_prefix" not in (
            await real_db["billing_settings"].find_one({"academy_id": ACE})
        )
        await repo.set_invoice_number_prefix("ACE")
        # A forged or stale model carrying another prefix changes nothing.
        await repo.upsert(BillingSettings(academy_id=ACE, invoice_number_prefix="EVIL"))
        assert (await repo.get()).invoice_number_prefix == "ACE"


async def test_two_academies_can_never_share_a_prefix(real_db) -> None:
    repo = MongoBillingSettingsRepository(real_db)
    with tenant_scope(BLNO):
        await repo.set_invoice_number_prefix("BLNO")
    with tenant_scope(ACE), pytest.raises(InvoicePrefixTaken):
        await repo.set_invoice_number_prefix("BLNO")
    with tenant_scope(BLNO):
        await repo.set_invoice_number_prefix("BLNO")  # re-setting your own is fine
    assert await _prefix(real_db, ACE) is None


async def test_assigner_skips_a_prefix_another_academy_holds(real_db) -> None:
    await _academy(real_db, "acad_ace_1", "ace-one")
    await _academy(real_db, "acad_ace_2", "ace-two")
    assigner = compose_invoice_prefix_assigner(real_db)

    assert await assigner.execute(academy_id="acad_ace_1", slug="ace-one") == "ACE"
    assert await assigner.execute(academy_id="acad_ace_2", slug="ace-two") == "ACE2"
    # Idempotent: re-bootstrapping keeps the prefix.
    assert await assigner.execute(academy_id="acad_ace_1", slug="renamed") == "ACE"


async def test_platform_override_locks_after_the_first_numbered_invoice(real_db) -> None:
    await _academy(real_db, ACE, "ace-badminton")
    platform = compose_platform_billing_identity(real_db)

    # No prefix yet: invoices are created unnumbered and do not lock anything.
    unnumbered = await _add_line(real_db, ACE, "p1")
    assert unnumbered.invoice_number is None
    assert (await platform.get.execute(ACE)).locked is False

    result = await platform.set.execute(
        SetInvoicePrefixCommand(academy_id=ACE, invoice_prefix="ACEB", actor_id="ops", reason="x")
    )
    assert (result.invoice_prefix, result.locked) == ("ACEB", False)
    [audit] = await real_db["billing_audit_log"].find({"academy_id": ACE}).to_list(None)
    assert audit["action"] == "invoice_prefix_changed"
    assert audit["before"] == {"invoice_number_prefix": None}
    assert audit["after"] == {"invoice_number_prefix": "ACEB"}

    numbered = await _add_line(real_db, ACE, "p2", period="2026-10")
    assert numbered.invoice_number == "ACEB-2026-10-0001"
    assert (await platform.get.execute(ACE)).locked is True

    with pytest.raises(InvoicePrefixLocked):
        await platform.set.execute(
            SetInvoicePrefixCommand(academy_id=ACE, invoice_prefix="ACE", actor_id="ops")
        )
    assert await _prefix(real_db, ACE) == "ACEB"


async def test_platform_override_refuses_another_academys_prefix(real_db) -> None:
    await _academy(real_db, BLNO, "blno")
    await _academy(real_db, ACE, "ace-badminton")
    await migration.up(real_db)
    platform = compose_platform_billing_identity(real_db)

    with pytest.raises(InvoicePrefixTaken):
        await platform.set.execute(
            SetInvoicePrefixCommand(academy_id=ACE, invoice_prefix="BLNO", actor_id="ops")
        )
    assert await _prefix(real_db, ACE) == "ACE"


async def test_migration_sets_blno_explicitly_and_rederives_the_old_default(real_db) -> None:
    # Before 0206 there was no unique index, and every settings save persisted
    # the "BLNO" default, so other academies can hold it too.
    await real_db["billing_settings"].drop_index(INDEX)
    await _academy(real_db, BLNO, "blno-badminton")
    await _academy(real_db, ACE, "ace-badminton")
    await _academy(real_db, "acad_kept", "kept")
    await _academy(real_db, "acad_bare", "shuttle-stars")
    await real_db["billing_settings"].insert_many(
        [
            {"academy_id": ACE, "invoice_number_prefix": "BLNO"},
            {"academy_id": "acad_kept", "invoice_number_prefix": "KEPT"},
            {"academy_id": "acad_orphan", "invoice_number_prefix": "BLNO"},
        ]
    )

    await migration.up(real_db)

    assert await _prefix(real_db, BLNO) == "BLNO"
    assert await _prefix(real_db, ACE) == "ACE"
    assert await _prefix(real_db, "acad_kept") == "KEPT"
    assert await _prefix(real_db, "acad_bare") == "SHUTTL"
    assert await _prefix(real_db, "acad_orphan") not in (None, "BLNO")
    indexes = await real_db["billing_settings"].index_information()
    assert indexes[INDEX]["unique"] is True

    before = await real_db["billing_settings"].find({}, {"_id": 0}).to_list(None)
    await migration.up(real_db)  # idempotent
    after = await real_db["billing_settings"].find({}, {"_id": 0}).to_list(None)
    assert sorted(before, key=lambda d: d["academy_id"]) == sorted(
        after, key=lambda d: d["academy_id"]
    )


async def test_migration_recognises_the_local_seed_blno_id(real_db) -> None:
    await _academy(real_db, "blno", "blno")
    await migration.up(real_db)
    assert await _prefix(real_db, "blno") == "BLNO"


async def test_migration_on_an_empty_database_writes_nothing(real_db) -> None:
    await migration.up(real_db)
    assert await real_db["billing_settings"].count_documents({}) == 0
