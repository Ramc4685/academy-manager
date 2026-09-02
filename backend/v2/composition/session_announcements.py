"""Session announcements — authoring, urgent fan-out and deletion (#614).

Lives in ``composition/`` for the same reason ``email_adapters.py`` and
``roster_notifications.py`` do: it needs ``shared.comms`` (the message store)
*and* ``contexts.communications`` (the audience resolver and the send port) at
once, and neither ``shared`` nor a context may reach across that line
(``tests/structural/test_layering.py``).

Three rules this module exists to keep true:

* **The portal write wins.** The announcement is stored first and the email is
  attempted afterwards, inside a ``try``. A provider outage downgrades an
  urgent post to a routine one that is still visible in every family's inbox;
  it never loses the post.
* **One delivery mechanism.** Urgent mail goes out through the same
  ``EmailSendPort`` built by ``digests._build_email_sender`` that the #612
  roster alerts and the #613 welcome email use — the single construction site
  that hands dev and CI a stub and only staging/prod the gated Resend adapter.
  There is no announcement-specific mailer.
* **Escaped at the boundary.** The body is stored raw (escaping is a render
  concern) and escaped here, once, when it is turned into HTML. The session
  title is escaped in both the subject and the heading.

Category is ``TRANSACTIONAL`` with both consequences taken deliberately: an
unsubscribe preference does not stop "class is cancelled tonight" because that
is operational rather than commercial, while a hard bounce or a spam complaint
still stops it because the mailbox is gone or hostile. Being outside the
unsubscribable set, it carries no CAN-SPAM footer — an unsubscribe link on a
message no preference can switch off would be a lie.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from backend.v2.composition.digests import _build_email_sender
from backend.v2.composition.email_adapters import _BRAND_HEADING, _branded_shell
from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    EmailSendPort,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.models import SessionAudience
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    MongoAudienceResolver,
)
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.comms import CommsService, Message
from backend.v2.shared.tenancy import current_academy_id

logger = logging.getLogger(__name__)

EmailStatus = Literal["skipped", "sent", "no_recipients", "failed"]


class SessionAnnouncementError(Exception):
    """Base for the errors the BFF routes translate into status codes."""


class SessionNotFound(SessionAnnouncementError):
    """No such session in this academy → 404."""


class AnnouncementNotFound(SessionAnnouncementError):
    """No such announcement on *this* session → 404."""


class AnnouncementDeleteForbidden(SessionAnnouncementError):
    """Actor is neither the author nor an admin → 403."""


class SessionLookup(Protocol):
    async def get(self, session_id: str) -> Session | None: ...


class AcademyNameLookup(Protocol):
    async def get_academy_name(self, academy_id: str) -> str | None: ...


class UserLookup(Protocol):
    async def get_by_id(self, user_id: str) -> Any | None: ...


@dataclass(frozen=True, slots=True)
class AnnouncementPostResult:
    """What was posted, and what the urgent fan-out actually achieved.

    ``sent_count``/``failed_count`` are surfaced all the way to the admin card
    on purpose. A suppressed or address-less family gets no email at all, and
    without the counts an admin would believe "class cancelled tonight" reached
    twelve families when it reached nine.
    """

    message: Message
    email_status: EmailStatus
    sent_count: int = 0
    failed_count: int = 0


def render_announcement_email(
    *,
    session_title: str,
    academy_name: str,
    author_display_name: str | None,
    body: str,
) -> tuple[str, str]:
    """Return ``(subject, html_body)`` for an urgent announcement.

    Every interpolated value is user-supplied, so every one of them is escaped
    here. Newlines become ``<br>`` *after* escaping, which is why a body
    containing ``<script>`` renders as text rather than as markup.
    """
    safe_title = html.escape(session_title)
    safe_body = html.escape(body).replace("\n", "<br>")
    parts = [
        f"<h2 style='color: {_BRAND_HEADING}; font-size: 18px; margin: 0 0 12px;'>"
        f"Announcement — {safe_title}</h2>",
        f"<p style='margin: 0 0 12px;'>{safe_body}</p>",
    ]
    if author_display_name:
        parts.append(
            f"<p style='margin: 24px 0 0; font-size: 13px;'>— "
            f"{html.escape(author_display_name)}</p>"
        )
    subject = f"{session_title}: announcement"
    return subject, _branded_shell(academy_name=academy_name, inner_html="".join(parts))


class SessionAnnouncementService:
    """Authoring surface behind the admin and coach announcement routes.

    Tenancy: the academy is read at *execution* time via
    ``current_academy_id()`` and never captured when this object is built; the
    repositories are tenant-scoped, so a session id from another academy simply
    does not resolve.
    """

    def __init__(
        self,
        *,
        comms: CommsService,
        sessions: SessionLookup,
        academies: AcademyNameLookup,
        users: UserLookup,
        audiences: AudienceResolver,
        sender: EmailSendPort,
    ) -> None:
        self._comms = comms
        self._sessions = sessions
        self._academies = academies
        self._users = users
        self._audiences = audiences
        self._sender = sender

    async def list_for_session(self, session_id: str) -> list[Message]:
        session = await self._sessions.get(session_id)
        if session is None:
            raise SessionNotFound(session_id)
        return await self._comms.list_session_announcements(session_id)

    async def post(
        self,
        *,
        session_id: str,
        author_id: str,
        author_persona: Literal["admin", "coach"],
        body: str,
        urgent: bool = False,
    ) -> AnnouncementPostResult:
        session = await self._sessions.get(session_id)
        if session is None:
            raise SessionNotFound(session_id)

        # Write first, mail second. If the fan-out raises, the announcement
        # still exists in every enrolled family's inbox and the caller is told
        # the email failed — the reverse order could email a class about a post
        # that was never stored.
        message = await self._comms.post_session_announcement(
            session_id=session_id,
            session_title=session.title,
            author_id=author_id,
            author_persona=author_persona,
            # Resolved here rather than taken from the route: `AuthClaims`
            # carries no display name, and the alternative the route *does*
            # have — the actor's email address — must not be stamped onto a
            # message every enrolled family can read.
            author_display_name=await self._author_name(author_id),
            body=body,
            urgency="urgent" if urgent else "routine",
        )
        if not urgent:
            return AnnouncementPostResult(message=message, email_status="skipped")

        try:
            return await self._fan_out(session=session, message=message)
        except Exception:
            logger.exception(
                "comms.session_announcement_fanout_failed",
                extra={"session_id": session_id, "message_id": message.message_id},
            )
            return AnnouncementPostResult(message=message, email_status="failed")

    async def delete(
        self,
        *,
        session_id: str,
        message_id: str,
        actor_id: str,
        actor_is_admin: bool,
    ) -> None:
        """Soft-delete one announcement. Author or admin only.

        The scope check is not redundant with the route's session guard: without
        it, an actor authorised on session A could delete an announcement
        belonging to session B just by supplying its message id.
        """
        message = await self._comms.get_message(message_id)
        if message is None or message.kind != "announcement" or message.scope_id != session_id:
            raise AnnouncementNotFound(message_id)
        if not actor_is_admin and message.sender_id != actor_id:
            raise AnnouncementDeleteForbidden(message_id)
        await self._comms.soft_delete_message(message_id, deleted_by=actor_id)

    async def _author_name(self, user_id: str) -> str | None:
        try:
            user = await self._users.get_by_id(user_id)
        except Exception:  # pragma: no cover - defensive
            return None
        name = str(getattr(user, "display_name", "") or "").strip()
        return name or None

    async def _fan_out(self, *, session: Session, message: Message) -> AnnouncementPostResult:
        recipients = [
            r
            for r in await self._audiences.resolve_session_audience(
                SessionAudience(session_id=session.session_id)
            )
            if (r.email or "").strip()
        ]
        if not recipients:
            # An empty class is a legitimate state, not a client error: the
            # announcement posts, and the caller is told nobody was mailed.
            return AnnouncementPostResult(message=message, email_status="no_recipients")

        academy_name = (
            await self._academies.get_academy_name(current_academy_id()) or "Your academy"
        )
        subject, body = render_announcement_email(
            session_title=session.title,
            academy_name=academy_name,
            author_display_name=message.author_display_name,
            body=message.body,
        )

        sent = failed = 0
        for recipient in recipients:
            outcome = await self._sender.send(
                recipient=recipient,
                subject=subject,
                body=body,
                category=EmailCategory.TRANSACTIONAL,
            )
            if outcome.ok:
                sent += 1
            else:
                failed += 1
        return AnnouncementPostResult(
            message=message,
            email_status="sent",
            sent_count=sent,
            failed_count=failed,
        )


def compose_announcements(
    db: Any,
    settings: Any,
    *,
    comms: CommsService,
    users: Any,
    sessions: Any = None,
) -> SessionAnnouncementService:
    """Build the service for a persona composition root.

    The send port comes from ``_build_email_sender`` — the one gate that keeps
    a local or CI stack on the stub adapter — so an admin or coach clicking
    "Urgent" in dev can never mail a real family.
    """
    return SessionAnnouncementService(
        comms=comms,
        sessions=sessions or MongoSessionRepository(db),
        academies=MongoAcademyRepository(db),
        users=users,
        audiences=MongoAudienceResolver(db=db),
        sender=_build_email_sender(settings, db),
    )
