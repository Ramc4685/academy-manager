"""``email_prospect_opt_outs`` is per academy, and its gate only sees prospects."""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

import pytest
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.infrastructure.mongo_prospect_opt_out_repo import (
    MongoProspectOptOutRepository,
    ProspectOptOutGate,
)
from backend.v2.shared.tenancy import tenant_scope

_M0217 = importlib.import_module("backend.v2.migrations.0217_email_prospect_opt_outs")


@pytest.fixture
def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["prospect-opt-outs"]
    asyncio.run(_M0217.up(db))
    return db


def test_opt_out_is_stored_by_normalised_address_for_one_academy_only(db: Any) -> None:
    repo = MongoProspectOptOutRepository(db)

    async def _run() -> tuple[bool, bool, int]:
        with tenant_scope("acad-a"):
            await repo.opt_out(email=" Jamie@Example.test ", recipient_id="crm_contact:c1")
            await repo.opt_out(email="jamie@example.test", recipient_id="crm_contact:c2")
            in_a = await repo.is_opted_out("JAMIE@example.test")
        with tenant_scope("acad-b"):
            in_b = await repo.is_opted_out("jamie@example.test")
        rows = await db["email_prospect_opt_outs"].count_documents({})
        return in_a, in_b, rows

    assert asyncio.run(_run()) == (True, False, 1)


def test_gate_blocks_only_prospect_recipients_and_fails_closed_on_store_errors(db: Any) -> None:
    repo = MongoProspectOptOutRepository(db)
    gate = ProspectOptOutGate(repo)

    async def _run() -> list[bool]:
        with tenant_scope("acad-a"):
            await repo.opt_out(email="jamie@example.test", recipient_id="crm_contact:c1")
            prospect = await gate.check(
                recipient_user_id="crm_contact:c9",
                email="jamie@example.test",
                category=EmailCategory.TRANSACTIONAL,
            )
            user = await gate.check(
                recipient_user_id="user-1",
                email="jamie@example.test",
                category=EmailCategory.TRANSACTIONAL,
            )
        # No tenant in scope: the repository raises, the gate refuses.
        broken = await gate.check(
            recipient_user_id="crm_contact:c9",
            email="jamie@example.test",
            category=EmailCategory.TRANSACTIONAL,
        )
        return [prospect.allowed, user.allowed, broken.allowed, broken.reason]

    assert asyncio.run(_run()) == [False, True, False, "unsubscribe_check_unavailable"]
