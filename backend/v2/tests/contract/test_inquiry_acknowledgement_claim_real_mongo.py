"""The inquiry-acknowledgement claims on a real ``mongod``.

``try_claim_acknowledgement`` matches ``{"acknowledged_at": None}``, which on
Mongo must also match a freshly inserted row where the field is absent;
mongomock would pass either way. The per-inbox claim leans on the unique
``(academy_id, mailbox, day)`` index from migration 0217, which only a real
server enforces under a race: two concurrent submissions for spellings of one
inbox must yield exactly one winner. Skipped without a ``mongod``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.v2.contexts.crm.domain.models import (
    ContactConsent,
    CrmContact,
    canonical_mailbox,
)
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.contexts.crm.infrastructure.mongo_inquiry_ack_throttle_repo import (
    MongoInquiryAckThrottleRepository,
)
from backend.v2.shared.tenancy import tenant_scope

ACADEMY = "acad-ack-claim"
NOW = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)


def _contact(contact_id: str) -> CrmContact:
    return CrmContact(
        contact_id=contact_id,
        academy_id=ACADEMY,
        name="Jamie Testparent",
        email="jamie@example.test",
        source="website",
        pipeline_status="trial",
        consent=ContactConsent(contact_about_request=True, captured_at=NOW),
        created_at=NOW,
        updated_at=NOW,
    )


async def test_first_contact_claim_wins_and_release_reopens(real_db: Any) -> None:
    repo = MongoCrmContactRepository(real_db)
    with tenant_scope(ACADEMY):
        await repo.add_if_absent(_contact("c1"))
        assert "acknowledged_at" not in await real_db["crm_contacts"].find_one({"contact_id": "c1"})

        assert await repo.try_claim_acknowledgement("c1", at=NOW) is True
        assert await repo.try_claim_acknowledgement("c1", at=NOW) is False
        await repo.release_acknowledgement("c1")
        assert await repo.try_claim_acknowledgement("c1", at=NOW) is True
    with tenant_scope("acad-other"):
        assert await repo.try_claim_acknowledgement("c1", at=NOW) is False


async def test_concurrent_claims_for_spellings_of_one_inbox_have_exactly_one_winner(
    real_db: Any,
) -> None:
    repo = MongoInquiryAckThrottleRepository(real_db)
    spellings = [
        "victim@gmail.com",
        "Victim+1@gmail.com",
        "v.i.c.t.i.m@gmail.com",
        "vic.tim+promo@GoogleMail.com",
    ] * 3
    with tenant_scope(ACADEMY):
        wins = await asyncio.gather(
            *(repo.try_claim(canonical_mailbox(s) or "", at=NOW) for s in spellings)
        )
        assert sum(wins) == 1
        assert await real_db["crm_inquiry_ack_throttle"].count_documents({}) == 1
        assert await repo.count_since(NOW - timedelta(hours=1)) == 1

        # The next UTC day is a new claim; a release gives today's back.
        assert await repo.try_claim("victim@gmail.com", at=NOW + timedelta(days=1)) is True
        await repo.release("victim@gmail.com", at=NOW)
        assert await repo.try_claim("victim@gmail.com", at=NOW) is True
    with tenant_scope("acad-other"):
        assert await repo.try_claim("victim@gmail.com", at=NOW) is True
        assert await repo.count_since(NOW - timedelta(hours=1)) == 1
