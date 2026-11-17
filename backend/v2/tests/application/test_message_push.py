"""Push for in-app messages (L11 items 4 and 5): DMs, academy broadcasts and
routine class announcements push only when their event is switched on, and
broadcasts/announcements skip people who turned notifications off."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.communications.application.ports import ResolvedRecipient
from backend.v2.contexts.communications.application.use_cases.notify_message_by_push import (
    NotifyMessageByPush,
)
from backend.v2.contexts.communications.application.use_cases.send_push_to_user import (
    SendPushToUser,
)
from backend.v2.contexts.communications.domain.email_preferences import EmailPreferences
from backend.v2.contexts.communications.domain.models import AcademyAudience, SessionAudience
from backend.v2.contexts.communications.domain.push_device import PushSendResult
from backend.v2.contexts.communications.domain.push_events import (
    ALWAYS_ON,
    PushEvent,
    enabled_push_events,
)
from backend.v2.shared.comms import Message
from backend.v2.shared.tenancy import tenant_scope


class _Devices:
    async def tokens_for_user(self, academy_id: str, user_id: str) -> list[str]:
        return [f"tok-{user_id}"]

    async def delete_tokens(self, academy_id: str, tokens: tuple[str, ...]) -> None:
        return None


class _Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[list[str], str]] = []
        self.urls: list[str] = []

    async def send(self, *, tokens: list[str], title: str, body: str, data: dict[str, str]):
        self.sent.append((tokens, body))
        self.urls.append(data["url"])
        return PushSendResult(attempted=len(tokens), sent=len(tokens))


class _Audiences:
    def __init__(self) -> None:
        self.calls = 0

    async def resolve_academy_audience(self, audience: AcademyAudience):
        self.calls += 1
        return [
            ResolvedRecipient(user_id="p1", email="a"),
            ResolvedRecipient(user_id="p2", email="b"),
        ]

    async def resolve_session_audience(self, audience: SessionAudience):
        self.calls += 1
        return [
            ResolvedRecipient(user_id="p1", email="a"),
            ResolvedRecipient(user_id="p2", email="b"),
        ]


class _Prefs:
    async def get(self, user_id: str) -> EmailPreferences | None:
        if user_id == "p2":
            return EmailPreferences(
                preference_id="x", user_id="p2", email="b", notifications_opted_out=True
            )
        return None


def _msg(kind: str = "announcement", recipient_id: str | None = None) -> Message:
    return Message(
        message_id="m1",
        academy_id="acad",
        kind=kind,  # type: ignore[arg-type]
        sender_id="admin",
        sender_persona="admin",
        recipient_id=recipient_id,
        body="Courts are closed tomorrow",
        created_at=datetime(2026, 11, 17, tzinfo=UTC),
    )


async def _parent_inbox(academy_id: str, user_id: str) -> str:
    return "/parent/messages"


def _notifier(extra: str) -> tuple[NotifyMessageByPush, _Sender, _Audiences]:
    sender, audiences = _Sender(), _Audiences()
    push = SendPushToUser(
        devices=_Devices(),  # type: ignore[arg-type]
        sender=sender,  # type: ignore[arg-type]
        enabled_events=enabled_push_events(extra),
    )
    notifier = NotifyMessageByPush(
        push=push,
        audiences=audiences,  # type: ignore[arg-type]
        preferences=_Prefs(),  # type: ignore[arg-type]
        inbox_path=_parent_inbox,
    )
    return notifier, sender, audiences


def test_catalogue_defaults_to_the_four_events_that_pushed_before() -> None:
    assert enabled_push_events("") == ALWAYS_ON
    assert enabled_push_events(" Direct_Message , bogus") == ALWAYS_ON | {PushEvent.DIRECT_MESSAGE}


async def test_nothing_pushes_and_no_audience_is_read_while_events_are_off() -> None:
    notifier, sender, audiences = _notifier("")
    with tenant_scope("acad"):
        await notifier.direct_message(_msg("dm", recipient_id="p1"))
        await notifier.academy_broadcast(_msg())
        await notifier.class_announcement(_msg(), session_id="s1", session_title="Juniors")
    assert sender.sent == []
    assert audiences.calls == 0


async def test_dm_pushes_to_its_recipient() -> None:
    notifier, sender, _ = _notifier("direct_message")
    with tenant_scope("acad"):
        await notifier.direct_message(_msg("dm", recipient_id="p1"))
    assert sender.sent == [(["tok-p1"], "Courts are closed tomorrow")]


async def test_broadcast_and_class_announcement_skip_people_who_opted_out() -> None:
    notifier, sender, _ = _notifier("academy_broadcast,class_announcement")
    with tenant_scope("acad"):
        await notifier.academy_broadcast(_msg())
        await notifier.class_announcement(_msg(), session_id="s1", session_title="Juniors")
    assert [tokens for tokens, _ in sender.sent] == [["tok-p1"], ["tok-p1"]]


async def test_legacy_callers_without_an_event_still_push() -> None:
    sender = _Sender()
    push = SendPushToUser(devices=_Devices(), sender=sender)  # type: ignore[arg-type]
    await push.execute(academy_id="acad", user_id="p1", title="t", body="b")
    assert len(sender.sent) == 1


async def test_dm_push_opens_the_recipients_own_inbox() -> None:
    from backend.v2.composition.push import message_inbox_path

    notifier, sender, _ = _notifier("direct_message,academy_broadcast")
    roles = {"coach1": ("coach",), "p1": ("parent", "coach"), "staff": ("billing",)}

    async def inbox_path(academy_id: str, user_id: str) -> str:
        assert academy_id == "acad"
        return message_inbox_path(roles[user_id])

    notifier.inbox_path = inbox_path
    with tenant_scope("acad"):
        for who in ("coach1", "p1", "staff"):
            await notifier.direct_message(_msg("dm", recipient_id=who))
        await notifier.academy_broadcast(_msg())
    assert sender.urls == [
        "/coach/messages",
        "/parent/messages",
        "/admin/messages",
        "/parent/messages",
    ]
