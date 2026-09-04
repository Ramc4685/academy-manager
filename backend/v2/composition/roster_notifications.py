"""Roster-change alerts for staff, and the seat-opened email for a family (#612).

The sibling of ``enrollment_welcome_email.py`` (#613) and built on exactly the
same mechanism, deliberately: a narrow one-method Protocol in the enrollment
application layer (``RosterChangeNotifier``), the adapter that renders and
sends here in ``composition/``, because a context may never import another
context (``tests/structural/test_layering.py``). There is no second delivery
pipeline for enrollment mail — the welcome email and the roster alert are two
adapters over the same ``EmailSendPort``, the same brand shell and the same
send-time gates.

Three rules this module exists to keep true:

* **The write wins.** Every call site invokes the port last and swallows
  everything it raises. Nothing here may turn a mail outage into a failed
  cancellation.
* **Session timezone, with the zone printed.** The alert quotes a class time,
  so it inherits #541/#604. Recurring sessions already store local wall-clock
  strings and need no conversion; a dated session is converted into the
  session's own zone. The zone *name* is always printed — prod has sessions
  stamped ``UTC`` under an America/Chicago academy, and printing the zone
  makes that data bug visible instead of silently shifting a class by hours.
* **Staff alerts are NOTIFICATION, the family's email is TRANSACTIONAL.** A
  coach may switch roster pings off (the category is unsubscribable and every
  body carries the footer). A family being told their child took a waitlisted
  seat is the record of that family's own enrollment and carries no footer,
  exactly like the invoice and welcome adapters.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from backend.v2.composition.digests import (
    _build_email_sender,
    compose_unsubscribe_link_builder,
)
from backend.v2.composition.email_adapters import (
    _BRAND_HEADING,
    _branded_button,
    _branded_shell,
)
from backend.v2.composition.enrollment_welcome_email import (
    EnrollmentWelcomeEmailAdapter,
    format_session_when,
)
from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.application.unsubscribe_footer import (
    append_unsubscribe_footer,
)
from backend.v2.contexts.communications.application.unsubscribe_token import (
    UnsubscribeLinkBuilder,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    AudienceRole,
    CoachAudience,
)
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    MongoAudienceResolver,
)
from backend.v2.contexts.enrollment.application.ports import RosterChangeKind
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.tenancy.academy_url import academy_frontend_url

logger = logging.getLogger(__name__)

#: Printed instead of a plausible-but-wrong local time when neither the session
#: nor the academy has a zone. A named zone the reader can sanity-check beats a
#: number they cannot.
_NO_TIMEZONE = "timezone not set"

#: Staff roster alerts go to the session's coach plus everyone who runs the
#: academy. ``owner`` is here because an owner-only academy has no admins.
_STAFF_ROLES: tuple[AudienceRole, ...] = ("admin", "owner")

_HEADLINES: dict[RosterChangeKind, str] = {
    "approved": "{student} was approved into {session}",
    "added": "{student} was added to {session}",
    "promoted": "{student} moved off the waitlist into {session}",
    "moved": "{student} moved to {session}",
    "cancelled": "{student} left {session}",
    "withdrawn": "{student} withdrew from {session}",
    "paused": "{student} paused {session}",
    "resumed": "{student} is back in {session}",
    "session_cancelled": "{session} was cancelled for {student}",
}


class SessionLookup(Protocol):
    async def get(self, session_id: str) -> Session | None: ...


class RosterCountQuery(Protocol):
    async def active_for_session(self, session_id: str) -> list[Any]: ...


class StudentLookup(Protocol):
    async def by_ids(self, student_ids: list[str]) -> list[Any]: ...


class AcademyLookup(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...


def _para(text: str) -> str:
    return f"<p style='margin: 0 0 12px;'>{text}</p>"


def format_session_schedule(session: Session, *, academy_timezone: str | None = None) -> str:
    """The class's wall clock with its zone named.

    Delegates the clock itself to the #613 renderer so the welcome email and
    the roster alert can never disagree about when a class runs, then appends
    the zone. ``Session.start_at`` is never formatted for a recurring template
    — ``MongoSessionRepository._representative_template_times`` synthesises it
    as the *next* matching occurrence counted from today, so it is a rolling
    value rather than this enrollment's date; ``format_session_when`` uses the
    stored ``days_of_week``/``start_time`` whenever they are present.
    """
    when = format_session_when(session, academy_timezone=academy_timezone)
    zone = (session.timezone or academy_timezone or "").strip() or _NO_TIMEZONE
    return f"{when} ({zone})"


def render_roster_alert(
    *,
    change: RosterChangeKind,
    session: Session,
    academy_name: str,
    student_name: str,
    active_count: int,
    academy_timezone: str | None = None,
    other_session_title: str | None = None,
    actor_name: str | None = None,
) -> tuple[str, str]:
    """Return ``(subject, html_body)`` for the staff alert, footer excluded.

    The footer is appended per recipient (each carries its own unsubscribe
    token), so the body is rendered once per event rather than once per person.
    """
    safe_student = html.escape(student_name)
    safe_session = html.escape(session.title)
    headline = _HEADLINES[change].format(student=safe_student, session=safe_session)

    parts = [
        f"<h2 style='color: {_BRAND_HEADING}; font-size: 18px; margin: 0 0 12px;'>{headline}</h2>",
        _para(
            f"<strong>When:</strong> "
            f"{html.escape(format_session_schedule(session, academy_timezone=academy_timezone))}"
        ),
    ]
    if session.location:
        parts.append(_para(f"<strong>Where:</strong> {html.escape(session.location)}"))
    if change == "moved" and other_session_title:
        parts.append(_para(f"<strong>Moved from:</strong> {html.escape(other_session_title)}"))
    # The active roster count, never `reserved_seats`: that counter has a known
    # drift history in this codebase, and `WithdrawEnrollment` does not release
    # a seat at all, so the two diverge on every withdrawal.
    parts.append(
        _para(f"<strong>Roster now:</strong> {active_count} of {session.capacity} enrolled")
    )
    if actor_name:
        parts.append(_para(f"<strong>Changed by:</strong> {html.escape(actor_name)}"))

    subject = f"{student_name} — {_SUBJECT_VERBS[change]} {session.title}"
    return subject, _branded_shell(academy_name=academy_name, inner_html="".join(parts))


_SUBJECT_VERBS: dict[RosterChangeKind, str] = {
    "approved": "approved into",
    "added": "added to",
    "promoted": "promoted into",
    "moved": "moved to",
    "cancelled": "left",
    "withdrawn": "withdrew from",
    "paused": "paused",
    "resumed": "resumed",
    "session_cancelled": "class cancelled:",
}


_PARENT_STATUS_CHANGES: frozenset[str] = frozenset(
    {"cancelled", "withdrawn", "paused", "resumed", "session_cancelled"}
)

_PARENT_STATUS_COPY: dict[str, tuple[str, str]] = {
    "cancelled": (
        "Enrollment cancelled",
        "{student}'s enrollment in {session} has been cancelled. The current month "
        "stays as invoiced; no further months will be billed.",
    ),
    "withdrawn": (
        "Enrollment withdrawn",
        "{student} has been withdrawn from {session}. The current month stays as "
        "invoiced; no further months will be billed.",
    ),
    "paused": (
        "Enrollment paused",
        "{student}'s enrollment in {session} is paused. Billing stops for the "
        "paused months and the seat is released; ask the academy to resume any time.",
    ),
    "resumed": (
        "Enrollment resumed",
        "{student} is back in {session}. Monthly billing resumes from the next billing day.",
    ),
    "session_cancelled": (
        "Class cancelled",
        "{session} has been cancelled by the academy, so {student}'s enrollment has "
        "ended. No further months will be billed.",
    ),
}


def render_parent_status_email(
    *,
    change: RosterChangeKind,
    session: Session,
    academy_name: str,
    student_name: str,
    portal_url: str | None,
    academy_timezone: str | None,
) -> tuple[str, str]:
    """``(subject, html_body)`` telling a family their child's status changed (#651)."""
    heading, template = _PARENT_STATUS_COPY[change]
    text = template.format(student=html.escape(student_name), session=html.escape(session.title))
    parts = [
        f"<h2 style='font-size: 18px; margin: 0 0 12px;'>{heading}</h2>",
        _para(text),
        _para(
            f"Schedule: {html.escape(format_session_schedule(session, academy_timezone=academy_timezone))}"
        ),
    ]
    if portal_url:
        parts.append(_para(f"<a href='{html.escape(portal_url)}'>Open the parent portal</a>"))
    subject = f"{heading}: {student_name} — {session.title}"
    return subject, _branded_shell(academy_name=academy_name, inner_html="".join(parts))


