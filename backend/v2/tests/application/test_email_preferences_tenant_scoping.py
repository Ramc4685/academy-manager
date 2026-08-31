"""Email preferences are per-academy (#555).

A preference is a relationship between a family and *one* academy. On a shared
platform, unsubscribing from one academy's marketing must not silence a sibling
enrolled at another — and, in the other direction, a preference row must never
be readable across the tenant boundary.

(The suppression list in #556 is deliberately the opposite: a dead mailbox is a
fact about the shared sender domain, so it is cross-tenant by design.)
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.contexts.communications.application.ports import ResolvedRecipient
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.infrastructure.gated_send_port import (
    GatedEmailSendPort,
)
from backend.v2.contexts.communications.infrastructure.mongo_email_preference_repo import (
    MongoEmailPreferenceGate,
    MongoEmailPreferenceRepository,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import StubEmailSendPort
from backend.v2.shared.tenancy import tenant_scope


@pytest.fixture
def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    return mongomock_motor.AsyncMongoMockClient()["email-preferences-scoping"]


@pytest.mark.asyncio
async def test_an_opt_out_under_one_academy_does_not_block_a_send_under_another(
    db: Any,
) -> None:
    with tenant_scope("acad-a"):
        await MongoEmailPreferenceRepository(db).set_opt_outs(
            user_id="u-1",
            email="u-1@example.test",
            campaigns_opted_out=True,
            digests_opted_out=True,
            source="link",
        )

    gated = GatedEmailSendPort(inner=StubEmailSendPort(), preferences=MongoEmailPreferenceGate(db))
    recipient = ResolvedRecipient(user_id="u-1", email="u-1@example.test")

    with tenant_scope("acad-a"):
        blocked = await gated.send(
            recipient=recipient, subject="s", body="b", category=EmailCategory.CAMPAIGN
        )
    with tenant_scope("acad-b"):
        allowed = await gated.send(
            recipient=recipient, subject="s", body="b", category=EmailCategory.CAMPAIGN
        )

    assert blocked.suppressed is True
    assert allowed.ok is True, "an opt-out leaked across the tenant boundary"


@pytest.mark.asyncio
async def test_the_stored_row_carries_its_academy_id(db: Any) -> None:
    with tenant_scope("acad-a"):
        await MongoEmailPreferenceRepository(db).set_opt_outs(
            user_id="u-1",
            email="U-1@Example.TEST",
            campaigns_opted_out=True,
            digests_opted_out=False,
            source="portal",
        )

    doc = await db["email_preferences"].find_one({"user_id": "u-1"})
    assert doc is not None
    assert doc["academy_id"] == "acad-a"
    # Normalized for audit lookups.
    assert doc["email"] == "u-1@example.test"
    assert doc["opted_out_at"] is not None


@pytest.mark.asyncio
async def test_repeated_writes_converge_on_one_row(db: Any) -> None:
    repo = MongoEmailPreferenceRepository(db)
    with tenant_scope("acad-a"):
        for _ in range(3):
            await repo.set_opt_outs(
                user_id="u-1",
                email="u-1@example.test",
                campaigns_opted_out=True,
                digests_opted_out=True,
                source="link",
            )
    assert await db["email_preferences"].count_documents({"user_id": "u-1"}) == 1
