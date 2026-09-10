"""Absence-notice notifications (#616): a staff alert and a parent confirmation.

Implements enrollment's ``AbsenceNoticeNotifier``. Before this adapter an
absence notice had one side effect — ``repo.add()`` — and was visible only by
pull (the coach's roster chip, the admin Requests > Absences tab). Nobody was
told before class, and a parent who gave late notice was never told that it
would not unlock a make-up.

Built on the two existing primitives, deliberately, so there is no third
delivery pipeline for enrollment mail:

* ``roster_notifications.py`` (#612) — the staff audience (the occurrence's
  coach(es) plus every admin and owner, deduped, actor removed), the
  NOTIFICATION category with the per-recipient unsubscribe footer, and the
  "class time with its zone named" formatter.
* ``hold_notifications.py`` (#697) — the send claim over
  ``communications/infrastructure/digest_claim.py``, which is what makes each
  email fire once per notice even if the request is retried or the use case
  is re-run. That module's docstring is the repo's written record of why a
  freshly written claim would be unsafe.

Three rules this module keeps true:

* **The write wins.** ``absence_notice_submitted`` never raises. The notice
  is already persisted when it runs and a mail outage may not undo that.
* **Staff alerts are NOTIFICATION, the parent's confirmation is TRANSACTIONAL.**
  A coach may switch absence pings off; a family's confirmation of their own
  notice is the record of that family's own enrollment and carries no footer.
* **Admin-recorded notices alert staff but never mail the parent.** The parent
  phoned or messaged; sending them a portal-style confirmation for something
  they did not do in the portal would be confusing at best. The adapter reads
  ``notice.recorded_by_admin`` — the use cases do not branch.

The staff/parent plumbing (``_staff_recipients``, ``_send_claimed``) is
event-agnostic on purpose: ``RequestEnrollmentPause`` has the same "nobody is
told" gap (#616 proper) and is meant to plug a second method into this same
adapter later. It is NOT wired here.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from backend.v2.composition.digests import (
    _build_email_sender,
    compose_unsubscribe_link_builder,
)
from backend.v2.composition.email_adapters import (
    _BRAND_HEADING,
    _branded_button,
    _branded_shell,
)
from backend.v2.composition.roster_notifications import format_occurrence_when
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
    DigestSendStatus,
    SelectedRecipientsAudience,
)
from backend.v2.contexts.communications.infrastructure.digest_claim import claim_digest_send
from backend.v2.contexts.enrollment.application.use_cases.absence_notices import AbsenceNotice
from backend.v2.contexts.enrollment.domain.models import Session, SessionOccurrence, Student
from backend.v2.contexts.enrollment.domain.self_service import ParentSelfServicePolicy
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id
from backend.v2.shared.tenancy.academy_url import academy_frontend_url

logger = logging.getLogger(__name__)

#: Which of the two emails a claim row is for. One row per (notice, audience).
NoticeAudience = Literal["staff", "parent"]

#: Staff alerts go to the occurrence's coach(es) plus everyone who runs the
#: academy. ``owner`` is here because an owner-only academy has no admins.
_STAFF_ROLES: tuple[AudienceRole, ...] = ("admin", "owner")


class SessionLookup(Protocol):
    async def get(self, session_id: str) -> Session | None: ...


class AcademyLookup(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...


class PolicyLookup(Protocol):
    async def get_or_default(self) -> ParentSelfServicePolicy: ...


def _para(text: str) -> str:
    return f"<p style='margin: 0 0 12px;'>{text}</p>"


def _hours(n: int) -> str:
    return "1 hour" if n == 1 else f"{n} hours"


class MongoAbsenceNoticeSendRepository(TenantScopedRepository):
    """Send claim for absence-notice emails, one row per (notice, audience).

    Structurally ``MongoHoldNoticeSendRepository`` with ``notice_id`` as the
    recipient field and the audience name as the ``digest_date`` key. Lives
    in ``composition/`` for the same reason that one does: it bridges the
    enrollment and communications contexts, which ``contexts/**`` may not.
    Migration 0172 adds the unique ``(academy_id, notice_id, audience)``
    index; the claim is already safe without it (see ``digest_claim``).
    """

    collection_name = "absence_notice_sends"

    async def try_claim(
        self, *, academy_id: str, notice_id: str, audience: NoticeAudience
    ) -> dict[str, Any] | None:
        doc = {
            "send_id": str(new_ulid()),
            "academy_id": academy_id,
            "notice_id": notice_id,
            "audience": audience,
            # `claim_digest_send`'s post-insert verify and its fallback
            # `reclaim_retryable_send` both filter on `digest_date`, so this
            # field is load-bearing (see hold_notice_send_repo.py).
            "digest_date": audience,
            "status": str(DigestSendStatus.QUEUED),
            "provider_message_id": None,
            "failed_reason": None,
            "created_at": datetime.now(UTC),
            "attempt_count": 1,
            "retryable": True,
        }
        return await claim_digest_send(
            self.collection,
            doc=doc,
            academy_id=academy_id,
            recipient_field="notice_id",
            recipient_id=notice_id,
            digest_date=audience,
        )

    async def mark_sent(self, send_id: str) -> None:
        await self.collection.update_one(
            {"send_id": send_id},
            {"$set": {"status": str(DigestSendStatus.SENT), "failed_reason": None}},
        )

    async def mark_failed(self, send_id: str, reason: str, *, retryable: bool = True) -> None:
        await self.collection.update_one(
            {"send_id": send_id},
            {
                "$set": {
                    "status": str(DigestSendStatus.FAILED),
                    "failed_reason": reason,
                    "retryable": retryable,
                }
            },
        )


def render_staff_absence_alert(
    *,
    student_name: str,
    session_title: str,
    when: str,
    location: str | None,
    academy_name: str,
    notice_window_met: bool,
    recorded_by_admin: bool,
) -> tuple[str, str]:
    """``(subject, html_body)`` for the staff alert, footer excluded.

    The footer is appended per recipient (each carries its own unsubscribe
    token), so the body is rendered once per notice rather than once per
    person.
    """
    safe_student = html.escape(student_name)
    safe_session = html.escape(session_title)
    parts = [
        f"<h2 style='color: {_BRAND_HEADING}; font-size: 18px; margin: 0 0 12px;'>"
        f"{safe_student} will miss {safe_session}</h2>",
        _para(f"<strong>When:</strong> {html.escape(when)}"),
    ]
    if location:
        parts.append(_para(f"<strong>Where:</strong> {html.escape(location)}"))
    if recorded_by_admin:
        parts.append(_para("Recorded by the academy on the family's behalf."))
    else:
        parts.append(_para("The family sent this notice from the parent portal."))
    if notice_window_met:
        parts.append(_para("The notice was in time, so this absence counts toward a make-up."))
    else:
        parts.append(_para("The notice was late, so this absence does not count toward a make-up."))
    subject = f"{student_name} will miss {session_title} on {when}"
    return subject, _branded_shell(academy_name=academy_name, inner_html="".join(parts))


def render_parent_absence_confirmation(
    *,
    student_name: str,
    session_title: str,
    when: str,
    academy_name: str,
    notice_window_met: bool,
    min_notice_hours: int,
    portal_url: str | None,
) -> tuple[str, str]:
    """``(subject, html_body)`` confirming the parent's own notice.

    Says plainly whether the notice was in time for a make-up. Before this
    email the only consumer of ``notice_window_met`` was the make-up
    eligibility gate, so a parent who gave late notice found out when the
    make-up request was refused.
    """
    safe_student = html.escape(student_name)
    safe_session = html.escape(session_title)
    parts = [
        f"<h2 style='color: {_BRAND_HEADING}; font-size: 18px; margin: 0 0 12px;'>"
        f"Absence notice received</h2>",
        _para(
            f"Thanks for letting us know. <strong>{safe_student}</strong> is marked as away "
            f"from {safe_session} on <strong>{html.escape(when)}</strong>."
        ),
    ]
    hours = _hours(min_notice_hours)
    if notice_window_met:
        parts.append(
            _para(
                f"You gave at least {hours}' notice, so this absence counts toward a "
                "make-up class. You can request one from the parent portal."
            )
        )
    else:
        parts.append(
            _para(
                f"This notice came in less than {hours} before the class starts, so under "
                "the academy's policy it does not count toward a make-up class. Contact "
                "the academy if you have a question about this."
            )
        )
    if portal_url:
        parts.append(_branded_button(label="Open the parent portal", url=portal_url))
    subject = f"Absence noted: {student_name} on {when}"
    return subject, _branded_shell(academy_name=academy_name, inner_html="".join(parts))


class AbsenceNoticeNotificationAdapter:
    """Implements enrollment's ``AbsenceNoticeNotifier``.

    Tenancy: the academy is read at *execution* time via
    ``current_academy_id()`` and never captured at composition time. Every
    repository here is tenant-scoped, so recipients can only ever come from
    the academy whose request is running.
    """

    def __init__(
        self,
        *,
        sessions: SessionLookup,
        academies: AcademyLookup,
        policies: PolicyLookup,
        audiences: AudienceResolver,
        sender: EmailSendPort,
        notice_sends: MongoAbsenceNoticeSendRepository,
        unsubscribe_links: UnsubscribeLinkBuilder | None = None,
    ) -> None:
        self._sessions = sessions
        self._academies = academies
        self._policies = policies
        self._audiences = audiences
        self._sender = sender
        self._notice_sends = notice_sends
        self._unsubscribe_links = unsubscribe_links or UnsubscribeLinkBuilder()

    async def absence_notice_submitted(
        self, *, notice: AbsenceNotice, occurrence: SessionOccurrence, student: Student
    ) -> None:
        try:
            await self._absence_notice_submitted(
                notice=notice, occurrence=occurrence, student=student
            )
        except Exception:
            # The use case swallows too; this keeps the log line specific.
            logger.exception(
                "enrollment.absence_notice_notify_failed",
                extra={"notice_id": notice.notice_id, "occurrence_id": occurrence.occurrence_id},
            )

    async def _absence_notice_submitted(
        self, *, notice: AbsenceNotice, occurrence: SessionOccurrence, student: Student
    ) -> None:
        academy_id = current_academy_id()
        session = await self._sessions.get(occurrence.session_id)
        academy_doc = await self._academies.find_by_id(academy_id) or {}
        academy_name = (
            str(academy_doc.get("display_name") or academy_doc.get("name") or "") or "Your academy"
        )
        academy_timezone = str(academy_doc.get("timezone") or "") or None
        academy_slug = str(academy_doc.get("slug") or "") or None
        session_title = session.title if session else "class"
        # Times in the ACADEMY's zone (the spec for #616), falling back to the
        # session's own zone when the academy has none. The zone name is
        # printed either way: prod holds sessions stamped UTC under an
        # America/Chicago academy, and a visibly odd time beats a silently
        # shifted one.
        when = format_occurrence_when(
            occurrence.start_at,
            session_timezone=academy_timezone or (session.timezone if session else None),
            academy_timezone=None,
        )

        await self._notify_staff(
            notice=notice,
            occurrence=occurrence,
            student=student,
            session=session,
            session_title=session_title,
            when=when,
            academy_id=academy_id,
            academy_name=academy_name,
            academy_slug=academy_slug,
        )
        if not notice.recorded_by_admin:
            await self._notify_parent(
                notice=notice,
                student=student,
                session_title=session_title,
                when=when,
                academy_id=academy_id,
                academy_name=academy_name,
                academy_slug=academy_slug,
            )

    # -- staff -------------------------------------------------------------

    async def _notify_staff(
        self,
        *,
        notice: AbsenceNotice,
        occurrence: SessionOccurrence,
        student: Student,
        session: Session | None,
        session_title: str,
        when: str,
        academy_id: str,
        academy_name: str,
        academy_slug: str | None,
    ) -> None:
        subject, body = render_staff_absence_alert(
            student_name=student.full_name,
            session_title=session_title,
            when=when,
            location=session.location if session else None,
            academy_name=academy_name,
            notice_window_met=notice.notice_window_met,
            recorded_by_admin=notice.recorded_by_admin,
        )

        async def _recipients() -> list[ResolvedRecipient]:
            return await self._staff_recipients(
                occurrence=occurrence,
                # Never tell someone about their own action: the admin who
                # just typed the notice in. A parent is never staff.
                actor_id=notice.submitted_by if notice.recorded_by_admin else None,
            )

        await self._send_claimed(
            notice_id=notice.notice_id,
            audience="staff",
            academy_id=academy_id,
            recipients=_recipients,
            subject=subject,
            # Footer per recipient: the unsubscribe token is bound to the
            # person, and NOTIFICATION is unsubscribable.
            body_for=lambda recipient: append_unsubscribe_footer(
                body,
                self._unsubscribe_links.build(
                    academy_id=academy_id,
                    user_id=recipient.user_id,
                    academy_slug=academy_slug,
                ),
            ),
            category=EmailCategory.NOTIFICATION,
        )

    async def _staff_recipients(
        self, *, occurrence: SessionOccurrence, actor_id: str | None
    ) -> list[ResolvedRecipient]:
        """Occurrence coach(es) + the session's coach + admins + owners, deduped.

        The occurrence's own coach fields come first (a substitute covering
        tonight needs the alert more than the template's coach), then the
        session's coach via ``CoachAudience``, then the academy roles.
        """
        coach_ids = tuple(
            dict.fromkeys(
                cid
                for cid in (
                    occurrence.actual_coach_id,
                    occurrence.substitute_coach_id,
                    occurrence.scheduled_coach_id,
                    *occurrence.assistant_coach_ids,
                )
                if cid
            )
        )
        groups: list[list[ResolvedRecipient]] = []
        if coach_ids:
            groups.append(
                await self._resolve(
                    self._audiences.resolve_selected_audience,
                    SelectedRecipientsAudience(user_ids=coach_ids),
                )
            )
        groups.append(
            await self._resolve(
                self._audiences.resolve_coach_audience,
                CoachAudience(session_id=occurrence.session_id),
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
                if actor_id and recipient.user_id == actor_id:
                    continue
                if not (recipient.email or "").strip():
                    continue
                seen.add(recipient.user_id)
                unique.append(recipient)
        return unique

    # -- parent ------------------------------------------------------------

    async def _notify_parent(
        self,
        *,
        notice: AbsenceNotice,
        student: Student,
        session_title: str,
        when: str,
        academy_id: str,
        academy_name: str,
        academy_slug: str | None,
    ) -> None:
        """TRANSACTIONAL: confirming your own notice is never a digest."""
        try:
            policy = await self._policies.get_or_default()
            min_hours = int(policy.absence_notice_min_hours)
        except Exception:
            logger.exception(
                "enrollment.absence_notice_policy_failed", extra={"notice_id": notice.notice_id}
            )
            min_hours = ParentSelfServicePolicy.default(academy_id).absence_notice_min_hours
        base = academy_frontend_url(
            frontend_url=self._unsubscribe_links.frontend_url, academy_slug=academy_slug
        )
        subject, body = render_parent_absence_confirmation(
            student_name=student.full_name,
            session_title=session_title,
            when=when,
            academy_name=academy_name,
            notice_window_met=notice.notice_window_met,
            min_notice_hours=min_hours,
            # Built on the academy's own subdomain (ADR-0007), like every
            # other family email here.
            portal_url=f"{base.rstrip('/')}/parent" if base else None,
        )

        async def _recipients() -> list[ResolvedRecipient]:
            if not student.parent_id:
                return []
            resolved = await self._resolve(
                self._audiences.resolve_selected_audience,
                SelectedRecipientsAudience(user_ids=(student.parent_id,)),
            )
            return [r for r in resolved if (r.email or "").strip()]

        await self._send_claimed(
            notice_id=notice.notice_id,
            audience="parent",
            academy_id=academy_id,
            recipients=_recipients,
            subject=subject,
            body_for=lambda _recipient: body,  # no unsubscribe footer: transactional
            category=EmailCategory.TRANSACTIONAL,
        )

    # -- shared plumbing ---------------------------------------------------

    async def _send_claimed(
        self,
        *,
        notice_id: str,
        audience: NoticeAudience,
        academy_id: str,
        recipients: Callable[[], Any],
        subject: str,
        body_for: Callable[[ResolvedRecipient], str],
        category: EmailCategory,
    ) -> None:
        """Claim ``(notice, audience)`` once, then mail every recipient.

        The claim comes BEFORE recipient resolution so a retried request or a
        re-run use case finds the row and sends nothing — the no-duplicate-
        email invariant. A recipient that fails does not cost the others
        their copy; the row records the first failure reason.
        """
        claim = await self._notice_sends.try_claim(
            academy_id=academy_id, notice_id=notice_id, audience=audience
        )
        if claim is None:
            return
        send_id = str(claim["send_id"])

        resolved = await recipients()
        if not resolved:
            await self._notice_sends.mark_failed(send_id, "no_recipient", retryable=False)
            return

        failure: str | None = None
        for recipient in resolved:
            reason = await self._send_one(
                recipient=recipient,
                subject=subject,
                body=body_for(recipient),
                category=category,
                context={"notice_id": notice_id, "audience": audience},
            )
            failure = failure or reason
        if failure is None:
            await self._notice_sends.mark_sent(send_id)
        else:
            await self._notice_sends.mark_failed(send_id, failure)

    async def _send_one(
        self,
        *,
        recipient: ResolvedRecipient,
        subject: str,
        body: str,
        category: EmailCategory,
        context: dict[str, Any],
    ) -> str | None:
        """One recipient, never raising. Returns a failure reason or ``None``."""
        try:
            outcome = await self._sender.send(
                recipient=recipient,
                subject=subject,
                body=body,
                category=category,
            )
        except Exception:
            logger.exception(
                "enrollment.absence_notice_send_failed",
                extra={**context, "recipient_user_id": recipient.user_id},
            )
            return "send_exception"
        if outcome.ok or outcome.suppressed:
            # A gate refusal is that recipient's preference, not a failure.
            return None
        logger.warning(
            "enrollment.absence_notice_send_failed",
            extra={
                **context,
                "recipient_user_id": recipient.user_id,
                "reason": outcome.failed_reason,
            },
        )
        return outcome.failed_reason or "send_failed"

    async def _resolve(self, resolver: Any, audience: Any) -> list[ResolvedRecipient]:
        try:
            return list(await resolver(audience))
        except Exception:
            logger.exception(
                "enrollment.absence_notice_audience_failed",
                extra={"audience": type(audience).__name__},
            )
            return []


def compose_absence_notifier(db: Any, settings: Any) -> AbsenceNoticeNotificationAdapter:
    """Convenience constructor mirroring ``compose_hold_notifications``: builds
    every Mongo-backed collaborator itself so ``composition/parent.py`` and
    ``composition/admin.py`` each add one keyword argument, not a block.

    The send port comes from ``_build_email_sender``, the single construction
    site that hands dev and CI the stub port and production the gated Resend
    one.
    """
    from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
        MongoAudienceResolver,
    )
    from backend.v2.contexts.enrollment.infrastructure.mongo_self_service_policy_repo import (
        MongoSelfServicePolicyRepository,
    )
    from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
        MongoSessionRepository,
    )
    from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
        MongoAcademyRepository,
    )

    return AbsenceNoticeNotificationAdapter(
        sessions=MongoSessionRepository(db),
        academies=MongoAcademyRepository(db),
        policies=MongoSelfServicePolicyRepository(db),
        audiences=MongoAudienceResolver(db=db),
        sender=_build_email_sender(settings, db),
        notice_sends=MongoAbsenceNoticeSendRepository(db),
        unsubscribe_links=compose_unsubscribe_link_builder(settings),
    )
