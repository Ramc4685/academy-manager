"""Push for in-app messages (L11 item 4): a DM, an academy broadcast or a
routine class announcement nudges the recipients' phones.

Each kind is an opt-in event in the push catalogue, so nothing changes until
it is named in ``V2_PUSH_EXTRA_EVENTS`` (and ``PUSH_DELIVERY_ENABLED`` is on).
Broadcasts and announcements skip anyone who switched notifications off; a DM
is a one-to-one reply and always nudges its recipient. Never raises: the
message is already stored, and push is best effort.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    EmailPreferenceRepository,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.application.use_cases.send_push_to_user import (
    SendPushToUser,
)
from backend.v2.contexts.communications.domain.models import AcademyAudience, SessionAudience
from backend.v2.contexts.communications.domain.push_events import PushEvent
from backend.v2.shared.comms import Message
from backend.v2.shared.tenancy import current_academy_id

log = logging.getLogger(__name__)

_PREVIEW = 140
_PARENT_INBOX = "/parent/messages"


def _preview(body: str) -> str:
    text = " ".join(body.split())
    return text if len(text) <= _PREVIEW else text[: _PREVIEW - 1].rstrip() + "…"


@dataclass
class NotifyMessageByPush:
    push: SendPushToUser
    audiences: AudienceResolver
    preferences: EmailPreferenceRepository
    # (academy_id, user_id) -> the inbox that user's shell opens. DMs reach
    # coaches and staff as well as parents; broadcasts only reach parents.
    inbox_path: Callable[[str, str], Awaitable[str]]

    async def direct_message(self, message: Message) -> None:
        if not message.recipient_id or not self.push.allows(PushEvent.DIRECT_MESSAGE):
            return
        try:
            url = await self.inbox_path(current_academy_id(), message.recipient_id)
        except Exception:
            log.warning("message push inbox lookup failed", exc_info=True)
            url = _PARENT_INBOX
        await self._send(
            [message.recipient_id], PushEvent.DIRECT_MESSAGE, "New message", message.body, url
        )

    async def academy_broadcast(self, message: Message) -> None:
        if not self.push.allows(PushEvent.ACADEMY_BROADCAST):
            return
        await self._fan_out(
            lambda: self.audiences.resolve_academy_audience(AcademyAudience(role="parent")),
            PushEvent.ACADEMY_BROADCAST,
            "Announcement",
            message.body,
        )

    async def class_announcement(
        self, message: Message, *, session_id: str, session_title: str
    ) -> None:
        if not self.push.allows(PushEvent.CLASS_ANNOUNCEMENT):
            return
        await self._fan_out(
            lambda: self.audiences.resolve_session_audience(SessionAudience(session_id=session_id)),
            PushEvent.CLASS_ANNOUNCEMENT,
            session_title or "Class announcement",
            message.body,
        )

    async def _fan_out(
        self,
        resolve: Callable[[], Awaitable[list[ResolvedRecipient]]],
        event: PushEvent,
        title: str,
        body: str,
    ) -> None:
        try:
            recipients = await resolve()
            user_ids = []
            for r in recipients:
                prefs = await self.preferences.get(r.user_id)
                if prefs is None or not prefs.notifications_opted_out:
                    user_ids.append(r.user_id)
        except Exception:
            log.warning("message push audience lookup failed", exc_info=True)
            return
        # shortcut: sends inline in the request, one device lookup per person;
        # move to the background queue if academies grow past a few hundred.
        await self._send(list(dict.fromkeys(user_ids)), event, title, body, _PARENT_INBOX)

    async def _send(
        self, user_ids: list[str], event: PushEvent, title: str, body: str, url: str
    ) -> None:
        academy_id = current_academy_id()
        for user_id in user_ids:
            await self.push.execute(
                academy_id=academy_id,
                user_id=user_id,
                title=title,
                body=_preview(body),
                data={"url": url},
                event=event,
            )
