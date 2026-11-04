"""The inquiry-acknowledgement claim on a real ``mongod``.

``try_claim_acknowledgement`` matches ``{"acknowledged_at": None}``, which on
Mongo must also match a freshly inserted row where the field is absent;
mongomock would pass either way. Also pins the release (claim again after a
provider failure) and the per-address window. Skipped without a ``mongod``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from backend.v2.contexts.crm.domain.models import ContactConsent, CrmContact
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
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


async def test_first_claim_wins_release_reopens_and_the_address_window_sees_it(
    real_db: Any,
) -> None:
    repo = MongoCrmContactRepository(real_db)
    with tenant_scope(ACADEMY):
        await repo.add_if_absent(_contact("c1"))
        await repo.add_if_absent(_contact("c2"))
        assert "acknowledged_at" not in await real_db["crm_contacts"].find_one({"contact_id": "c1"})

        assert await repo.try_claim_acknowledgement("c1", at=NOW) is True
        assert await repo.try_claim_acknowledgement("c1", at=NOW) is False
        assert await repo.acknowledged_since("jamie@example.test", since=NOW - timedelta(days=1))
        assert not await repo.acknowledged_since(
            "jamie@example.test", since=NOW + timedelta(seconds=1)
        )

        await repo.release_acknowledgement("c1")
        assert not await repo.acknowledged_since(
            "jamie@example.test", since=NOW - timedelta(days=1)
        )
        assert await repo.try_claim_acknowledgement("c1", at=NOW) is True
    with tenant_scope("acad-other"):
        assert await repo.try_claim_acknowledgement("c1", at=NOW) is False
