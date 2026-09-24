"""Registration outcome emails (issue #776).

Approval has had a family email since #613. Waitlisting and declining had
none — and declining *refunds money* — so the two outcomes that leave a family
waiting or out of pocket were the two that arrived as silence. This module is
the adapter behind ``AdminRegistrationReview``'s ``RegistrationDecisionNotifier``
port, plus the staff alert that fires when a new application reaches the review
queue in the first place.

It lives in ``composition/`` for the same reason ``enrollment_welcome_email``
does: it needs onboarding, communications and identity at once, which no single
bounded context may import.

Tenancy: the academy is read at *send* time via ``current_academy_id()`` and
staff recipients come from the tenant-scoped ``AudienceResolver``. The parent's
own address is taken from the application row the caller already read inside
the tenant scope.
"""

from __future__ import annotations

import html
import logging
from typing import Any, Protocol

from backend.v2.composition.email_adapters import _branded_shell
from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    SelectedRecipientsAudience,
)
from backend.v2.shared.comms.sender_identity import sender_identity_for_current_academy
from backend.v2.shared.tenancy import current_academy_id

logger = logging.getLogger(__name__)


class AcademyLookup(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...


class SessionLookup(Protocol):
    async def get(self, session_id: str) -> Any: ...


def _para(text: str) -> str:
    return f'<p style="margin:0 0 14px;line-height:1.5;">{html.escape(text)}</p>'


def render_waitlisted_email(
    *,
    academy_name: str,
    student_name: str,
    session_title: str | None,
    reason: str | None,
) -> tuple[str, str]:
    """Position is deliberately not quoted.

    The waitlist is re-ordered by promotions, skips and withdrawals between the
    decision and the moment the parent reads the mail, so a number here would
    be wrong more often than right — and a wrong number is what generates the
    phone call this email exists to prevent. What the family needs is the two
    facts that stay true: they hold a place, and they do not need to re-apply.
    """
    where = f" for {session_title}" if session_title else ""
    subject = f"{student_name} is on the waitlist{where}"
    inner = "".join(
        [
            f'<h2 style="margin:0 0 16px;">{html.escape(subject)}</h2>',
            _para(
                f"{student_name}'s registration has been reviewed and placed on the "
                f"waitlist{where}. The class is full right now."
            ),
            _para(
                "You do not need to do anything or register again. We contact "
                "waitlisted families in the order they joined as soon as a place "
                "opens up, and you will have time to confirm before the place is "
                "offered to anyone else."
            ),
            _para(f"Note from the academy: {reason}") if reason else "",
            _para("Reply to this email if you would like to be considered for a different class."),
        ]
    )
    return subject, _branded_shell(academy_name=academy_name, inner_html=inner)


def render_declined_email(
    *,
    academy_name: str,
    student_name: str,
    reason: str,
    refund_issued: bool,
) -> tuple[str, str]:
    subject = f"{student_name}'s registration could not be accepted"
    refund_line = (
        "Any payment taken at checkout has been refunded in full to the original "
        "card. Refunds normally appear on a statement within 5-10 business days."
        if refund_issued
        else "No payment was taken, so there is nothing to refund."
    )
    inner = "".join(
        [
            f'<h2 style="margin:0 0 16px;">{html.escape(subject)}</h2>',
            _para(f"We were not able to accept {student_name}'s registration."),
            _para(f"Reason: {reason}"),
            _para(refund_line),
            _para("Reply to this email if you would like help finding another class."),
        ]
    )
    return subject, _branded_shell(academy_name=academy_name, inner_html=inner)


def render_submitted_alert(
    *,
    academy_name: str,
    student_name: str,
    parent_name: str | None,
    session_title: str | None,
) -> tuple[str, str]:
    subject = f"New registration to review: {student_name}"
    where = session_title or "no class selected"
    inner = "".join(
        [
            f'<h2 style="margin:0 0 16px;">{html.escape(subject)}</h2>',
            _para(f"Student: {student_name}"),
            _para(f"Parent: {parent_name or 'unknown'}"),
            _para(f"Requested class: {where}"),
            _para("It is waiting in the admin Inbox under Registrations."),
        ]
    )
    return subject, _branded_shell(academy_name=academy_name, inner_html=inner)


class RegistrationDecisionEmailAdapter:
    """Implements ``RegistrationDecisionNotifier`` and the submit staff alert.

    Every method is best-effort by contract: callers invoke them only after the
    decision (or the transition) is already durable, and a send failure is
    logged, never raised.
    """

    def __init__(
        self,
        *,
        academies: AcademyLookup,
        sessions: SessionLookup,
        audiences: AudienceResolver,
        sender: EmailSendPort,
    ) -> None:
        self._academies = academies
        self._sessions = sessions
        self._audiences = audiences
        self._sender = sender

    async def registration_waitlisted(
        self,
        *,
        application_id: str,
        parent_user_id: str,
        parent_email: str | None,
        parent_name: str | None,
        student_name: str,
        session_id: str,
        reason: str | None,
    ) -> None:
        subject, body = render_waitlisted_email(
            academy_name=await self._academy_name(),
            student_name=student_name,
            session_title=await self._session_title(session_id),
            reason=reason,
        )
        await self._send_to_parent(
            application_id=application_id,
            parent_user_id=parent_user_id,
            parent_email=parent_email,
            parent_name=parent_name,
            subject=subject,
            body=body,
        )

    async def registration_declined(
        self,
        *,
        application_id: str,
        parent_user_id: str,
        parent_email: str | None,
        parent_name: str | None,
        student_name: str,
        reason: str,
        refund_issued: bool,
    ) -> None:
        subject, body = render_declined_email(
            academy_name=await self._academy_name(),
            student_name=student_name,
            reason=reason,
            refund_issued=refund_issued,
        )
        await self._send_to_parent(
            application_id=application_id,
            parent_user_id=parent_user_id,
            parent_email=parent_email,
            parent_name=parent_name,
            subject=subject,
            body=body,
        )

    async def registration_submitted(
        self,
        *,
        application_id: str,
        student_name: str,
        parent_name: str | None,
        session_id: str | None,
    ) -> None:
        """Tell the academy's staff a new application is waiting.

        Fans out to the academy's admins, so a registration that arrives at
        22:00 is not discovered days later by someone who happened to open the
        queue. Never raises: the application is already PENDING_APPROVAL and
        visible in the Inbox count whether or not this mail goes out.
        """
        subject, body = render_submitted_alert(
            academy_name=await self._academy_name(),
            student_name=student_name,
            parent_name=parent_name,
            session_title=await self._session_title(session_id) if session_id else None,
        )
        try:
            recipients = await self._audiences.resolve_academy_audience(
                AcademyAudience(role="admin")
            )
        except Exception:
            logger.exception(
                "registration.staff_alert_audience_failed",
                extra={"application_id": application_id},
            )
            return
        for recipient in recipients:
            if not (recipient.email or "").strip():
                continue
            await self._send(recipient, subject, body, application_id)

    async def _send_to_parent(
        self,
        *,
        application_id: str,
        parent_user_id: str,
        parent_email: str | None,
        parent_name: str | None,
        subject: str,
        body: str,
    ) -> None:
        resolved = await self._resolve_parent(parent_user_id)
        email = (parent_email or (resolved.email if resolved else "") or "").strip()
        if not email:
            logger.warning(
                "registration.decision_email_no_recipient",
                extra={"application_id": application_id, "parent_user_id": parent_user_id},
            )
            return
        display_name = parent_name or (resolved.display_name if resolved else None)
        await self._send(
            ResolvedRecipient(user_id=parent_user_id, email=email, display_name=display_name),
            subject,
            body,
            application_id,
        )

    async def _send(
        self,
        recipient: ResolvedRecipient,
        subject: str,
        body: str,
        application_id: str,
    ) -> None:
        identity = await sender_identity_for_current_academy(self._academies)
        outcome = await self._sender.send(
            recipient=recipient,
            subject=subject,
            body=body,
            # TRANSACTIONAL: the record of a decision the family asked for (and
            # in the decline case, of a refund). It still passes the #556
            # bounce/complaint gate but carries no unsubscribe footer.
            category=EmailCategory.TRANSACTIONAL,
            reply_to=identity.reply_to,
            sender_name=identity.sender_name,
        )
        if not outcome.ok and not outcome.suppressed:
            logger.warning(
                "registration.decision_email_failed",
                extra={"application_id": application_id, "reason": outcome.failed_reason},
            )

    async def _resolve_parent(self, parent_user_id: str) -> ResolvedRecipient | None:
        if not parent_user_id:
            return None
        try:
            resolved = await self._audiences.resolve_selected_audience(
                SelectedRecipientsAudience(user_ids=(parent_user_id,))
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "registration.decision_email_audience_failed",
                extra={"parent_user_id": parent_user_id},
            )
            return None
        return resolved[0] if resolved else None

    async def _academy_name(self) -> str:
        try:
            doc = await self._academies.find_by_id(current_academy_id()) or {}
        except Exception:  # pragma: no cover - defensive
            doc = {}
        return str(doc.get("display_name") or doc.get("name") or "") or "Your academy"

    async def _session_title(self, session_id: str) -> str | None:
        if not session_id:
            return None
        try:
            session = await self._sessions.get(session_id)
        except Exception:  # pragma: no cover - defensive
            return None
        title = str(getattr(session, "title", "") or "").strip()
        return title or None


def compose_registration_decision_notifier(
    db: Any,
    settings: Any,
) -> RegistrationDecisionEmailAdapter:
    """Build the adapter with the one gated send port the rest of the app uses.

    ``_build_email_sender`` is the single construction site that hands dev and
    CI the stub port and production the gated Resend one, so this adapter can
    never become the path that mails real families from a test stack.
    """
    from backend.v2.composition.digests import _build_email_sender
    from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
        MongoAudienceResolver,
    )
    from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
        MongoSessionRepository,
    )
    from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
        MongoAcademyRepository,
    )

    return RegistrationDecisionEmailAdapter(
        academies=MongoAcademyRepository(db),
        sessions=MongoSessionRepository(db),
        audiences=MongoAudienceResolver(db=db),
        sender=_build_email_sender(settings, db),
    )
