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
    await db["sessions"].update_one(
        {"academy_id": academy_id, "session_id": session_id},
        {"$set": {"title": session_id}},
        upsert=True,
    )
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


# --- #1031: recipient review, exclusions, changed-audience guard ----------------


class _Gate:
    """Mirrors the real gates: never raises, refuses with a reason string."""

    def __init__(self, refused: dict[str, str]) -> None:
        self.refused = refused

    async def check(self, *, recipient_user_id: str, email: str, category: Any) -> Any:
        from backend.v2.contexts.communications.application.send_gate import ALLOW, GateVerdict

        reason = self.refused.get(email)
        return GateVerdict(allowed=False, reason=reason) if reason else ALLOW


async def test_preview_lists_recipients_and_explains_every_exclusion() -> None:
    db = AsyncMongoMockClient()["preview-exclusions"]
    await _seed_session(db, "sess-1", {"p0": ["s0"], "p1": ["s1"], "p2": ["s2"], "p3": ["s3"]})
    # p1 has no address; p4 shares p0's address under another account.
    await db["users"].update_one({"user_id": "par-p1"}, {"$unset": {"email": ""}})
    await _seed_session(db, "sess-1", {"p4": ["s4"]})
    await db["users"].update_one({"user_id": "par-p4"}, {"$set": {"email": "P0@example.test"}})
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
    use_case = _use_case(db)
    use_case.gates = (
        _Gate({"p2@example.test": "suppressed:hard_bounce"}),
        _Gate({"p3@example.test": "unsubscribed:campaign"}),
    )

    with tenant_scope(A):
        preview = await use_case.preview(SessionAudience(session_id="sess-1"))

    assert [(r.email, r.is_family_contact) for r in preview.recipients] == [
        ("p0@example.test", False),
        ("second@example.test", True),
    ]
    assert (preview.recipient_count, preview.family_count, preview.contact_count) == (2, 1, 1)
    reasons = {(e.display_name, e.reason) for e in preview.exclusions}
    assert reasons == {
        ("Parent p1", "missing_email"),
        ("Parent p4", "duplicate_address"),
        ("Parent p2", "suppressed"),
        ("Parent p3", "unsubscribed"),
    }


async def test_preview_never_includes_another_academys_roster() -> None:
    db = AsyncMongoMockClient()["preview-tenancy"]
    await _seed_session(db, "sess-1", {"p0": ["s0"]})
    await _seed_session(db, "sess-1", {"x0": ["x0"]}, academy_id="acad-2")

    with tenant_scope(A):
        preview = await _use_case(db).preview(SessionAudience(session_id="sess-1"))

    assert [r.email for r in preview.recipients] == ["p0@example.test"]


async def test_send_refuses_when_the_audience_changed_since_preview() -> None:
    from backend.v2.contexts.communications.application.use_cases.send_campaign import (
        SendCampaignCommand,
    )
    from backend.v2.contexts.communications.domain.errors import AudienceChangedError

    db = AsyncMongoMockClient()["preview-changed"]
    await _seed_session(db, "sess-1", {"p0": ["s0"]})
    sender = StubEmailSendPort()
    use_case = _use_case(db)
    use_case.sender = sender
    audience = SessionAudience(session_id="sess-1")

    with tenant_scope(A):
        seen = await use_case.preview(audience)
        # A family joins between the review and the send.
        await _seed_session(db, "sess-1", {"p1": ["s1"]})
        command = SendCampaignCommand(
            academy_id=A,
            sender_id="admin-1",
            audience=audience,
            subject="Hi",
            body="Hello",
            expected_audience_fingerprint=seen.audience_fingerprint,
        )
        try:
            await use_case.execute(command)
        except AudienceChangedError:
            pass
        else:  # pragma: no cover - the assertion below names the failure
            raise AssertionError("a changed audience must be re-reviewed")
        assert sender.sent == []
        assert await db["message_campaigns"].count_documents({}) == 0

        fresh = await use_case.preview(audience)
        assert fresh.audience_fingerprint != seen.audience_fingerprint
        result = await use_case.execute(
            SendCampaignCommand(
                academy_id=A,
                sender_id="admin-1",
                audience=audience,
                subject="Hi",
                body="Hello",
                expected_audience_fingerprint=fresh.audience_fingerprint,
            )
        )
    assert result.sent_count == 2


async def test_send_uses_the_same_resolution_it_checked() -> None:
    """Codex P2 on #1222: checking the fingerprint against one resolution and
    building deliveries from a second could email a roster nobody reviewed."""
    from backend.v2.contexts.communications.application.ports import ResolvedRecipient
    from backend.v2.contexts.communications.application.use_cases.send_campaign import (
        SendCampaignCommand,
    )

    db = AsyncMongoMockClient()["preview-one-resolution"]
    await _seed_session(db, "sess-1", {"p0": ["s0"]})
    audience = SessionAudience(session_id="sess-1")
    use_case = _use_case(db)
    sender = StubEmailSendPort()
    use_case.sender = sender

    with tenant_scope(A):
        seen = await use_case.preview(audience)

    real = use_case.resolver
    calls = 0

    class _ChangesOnSecondResolve:
        async def resolve_session_audience(self, aud):  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            rows = await real.resolve_session_audience(aud)
            if calls > 1:  # the roster changes right after the check
                rows = [
                    *rows,
                    ResolvedRecipient(
                        user_id="late", email="late@example.test", display_name="Late"
                    ),
                ]
            return rows

    use_case.resolver = _ChangesOnSecondResolve()  # type: ignore[assignment]
    with tenant_scope(A):
        result = await use_case.execute(
            SendCampaignCommand(
                academy_id=A,
                sender_id="admin-1",
                audience=audience,
                subject="Hi",
                body="Hello",
                expected_audience_fingerprint=seen.audience_fingerprint,
            )
        )

    assert calls == 1
    assert result.sent_count == 1
    assert [sent["email"] for sent in sender.sent] == ["p0@example.test"]


