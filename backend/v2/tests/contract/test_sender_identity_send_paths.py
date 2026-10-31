"""Every non-billing send path passes the academy's sender identity (L9a).

A spy send port records the ``sender_name`` / ``reply_to`` each path hands
over. The academy lookup is keyed by academy id (as ``MongoAcademyRepository``
is) and holds TWO academies, so a path that read the wrong tenant would show
academy B's values on academy A's email.

Billing paths (invoice, dunning, autopay, dues reminders, add-card reminder)
are deliberately NOT wired here — see the L9a PR body for the follow-up list.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from backend.v2.composition.absence_notifications import AbsenceNoticeNotificationAdapter
from backend.v2.composition.digests import _AcademyBrandLookup
from backend.v2.composition.email_adapters import (
    LoginInviteEmailAdapter,
    build_user_facing_invite_sender,
)
from backend.v2.composition.hold_notifications import HoldNotificationAdapter
from backend.v2.composition.registration_decision_email import (
    RegistrationDecisionEmailAdapter,
)
from backend.v2.composition.roster_notifications import RosterAlertAdapter
from backend.v2.composition.session_announcements import SessionAnnouncementService
from backend.v2.composition.win_back import WinBackNotificationAdapter
from backend.v2.contexts.communications.application.ports import ResolvedRecipient, SendOutcome
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.comms.sender_identity import sender_identity_for_current_academy
from backend.v2.shared.tenancy import tenant_scope

A = "acad-alpha"
B = "acad-bravo"
DOCS: dict[str, dict[str, Any]] = {
    A: {
        "academy_id": A,
        "display_name": "Alpha Shuttle Club",
        "email_sender_name": "Alpha Front Desk",
        "email_reply_to": "desk@alpha.example.com",
    },
    B: {
        "academy_id": B,
        "display_name": "Bravo Racquet Club",
        "email_sender_name": "Bravo Front Desk",
        "email_reply_to": "desk@bravo.example.com",
    },
}
EXPECTED = {"sender_name": "Alpha Front Desk", "reply_to": "desk@alpha.example.com"}
FAMILY = ResolvedRecipient(user_id="parent-1", email="family@example.test", display_name="Pat")


class SpySender:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> SendOutcome:
        self.calls.append(kwargs)
        return SendOutcome(ok=True, provider_message_id="m-1", failed_reason=None)


class KeyedAcademies:
    """Mirrors ``MongoAcademyRepository``: lookups are keyed by academy id."""

    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None:
        doc = DOCS.get(academy_id)
        return dict(doc) if doc else None

    async def get_academy_name(self, academy_id: str) -> str | None:
        doc = DOCS.get(academy_id)
        return str(doc["display_name"]) if doc else None


class OneParentAudience:
    async def resolve_selected_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return [FAMILY]

    async def resolve_session_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return [FAMILY]


def _identity(call: dict[str, Any]) -> dict[str, Any]:
    return {"sender_name": call.get("sender_name"), "reply_to": call.get("reply_to")}


async def test_roster_alert_path() -> None:
    sender = SpySender()
    adapter = RosterAlertAdapter(
        sessions=None,  # type: ignore[arg-type]
        enrollments=None,  # type: ignore[arg-type]
        students=None,  # type: ignore[arg-type]
        academies=KeyedAcademies(),  # type: ignore[arg-type]
        audiences=None,  # type: ignore[arg-type]
        sender=sender,  # type: ignore[arg-type]
    )
    with tenant_scope(A):
        await adapter._send_one(
            recipient=FAMILY,
            subject="s",
            body="b",
            category=EmailCategory.TRANSACTIONAL,
            context={},
        )
    assert [_identity(c) for c in sender.calls] == [EXPECTED]


async def test_absence_notice_path() -> None:
    sender = SpySender()
    adapter = AbsenceNoticeNotificationAdapter(
        sessions=None,  # type: ignore[arg-type]
        academies=KeyedAcademies(),  # type: ignore[arg-type]
        policies=None,  # type: ignore[arg-type]
        audiences=None,  # type: ignore[arg-type]
        sender=sender,  # type: ignore[arg-type]
        notice_sends=None,  # type: ignore[arg-type]
    )
    with tenant_scope(A):
        await adapter._send_one(
            recipient=FAMILY,
            subject="s",
            body="b",
            category=EmailCategory.TRANSACTIONAL,
            context={},
        )
    assert [_identity(c) for c in sender.calls] == [EXPECTED]


async def test_session_announcement_path() -> None:
    sender = SpySender()
    service = SessionAnnouncementService(
        comms=None,  # type: ignore[arg-type]
        sessions=None,  # type: ignore[arg-type]
        academies=KeyedAcademies(),
        users=None,  # type: ignore[arg-type]
        audiences=OneParentAudience(),  # type: ignore[arg-type]
        sender=sender,  # type: ignore[arg-type]
    )
    session = SimpleNamespace(session_id="sess-1", title="Juniors")
    message = SimpleNamespace(author_display_name="Coach Synthetic", body="Court moved")
    with tenant_scope(A):
        await service._fan_out(session=session, message=message)  # type: ignore[arg-type]
    assert [_identity(c) for c in sender.calls] == [EXPECTED]


async def test_hold_notice_path() -> None:
    class NoticeSends:
        async def try_claim(self, **_: Any) -> dict[str, str]:
            return {"send_id": "send-1"}

        async def mark_sent(self, *_: Any) -> None:
            return None

        async def mark_failed(self, *_: Any, **__: Any) -> None:
            return None

    class Sessions:
        async def get(self, session_id: str) -> Any:
            return SimpleNamespace(session_id=session_id, title="Juniors")

    class Students:
        async def by_ids(self, ids: list[str]) -> list[Any]:
            return [SimpleNamespace(full_name="Sam Synthetic", parent_id="parent-1")]

    sender = SpySender()
    adapter = HoldNotificationAdapter(
        sessions=Sessions(),  # type: ignore[arg-type]
        students=Students(),  # type: ignore[arg-type]
        audiences=OneParentAudience(),  # type: ignore[arg-type]
        sender=sender,  # type: ignore[arg-type]
        notice_sends=NoticeSends(),  # type: ignore[arg-type]
        academies=KeyedAcademies(),
    )
    with tenant_scope(A):
        await adapter._send_claimed(
            enrollment_id="enr-1",
            notice_key="hold:1",
            session_id="sess-1",
            student_id="stu-1",
            build=lambda session, name: ("s", "b"),
        )
    assert [_identity(c) for c in sender.calls] == [EXPECTED]


async def test_win_back_path() -> None:
    class Students:
        async def by_ids(self, ids: list[str]) -> list[Any]:
            return [SimpleNamespace(full_name="Sam Synthetic")]

    sender = SpySender()
    adapter = WinBackNotificationAdapter(
        audiences=OneParentAudience(),
        students=Students(),
        sender=sender,  # type: ignore[arg-type]
        academies=KeyedAcademies(),
    )
    from datetime import UTC, datetime

    with tenant_scope(A):
        await adapter.win_back(
            student_id="stu-1",
            parent_id="parent-1",
            milestone_days=30,
            dropped_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
    assert [_identity(c) for c in sender.calls] == [EXPECTED]


async def test_registration_decision_path() -> None:
    sender = SpySender()
    adapter = RegistrationDecisionEmailAdapter(
        academies=KeyedAcademies(),
        sessions=None,  # type: ignore[arg-type]
        audiences=None,  # type: ignore[arg-type]
        sender=sender,  # type: ignore[arg-type]
    )
    with tenant_scope(A):
        await adapter._send(FAMILY, "s", "b", "app-1")
    assert [_identity(c) for c in sender.calls] == [EXPECTED]


async def test_login_invite_path() -> None:
    sender = SpySender()
    adapter = LoginInviteEmailAdapter(sender=sender, academies=KeyedAcademies())  # type: ignore[arg-type]
    with tenant_scope(A):
        await adapter.send_invite_email(
            user_id="parent-1",
            email="family@example.test",
            display_name="Pat",
            subject="s",
            body="b",
        )
    assert [_identity(c) for c in sender.calls] == [EXPECTED]


async def test_user_facing_invite_builder_threads_the_academy_lookup() -> None:
    sender = SpySender()
    adapter = build_user_facing_invite_sender(
        sender=sender,  # type: ignore[arg-type]
        env="local",
        real_email_envs=frozenset({"production"}),
        academies=KeyedAcademies(),
    )
    assert isinstance(adapter, LoginInviteEmailAdapter)
    with tenant_scope(A):
        await adapter.send_invite_email(
            user_id="u", email="family@example.test", display_name="Pat", subject="s", body="b"
        )
    assert [_identity(c) for c in sender.calls] == [EXPECTED]


async def test_login_invite_without_lookup_keeps_the_old_headers() -> None:
    sender = SpySender()
    adapter = LoginInviteEmailAdapter(sender=sender)  # type: ignore[arg-type]
    with tenant_scope(A):
        await adapter.send_invite_email(
            user_id="u", email="family@example.test", display_name="Pat", subject="s", body="b"
        )
    assert _identity(sender.calls[0]) == {"sender_name": None, "reply_to": None}


async def test_brand_lookup_carries_the_identity_for_digests_and_campaigns() -> None:
    lookup = _AcademyBrandLookup(KeyedAcademies())
    brand_a = await lookup.brand_for(A)
    brand_b = await lookup.brand_for(B)
    assert brand_a is not None and brand_b is not None
    assert (brand_a.sender_name, brand_a.reply_to) == (
        EXPECTED["sender_name"],
        EXPECTED["reply_to"],
    )
    assert brand_b.sender_name == "Bravo Front Desk"


async def test_paths_in_academy_b_never_carry_academy_a_values() -> None:
    sender = SpySender()
    adapter = LoginInviteEmailAdapter(sender=sender, academies=KeyedAcademies())  # type: ignore[arg-type]
    for academy in (A, B, A):
        with tenant_scope(academy):
            await adapter.send_invite_email(
                user_id="u", email="family@example.test", display_name="Pat", subject="s", body="b"
            )
    assert [c["sender_name"] for c in sender.calls] == [
        "Alpha Front Desk",
        "Bravo Front Desk",
        "Alpha Front Desk",
    ]
    assert [c["reply_to"] for c in sender.calls] == [
        "desk@alpha.example.com",
        "desk@bravo.example.com",
        "desk@alpha.example.com",
    ]


async def test_tenant_isolation_on_real_academy_repository(real_db: Any) -> None:
    """Same property against the real ``academies`` collection and repo."""
    await real_db["academies"].insert_many([dict(DOCS[A]), dict(DOCS[B])])
    repo = MongoAcademyRepository(real_db)

    with tenant_scope(A):
        a = await sender_identity_for_current_academy(repo)
    with tenant_scope(B):
        b = await sender_identity_for_current_academy(repo)
    with tenant_scope("acad-unknown"):
        unknown = await sender_identity_for_current_academy(repo)

    assert (a.sender_name, a.reply_to) == (EXPECTED["sender_name"], EXPECTED["reply_to"])
    assert (b.sender_name, b.reply_to) == ("Bravo Front Desk", "desk@bravo.example.com")
    assert (unknown.sender_name, unknown.reply_to) == (None, None)
