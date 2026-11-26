"""The academy inbox (D-18): which admin DMs join a family's shared thread.

Page-scoped so ``composition/admin.py`` (at its line budget) stays untouched.
The admin DM route asks this whether a recipient is a parent of the request's
academy; if so the reply is stamped into that family's thread, visible to every
admin, and carries the staff member's name for the other admins.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from backend.v2.composition.push import compose_roles_of

#: Roles a recipient may hold for a staff DM to join the shared family thread.
FAMILY_ROLES = frozenset({"parent", "student"})


@dataclass
class AcademyInbox:
    roles_of: Callable[[str, str], Awaitable[Sequence[str]]]
    users: Any  # MongoUserRepository: get_by_id(user_id) -> User | None

    async def thread_for(self, academy_id: str, recipient_id: str) -> str | None:
        """The academy-inbox thread a staff DM to ``recipient_id`` belongs to:
        the parent's own id, or ``None`` (the DM stays private to its two ends).

        Parent-only on purpose: a parent who is also a coach or staff member
        could be getting a private staff DM, and joining it to the shared
        thread would show it to every admin. Their own messages to the academy
        still land in the thread; staff replies to them stay private.
        """
        roles = set(await self.roles_of(academy_id, recipient_id))
        return recipient_id if "parent" in roles and roles <= FAMILY_ROLES else None

    async def staff_name(self, user_id: str) -> str | None:
        user = await self.users.get_by_id(user_id)
        name = str(getattr(user, "display_name", "") or "").strip()
        return name or None


def compose_academy_inbox(db: Any, settings: Any) -> AcademyInbox:
    from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository

    return AcademyInbox(roles_of=compose_roles_of(db, settings), users=MongoUserRepository(db))


#: Roles told by email that a family wrote to the academy inbox.
STAFF_ALERT_ROLES = ("admin", "owner")


class AcademyInboxStaffAlert:
    """Emails the academy's admins when a family starts writing (industry
    norm for a shared inbox: nobody should have to keep the tab open).

    One email per family per hour: only the first message of a burst alerts.
    The email names the family and never carries the message text, so what a
    parent writes (health details included) stays in the app.
    """

    def __init__(self, db: Any, sender: Any | None, *, window_hours: int = 1) -> None:
        from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
            MongoAudienceResolver,
        )
        from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
            MongoAcademyRepository,
        )
        from backend.v2.contexts.identity.infrastructure.mongo_user_repo import (
            MongoUserRepository,
        )
        from backend.v2.shared.comms import MongoMessageRepository

        self._db = db
        self._sender = sender
        self._window_hours = window_hours
        self._audiences = MongoAudienceResolver(db=db)
        self._academies = MongoAcademyRepository(db)
        self._users = MongoUserRepository(db)
        self._messages = MongoMessageRepository(db)

    async def _admin_ids(self, academy_id: str) -> list[str]:
        return [
            str(doc["user_id"])
            async for doc in self._db["academy_memberships"].find(
                {
                    "academy_id": academy_id,
                    "$or": [{"status": "active"}, {"status": {"$exists": False}}],
                    "roles": {"$in": list(STAFF_ALERT_ROLES)},
                },
                {"user_id": 1},
            )
            if doc.get("user_id")
        ]

    async def notify(self, message: Any) -> None:
        """Best effort, after the message is stored: a mail outage never costs
        the family their message."""
        import html
        import logging
        from datetime import timedelta

        from backend.v2.composition.email_adapters import _BRAND_HEADING, _branded_shell
        from backend.v2.contexts.communications.domain.email_category import EmailCategory
        from backend.v2.contexts.communications.domain.models import SelectedRecipientsAudience
        from backend.v2.shared.comms.sender_identity import sender_identity_for_current_academy

        if self._sender is None:
            return
        try:
            since = message.created_at - timedelta(hours=self._window_hours)
            if await self._messages.count_academy_inbox_sent(message.sender_id, since=since) > 1:
                return  # this family already alerted staff within the window
            admin_ids = await self._admin_ids(message.academy_id)
            if not admin_ids:
                return
            parent = await self._users.get_by_id(message.sender_id)
            family = str(getattr(parent, "display_name", "") or "").strip() or "A family"
            academy = await self._academies.find_by_id(message.academy_id) or {}
            academy_name = str(academy.get("display_name") or academy.get("name") or "Your academy")
            inner = (
                f"<h2 style='color: {_BRAND_HEADING}; font-size: 18px; margin: 0 0 12px;'>"
                f"New message from {html.escape(family)}</h2>"
                "<p style='margin: 0 0 12px;'>Open Messages in the admin app to read it and "
                "reply. Any admin can answer; the family sees the academy's name.</p>"
            )
            body = _branded_shell(academy_name=academy_name, inner_html=inner)
            identity = await sender_identity_for_current_academy(self._academies)
            recipients = await self._audiences.resolve_selected_audience(
                SelectedRecipientsAudience(user_ids=tuple(admin_ids))
            )
            for recipient in recipients:
                if not (recipient.email or "").strip():
                    continue
                await self._sender.send(
                    recipient=recipient,
                    subject=f"New message from {family}",
                    body=body,
                    category=EmailCategory.NOTIFICATION,
                    reply_to=identity.reply_to,
                    sender_name=identity.sender_name,
                )
        except Exception:
            logging.getLogger(__name__).warning("academy_inbox_staff_alert_failed", exc_info=True)


def compose_send_academy_message(
    db: Any, settings: Any, send_to_academy: Callable[..., Awaitable[Any]]
) -> Callable[..., Awaitable[Any]]:
    """The parent's send, followed by the staff email alert."""
    from backend.v2.composition.digests import _build_email_sender

    alert = AcademyInboxStaffAlert(db, _build_email_sender(settings, db))

    async def send(*, parent_id: str, body: str) -> Any:
        message = await send_to_academy(parent_id=parent_id, body=body)
        await alert.notify(message)
        return message

    send.alert = alert  # type: ignore[attr-defined]
    return send