def render_seat_opened_email(
    *,
    session: Session,
    academy_name: str,
    student_name: str,
    portal_url: str | None,
    academy_timezone: str | None = None,
) -> tuple[str, str]:
    """The family's "a seat opened and it is yours" email (#612, Phase 2)."""
    safe_student = html.escape(student_name)
    safe_session = html.escape(session.title)
    parts = [
        f"<h2 style='color: {_BRAND_HEADING}; font-size: 18px; margin: 0 0 12px;'>"
        f"A seat opened — {safe_student} is enrolled in {safe_session}</h2>",
        _para(
            f"{safe_student} was next on the waitlist for {safe_session} and now "
            f"has a place in the class."
        ),
        _para(
            f"<strong>When:</strong> "
            f"{html.escape(format_session_schedule(session, academy_timezone=academy_timezone))}"
        ),
    ]
    if session.location:
        parts.append(_para(f"<strong>Where:</strong> {html.escape(session.location)}"))
    if portal_url:
        parts.append(_branded_button(label="View the enrollment", url=portal_url))
    return (
        f"{student_name} has a seat in {session.title}",
        _branded_shell(academy_name=academy_name, inner_html="".join(parts)),
    )


class RosterAlertAdapter:
    """Implements enrollment's ``RosterChangeNotifier``.

    Tenancy: the academy is read at *execution* time via
    ``current_academy_id()`` and never captured at composition time — the
    #532-class trap. Every repository here is tenant-scoped, so recipients can
    only ever come from the academy whose request is running.
    """

    def __init__(
        self,
        *,
        sessions: SessionLookup,
        enrollments: RosterCountQuery,
        students: StudentLookup,
        academies: AcademyLookup,
        audiences: AudienceResolver,
        sender: EmailSendPort,
        unsubscribe_links: UnsubscribeLinkBuilder | None = None,
    ) -> None:
        self._sessions = sessions
        self._enrollments = enrollments
        self._students = students
        self._academies = academies
        self._audiences = audiences
        self._sender = sender
        self._unsubscribe_links = unsubscribe_links or UnsubscribeLinkBuilder()

    async def roster_changed(
        self,
        *,
        change: RosterChangeKind,
        session_id: str,
        student_id: str,
        student_name: str | None = None,
        enrollment_id: str | None = None,
        from_session_id: str | None = None,
        to_session_id: str | None = None,
        actor_id: str | None = None,
        parent_user_id: str | None = None,
    ) -> None:
        academy_id = current_academy_id()
        session = await self._sessions.get(session_id)
        if session is None:
            logger.warning(
                "enrollment.roster_alert_session_missing",
                extra={"session_id": session_id, "change": change},
            )
            return

        academy_doc = await self._academies.find_by_id(academy_id) or {}
        academy_name = str(academy_doc.get("display_name") or academy_doc.get("name") or "") or (
            "Your academy"
        )
        academy_timezone = str(academy_doc.get("timezone") or "") or None
        academy_slug = str(academy_doc.get("slug") or "") or None

        resolved_name = student_name or await self._student_name(student_id) or "A student"
        active_count = len(await self._enrollments.active_for_session(session_id))

        other_title: str | None = None
        if change == "moved" and from_session_id and from_session_id != session_id:
            origin = await self._sessions.get(from_session_id)
            other_title = origin.title if origin else None

        subject, body = render_roster_alert(
            change=change,
            session=session,
            academy_name=academy_name,
            student_name=resolved_name,
            active_count=active_count,
            academy_timezone=academy_timezone,
            other_session_title=other_title,
        )

        recipients = await self._staff_recipients(
            session_id=session_id,
            from_session_id=from_session_id if change == "moved" else None,
            actor_id=actor_id,
        )
        for recipient in recipients:
            await self._send_one(
                recipient=recipient,
                subject=subject,
                # Footer per recipient: the unsubscribe token is bound to the
                # person, and NOTIFICATION is unsubscribable, so the CAN-SPAM
                # notice is mandatory on every staff alert.
                body=append_unsubscribe_footer(
                    body,
                    self._unsubscribe_links.build(
                        academy_id=academy_id,
                        user_id=recipient.user_id,
                        academy_slug=academy_slug,
                    ),
                ),
                category=EmailCategory.NOTIFICATION,
                context={"change": change, "session_id": session_id},
            )

        if change in _PARENT_STATUS_CHANGES:
            # Issue #651: the family hears about their own child's status
            # change (cancel, withdraw, pause, resume, class cancelled).
            parent_id = parent_user_id or await self._parent_id_for_student(student_id)
            if parent_id:
                await self._notify_parent_status(
                    change=change,
                    session=session,
                    academy_name=academy_name,
                    academy_timezone=academy_timezone,
                    academy_slug=academy_slug,
                    student_name=resolved_name,
                    parent_user_id=parent_id,
                )

        if change == "promoted" and parent_user_id:
            await self._notify_parent_seat_opened(
                session=session,
                academy_name=academy_name,
                academy_timezone=academy_timezone,
                academy_slug=academy_slug,
                student_name=resolved_name,
                parent_user_id=parent_user_id,
            )

    async def _parent_id_for_student(self, student_id: str) -> str | None:
        try:
            students = await self._students.by_ids([student_id])
        except Exception:  # pragma: no cover - defensive
            return None
        for student in students:
            parent_id = str(getattr(student, "parent_id", "") or "").strip()
            if parent_id:
                return parent_id
        return None

    async def _notify_parent_status(
        self,
        *,
        change: RosterChangeKind,
        session: Session,
        academy_name: str,
        academy_timezone: str | None,
        academy_slug: str | None,
        student_name: str,
        parent_user_id: str,
    ) -> None:
        """TRANSACTIONAL: a status change to your own enrollment is never a digest."""
        parent = await self._resolve_users([parent_user_id])
        recipient = parent[0] if parent else None
        if recipient is None or not recipient.email:
            logger.warning(
                "enrollment.status_change_no_recipient",
                extra={"session_id": session.session_id, "parent_user_id": parent_user_id},
            )
            return
        base = academy_frontend_url(
            frontend_url=self._unsubscribe_links.frontend_url, academy_slug=academy_slug
        )
        subject, body = render_parent_status_email(
            change=change,
            session=session,
            academy_name=academy_name,
            student_name=student_name,
            portal_url=f"{base.rstrip('/')}/parent" if base else None,
            academy_timezone=academy_timezone,
        )
        await self._send_one(
            recipient=recipient,
            subject=subject,
            body=body,
            category=EmailCategory.TRANSACTIONAL,
            context={"change": change, "session_id": session.session_id},
        )

    async def pause_request_declined(
        self,
        *,
        parent_id: str,
        enrollment_id: str,
        session_id: str | None,
        reason: str | None,
    ) -> None:
        """Issue #651: tell the parent their pause request was declined."""
        parent = await self._resolve_users([parent_id])
        recipient = parent[0] if parent else None
        if recipient is None or not recipient.email:
            return
        session = await self._sessions.get(session_id) if session_id else None
        academy_id = current_academy_id()
        academy_doc = await self._academies.find_by_id(academy_id) or {}
        academy_name = str(academy_doc.get("display_name") or academy_doc.get("name") or "") or (
            "Your academy"
        )
        title = html.escape(session.title if session else "your class")
        note = f"<p>Reason: {html.escape(reason)}</p>" if reason else ""
        inner = (
            f"<h2 style='font-size: 18px; margin: 0 0 12px;'>Pause request declined</h2>"
            f"<p>The academy could not approve the pause you requested for {title}. "
            "The enrollment stays active and billing continues as usual.</p>"
            f"{note}<p>Reply to this email or contact the academy if you have questions.</p>"
        )
        await self._send_one(
            recipient=recipient,
            subject=f"Pause request declined — {session.title if session else 'your class'}",
            body=_branded_shell(academy_name=academy_name, inner_html=inner),
            category=EmailCategory.TRANSACTIONAL,
            context={"change": "pause_declined", "enrollment_id": enrollment_id},
        )

    async def _notify_parent_seat_opened(
        self,
        *,
        session: Session,
        academy_name: str,
        academy_timezone: str | None,
        academy_slug: str | None,
        student_name: str,
        parent_user_id: str,
    ) -> None:
        """Phase 2. TRANSACTIONAL, so a family that switched off digests still
        hears that their child got the seat; a hard bounce still blocks it."""
        parent = await self._resolve_users([parent_user_id])
        recipient = parent[0] if parent else None
        if recipient is None or not recipient.email:
            logger.warning(
                "enrollment.seat_opened_no_recipient",
                extra={"session_id": session.session_id, "parent_user_id": parent_user_id},
            )
            return
        base = academy_frontend_url(
            frontend_url=self._unsubscribe_links.frontend_url, academy_slug=academy_slug
        )
        subject, body = render_seat_opened_email(
            session=session,
            academy_name=academy_name,
            student_name=student_name,
            # Built on the academy's own subdomain (ADR-0007): TenantResolver
            # reads the tenant from the host's first label, so a link on the
            # deployment's generic frontend_url resolves to no tenant at all.
            portal_url=f"{base.rstrip('/')}/parent" if base else None,
            academy_timezone=academy_timezone,
        )
        await self._send_one(
            recipient=recipient,
            subject=subject,
            body=body,  # no unsubscribe footer: transactional
            category=EmailCategory.TRANSACTIONAL,
            context={"change": "promoted", "session_id": session.session_id},
        )

    async def _send_one(
        self,
        *,
        recipient: ResolvedRecipient,
        subject: str,
        body: str,
        category: EmailCategory,
        context: dict[str, Any],
    ) -> None:
        """One recipient, never raising.

        A provider failure for one person must not cost the rest of the
        audience their alert, and must not reach the enrollment write.
        """
        try:
            outcome = await self._sender.send(
                recipient=recipient,
                subject=subject,
                body=body,
                category=category,
            )
        except Exception:
            logger.exception(
                "enrollment.roster_notification_send_failed",
                extra={**context, "recipient_user_id": recipient.user_id},
            )
            return
        if not outcome.ok and not outcome.suppressed:
            logger.warning(
                "enrollment.roster_notification_send_failed",
                extra={
                    **context,
                    "recipient_user_id": recipient.user_id,
                    "reason": outcome.failed_reason,
                },
            )

    async def _staff_recipients(
        self,
        *,
        session_id: str,
        from_session_id: str | None,
        actor_id: str | None,
    ) -> list[ResolvedRecipient]:
        """Coach(es) plus admins plus owners, deduped by user_id, actor removed.

        Resolution happens before anything is sent, so a failure here is safe
        to swallow whole: no recipient has been mailed yet. A move resolves
        both sessions' coaches — the coach losing a student needs the alert as
        much as the one gaining them.
        """
        groups: list[list[ResolvedRecipient]] = []
        for sid in filter(None, (session_id, from_session_id)):
            groups.append(
                await self._resolve(
                    self._audiences.resolve_coach_audience, CoachAudience(session_id=sid)
                )
            )
        for role in _STAFF_ROLES:
            groups.append(
                await self._resolve(
                    self._audiences.resolve_academy_audience, AcademyAudience(role=role)
                )
            )

        seen: set[str] = set()
        unique: list[ResolvedRecipient] = []
        for group in groups:
            for recipient in group:
                if not recipient.user_id or recipient.user_id in seen:
                    continue
                # Never tell someone about their own action, and never try to
                # mail a staff row with no address.
                if actor_id and recipient.user_id == actor_id:
                    continue
                if not (recipient.email or "").strip():
                    continue
                seen.add(recipient.user_id)
                unique.append(recipient)
        return unique

    async def _resolve(self, resolver: Any, audience: Any) -> list[ResolvedRecipient]:
        try:
            return list(await resolver(audience))
        except Exception:
            logger.exception(
                "enrollment.roster_alert_audience_failed",
                extra={"audience": type(audience).__name__},
            )
            return []

    async def _resolve_users(self, user_ids: list[str]) -> list[ResolvedRecipient]:
        from backend.v2.contexts.communications.domain.models import SelectedRecipientsAudience

        return await self._resolve(
            self._audiences.resolve_selected_audience,
            SelectedRecipientsAudience(user_ids=tuple(user_ids)),
        )

    async def _student_name(self, student_id: str) -> str | None:
        try:
            students = await self._students.by_ids([student_id])
        except Exception:  # pragma: no cover - defensive
            return None
        for student in students:
            name = str(getattr(student, "full_name", "") or "").strip()
            if name:
                return name
        return None


