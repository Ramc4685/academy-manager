"""Campaign audience preview (#1029): the count an admin sees before sending
comes from the same resolution the send uses, not from an enrollment count."""

from __future__ import annotations

from typing import Any

from mongomock_motor import AsyncMongoMockClient

from backend.v2.contexts.communications.application.use_cases.send_campaign import SendCampaign
from backend.v2.contexts.communications.domain.models import SessionAudience
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    MongoAudienceResolver,
)
from backend.v2.contexts.communications.infrastructure.mongo_campaign_repo import (
    MongoCampaignRepository,
)
from backend.v2.contexts.communications.infrastructure.mongo_delivery_repo import (
    MongoDeliveryRepository,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import (
    StubEmailSendPort,
)
from backend.v2.shared.tenancy.context import tenant_scope

A = "acad-1"


async def _seed_session(
    db: Any, session_id: str, families: dict[str, list[str]], *, academy_id: str = A
) -> None:
    """``families`` maps a parent suffix to the student suffixes it owns."""
    for parent, students in families.items():
        await db["users"].insert_one(
            {
                "academy_id": academy_id,
                "user_id": f"par-{parent}",
                "email": f"{parent}@example.test",
                "display_name": f"Parent {parent}",
            }
        )
        for student in students:
            await db["students"].insert_one(
                {
                    "academy_id": academy_id,
                    "student_id": f"stu-{student}",
                    "parent_id": f"par-{parent}",
                }
            )
            await db["enrollments"].insert_one(
                {
                    "academy_id": academy_id,
                    "enrollment_id": f"enr-{session_id}-{student}",
                    "session_id": session_id,
                    "student_id": f"stu-{student}",
                    "status": "active",
                }
            )


def _use_case(db: Any) -> SendCampaign:
    return SendCampaign(
        campaigns=MongoCampaignRepository(db),
        deliveries=MongoDeliveryRepository(db),
        resolver=MongoAudienceResolver(db=db),
        sender=StubEmailSendPort(),
    )


async def test_siblings_count_once_seven_families_not_eight_students() -> None:
    db = AsyncMongoMockClient()["preview-siblings"]
    # 8 students, 7 parents: one family has two children in the class.
    families = {f"p{i}": [f"s{i}"] for i in range(6)}
    families["p6"] = ["s6", "s7"]
    await _seed_session(db, "sess-1", families)

    with tenant_scope(A):
        preview = await _use_case(db).preview(SessionAudience(session_id="sess-1"))

    assert preview.recipient_count == 7
    assert preview.family_count == 7
    assert preview.contact_count == 0


async def test_twelve_one_child_families_count_twelve() -> None:
    db = AsyncMongoMockClient()["preview-twelve"]
    await _seed_session(db, "sess-1", {f"p{i}": [f"s{i}"] for i in range(12)})

    with tenant_scope(A):
        preview = await _use_case(db).preview(SessionAudience(session_id="sess-1"))

    assert (preview.recipient_count, preview.family_count) == (12, 12)


async def test_opted_in_contact_adds_a_recipient_not_a_family() -> None:
    db = AsyncMongoMockClient()["preview-contact"]
    await _seed_session(db, "sess-1", {"p0": ["s0"], "p1": ["s1"]})
    await db["family_contacts"].insert_one(
        {
            "academy_id": A,
            "contact_id": "c1",
            "parent_id": "par-p0",
            "name": "Second Parent",
            "email": "second@example.test",
            "gets_notices": True,
            "created_at": "1",
        }
    )

    with tenant_scope(A):
        preview = await _use_case(db).preview(SessionAudience(session_id="sess-1"))

    assert preview.recipient_count == 3
    assert preview.family_count == 2
    assert preview.contact_count == 1


async def test_preview_sends_nothing_and_records_nothing() -> None:
    db = AsyncMongoMockClient()["preview-readonly"]
    await _seed_session(db, "sess-1", {"p0": ["s0"]})
    sender = StubEmailSendPort()
    use_case = _use_case(db)
    use_case.sender = sender

    with tenant_scope(A):
        await use_case.preview(SessionAudience(session_id="sess-1"))

    assert await db["message_campaigns"].count_documents({}) == 0
    assert await db["message_deliveries"].count_documents({}) == 0
    assert sender.sent == []