def test_composed_campaign_preview_consults_the_senders_own_gates() -> None:
    from types import SimpleNamespace

    from backend.v2.composition.digests import compose_send_campaign
    from backend.v2.contexts.communications.infrastructure.gated_send_port import (
        GatedEmailSendPort,
    )

    suppressions, preferences = _Gate({}), _Gate({})
    sender = GatedEmailSendPort(
        inner=StubEmailSendPort(), suppressions=suppressions, preferences=preferences
    )
    db = AsyncMongoMockClient()["preview-compose"]
    use_case = compose_send_campaign(db, sender, SimpleNamespace())
    assert tuple(use_case.gates) == (suppressions, preferences)


# --- #1030: one campaign, several sessions ------------------------------------


async def _seed_two_overlapping_sessions(db: Any) -> None:
    # p0 has a child in each session; p1 only in sess-1; p2 only in sess-2;
    # p3's contact shares p2's contact address.
    await _seed_session(db, "sess-1", {"p0": ["a0"], "p1": ["a1"]})
    await _seed_session(db, "sess-2", {"p2": ["b2"]})
    await db["students"].insert_one({"academy_id": A, "student_id": "b0", "parent_id": "par-p0"})
    await db["enrollments"].insert_one(
        {
            "academy_id": A,
            "enrollment_id": "enr-sess-2-b0",
            "session_id": "sess-2",
            "student_id": "b0",
            "status": "active",
        }
    )
    await db["family_contacts"].insert_many(
        [
            {
                "academy_id": A,
                "contact_id": "c1",
                "parent_id": "par-p1",
                "name": "Grandparent",
                "email": "gran@example.test",
                "gets_notices": True,
                "created_at": "1",
            },
            {
                "academy_id": A,
                "contact_id": "c2",
                "parent_id": "par-p2",
                "name": "Same Gran",
                "email": "GRAN@example.test",
                "gets_notices": True,
                "created_at": "2",
            },
        ]
    )
    # Another academy reuses the same session id; never part of this audience.
    await _seed_session(db, "sess-2", {"x9": ["x9"]}, academy_id="acad-2")


async def test_two_sessions_send_one_copy_per_address_within_the_academy() -> None:
    from backend.v2.contexts.communications.application.use_cases.send_campaign import (
        SendCampaignCommand,
    )
    from backend.v2.contexts.communications.domain.models import SessionsAudience

    db = AsyncMongoMockClient()["preview-two-sessions"]
    await _seed_two_overlapping_sessions(db)
    sender = StubEmailSendPort()
    use_case = _use_case(db)
    use_case.sender = sender
    audience = SessionsAudience(session_ids=("sess-1", "sess-2"))

    with tenant_scope(A):
        preview = await use_case.preview(audience)
        result = await use_case.execute(
            SendCampaignCommand(
                academy_id=A, sender_id="admin-1", audience=audience, subject="S", body="B"
            )
        )

    expected = {"p0@example.test", "p1@example.test", "p2@example.test", "gran@example.test"}
    assert {r.email for r in preview.recipients} == expected
    assert (preview.recipient_count, preview.family_count, preview.contact_count) == (4, 3, 1)
    sent = [s["email"].lower() for s in sender.sent]
    assert sorted(sent) == sorted(expected)
    assert result.sent_count == 4


async def test_unknown_or_other_academy_session_is_rejected() -> None:
    import pytest

    from backend.v2.contexts.communications.domain.errors import InvalidAudienceError
    from backend.v2.contexts.communications.domain.models import SessionsAudience

    db = AsyncMongoMockClient()["preview-foreign-session"]
    await _seed_session(db, "sess-1", {"p0": ["s0"]})
    await db["sessions"].insert_one({"academy_id": "acad-2", "session_id": "sess-foreign"})

    with tenant_scope(A), pytest.raises(InvalidAudienceError):
        await _use_case(db).preview(SessionsAudience(session_ids=("sess-1", "sess-foreign")))


def test_sessions_audience_round_trips_and_refuses_empty() -> None:
    import pytest

    from backend.v2.contexts.communications.domain.errors import InvalidAudienceError
    from backend.v2.contexts.communications.domain.models import (
        SessionsAudience,
        audience_descriptor,
        parse_audience,
    )

    audience = SessionsAudience(session_ids=("sess-1", "sess-2"))
    assert parse_audience(audience_descriptor(audience)) == audience
    with pytest.raises(InvalidAudienceError):
        SessionsAudience(session_ids=())