@dataclass(frozen=True, slots=True)
class EnrollmentNotifiers:
    """The two outbound-mail adapters an enrollment write may fire.

    Returned as a pair so ``composition/admin.py`` stays one line of wiring per
    concern — it is held to a hard line budget by
    ``tests/structural/test_composition_is_wiring.py``, and the right response
    to that budget is to move construction into a module like this one.
    """

    welcome: EnrollmentWelcomeEmailAdapter
    roster: RosterAlertAdapter


def compose_enrollment_notifiers(
    db: Any,
    settings: Any,
    *,
    users: Any,
) -> EnrollmentNotifiers:
    """Build the #613 welcome adapter and the #612 roster-alert adapter.

    Both take their send port from ``_build_email_sender``, the single
    construction site that hands dev and CI the stub port and production the
    gated Resend one — so neither adapter can accidentally become a path that
    sends real mail from a test stack.
    """
    academies = MongoAcademyRepository(db)
    sessions = MongoSessionRepository(db)
    sender = _build_email_sender(settings, db)
    return EnrollmentNotifiers(
        welcome=EnrollmentWelcomeEmailAdapter(
            sessions=sessions,
            users=users,
            academies=academies,
            # Tenant-scoped recipient resolution for the family's address. The
            # global user lookup above is only used for the coach's *name*,
            # and that id comes off the tenant-scoped session document.
            audiences=MongoAudienceResolver(db=db),
            sender=sender,
        ),
        roster=compose_roster_notifier(db, settings, sessions=sessions, academies=academies),
    )


def compose_roster_notifier(
    db: Any,
    settings: Any,
    *,
    sessions: Any = None,
    academies: Any = None,
) -> RosterAlertAdapter:
    """The #612 staff-alert adapter on its own.

    ``composition/parent.py`` wires the parent-side triggers (self-cancel and
    the waitlist promotion that follows it) and has no welcome adapter to
    build, so it takes this rather than the pair.
    """
    return RosterAlertAdapter(
        sessions=sessions or MongoSessionRepository(db),
        enrollments=MongoEnrollmentRepository(db),
        students=MongoStudentRepository(db),
        academies=academies or MongoAcademyRepository(db),
        audiences=MongoAudienceResolver(db=db),
        sender=_build_email_sender(settings, db),
        unsubscribe_links=compose_unsubscribe_link_builder(settings),
    )
