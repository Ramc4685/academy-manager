"""HoldNotifier adapter — family email for hold start, reclaim/expiry and reminders.

Issue #697. Lives outside ``composition/admin.py`` — that module sits at its
wiring line budget (``test_composition_is_wiring`` is the check). Reuses the
claim from ``communications/infrastructure/digest_claim.py`` for BOTH sends,
which is mandatory (see the departures design contract §4.4): that module's
docstring is the repo's written record of the 2026-09-02 production incident
where a freshly written claim would have been unsafe.

Both sends are best-effort from the caller's point of view (never raise) and
are TRANSACTIONAL — a family whose child's seat is being taken away must get
the notice regardless of marketing preferences.
"""

from __future__ import annotations

import html
import logging
from datetime import date, datetime
from typing import Any, Literal, Protocol

from backend.v2.composition.hold_notice_send_repo import MongoHoldNoticeSendRepository
from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.models import SelectedRecipientsAudience
from backend.v2.contexts.enrollment.domain.models import Session, Student
from backend.v2.shared.tenancy import current_academy_id

logger = logging.getLogger(__name__)


def _para(text: str) -> str:
    return f"<p style='margin:0 0 12px'>{text}</p>"


class SessionLookup(Protocol):
    async def get(self, session_id: str) -> Session | None: ...


class StudentLookup(Protocol):
    async def by_ids(self, student_ids: list[str]) -> list[Student]: ...


class HoldNotificationAdapter:
    def __init__(
        self,
        *,
        sessions: SessionLookup,
        students: StudentLookup,
        audiences: AudienceResolver,
        sender: EmailSendPort,
        notice_sends: MongoHoldNoticeSendRepository,
    ) -> None:
        self._sessions = sessions
        self._students = students
        self._audiences = audiences
        self._sender = sender
        self._notice_sends = notice_sends

    async def hold_started(
        self,
        *,
        enrollment_id: str,
        hold_seq: int,
        session_id: str,
        student_id: str,
        hold_started_at: datetime,
        hold_return_on: date,
        hold_expires_at: datetime,
    ) -> None:
        """Issue #740. Keyed by ``hold_seq`` so re-holding the same enrollment
        later mails again, while a retry of THIS hold never does."""
        notice_key = f"hold-start:{hold_seq}"
        await self._send_claimed(
            enrollment_id=enrollment_id,
            notice_key=notice_key,
            session_id=session_id,
            student_id=student_id,
            build=lambda session, student_name: (
                f"{student_name}'s class is on hold",
                self._render_started_body(
                    session=session,
                    student_name=student_name,
                    hold_return_on=hold_return_on,
                    hold_expires_at=hold_expires_at,
                ),
            ),
        )

    async def hold_reclaimed(
        self,
        *,
        enrollment_id: str,
        hold_seq: int,
        session_id: str,
        student_id: str,
        hold_started_at: datetime,
        reason: Literal["reclaimed", "expired", "orphaned"],
        requested_by: str | None,
        billing_result: str | None,
    ) -> None:
        notice_key = f"hold-reclaim:{hold_seq}"
        await self._send_claimed(
            enrollment_id=enrollment_id,
            notice_key=notice_key,
            session_id=session_id,
            student_id=student_id,
            build=lambda session, student_name: (
                f"{student_name} is off the roster",
                self._render_reclaim_body(
                    session=session,
                    student_name=student_name,
                    hold_started_at=hold_started_at,
                    reason=reason,
                    billing_result=billing_result,
                ),
            ),
        )

    async def hold_reminder(
        self,
        *,
        enrollment_id: str,
        hold_seq: int,
        notice_index: int,
        session_id: str,
        student_id: str,
        hold_started_at: datetime,
        hold_return_on: date,
        hold_expires_at: datetime,
    ) -> None:
        notice_key = f"hold-reminder:{hold_seq}:{notice_index}"
        await self._send_claimed(
            enrollment_id=enrollment_id,
            notice_key=notice_key,
            session_id=session_id,
            student_id=student_id,
            build=lambda session, student_name: (
                f"{student_name}'s hold is still on",
                self._render_reminder_body(
                    session=session,
                    student_name=student_name,
                    hold_started_at=hold_started_at,
                    hold_return_on=hold_return_on,
                    hold_expires_at=hold_expires_at,
                ),
            ),
        )

    # -- shared plumbing ---------------------------------------------------

    async def _send_claimed(
        self,
        *,
        enrollment_id: str,
        notice_key: str,
        session_id: str,
        student_id: str,
        build: Any,
    ) -> None:
        academy_id = current_academy_id()
        claim = await self._notice_sends.try_claim(
            academy_id=academy_id, enrollment_id=enrollment_id, notice_key=notice_key
        )
        if claim is None:
            # Already sent/skipped/in-flight/non-retryable/out of attempts —
            # the no-duplicate-email invariant.
            return

        session = await self._sessions.get(session_id)
        students = await self._students.by_ids([student_id])
        student_name = students[0].full_name if students else "The student"
        parent_id = students[0].parent_id if students else None

        if session is None or not parent_id:
            await self._notice_sends.mark_failed(
                claim["send_id"], "session_or_parent_missing", retryable=False
            )
            return

        recipient = await self._resolve_parent(parent_id)
        if recipient is None or not recipient.email:
            await self._notice_sends.mark_failed(claim["send_id"], "no_recipient", retryable=False)
            return

        subject, body = build(session, student_name)
        try:
            outcome = await self._sender.send(
                recipient=recipient,
                subject=subject,
                body=body,
                category=EmailCategory.TRANSACTIONAL,
            )
        except Exception:
            logger.exception("hold_notice_send_failed", extra={"enrollment_id": enrollment_id})
            await self._notice_sends.mark_failed(claim["send_id"], "send_exception")
            return

        if outcome.ok:
            await self._notice_sends.mark_sent(claim["send_id"])
        elif outcome.suppressed:
            await self._notice_sends.mark_failed(claim["send_id"], "suppressed", retryable=False)
        else:
            await self._notice_sends.mark_failed(
                claim["send_id"], outcome.failed_reason or "send_failed"
            )

    async def _resolve_parent(self, parent_id: str) -> ResolvedRecipient | None:
        try:
            resolved = await self._audiences.resolve_selected_audience(
                SelectedRecipientsAudience(user_ids=(parent_id,))
            )
        except Exception:
            logger.exception("hold_notice_audience_failed", extra={"parent_id": parent_id})
            return None
        return resolved[0] if resolved else None

    @staticmethod
    def _render_started_body(
        *,
        session: Session,
        student_name: str,
        hold_return_on: date,
        hold_expires_at: datetime,
    ) -> str:
        safe_name = html.escape(student_name)
        safe_title = html.escape(session.title)
        return "".join(
            [
                _para(f"<strong>{safe_name}</strong>'s place in {safe_title} is on hold."),
                _para(
                    f"{safe_name} is not expected in class until "
                    f"{html.escape(hold_return_on.isoformat())}, so {safe_title} will not "
                    "appear in the upcoming sessions on your portal until then."
                ),
                _para(
                    "The seat is being kept for you. It must be used or returned by "
                    f"{html.escape(hold_expires_at.date().isoformat())}."
                ),
                _para("If this is not right, please contact the academy."),
            ]
        )

    @staticmethod
    def _render_reclaim_body(
        *,
        session: Session,
        student_name: str,
        hold_started_at: datetime,
        reason: Literal["reclaimed", "expired", "orphaned"],
        billing_result: str | None,
    ) -> str:
        safe_name = html.escape(student_name)
        safe_title = html.escape(session.title)
        why = {
            "reclaimed": "the class filled up and needed the seat",
            "expired": "the hold reached its maximum length",
            # A system error interrupted the hand-over before it completed —
            # NOT "the class filled up" (that would be false: nobody ended up
            # with the seat) and not "the hold expired" (its clock had not
            # run out). Honest about what actually happened.
            "orphaned": "a system error interrupted the process of returning the seat",
        }[reason]
        parts = [
            _para(f"<strong>{safe_name}</strong> has been taken off the roster for {safe_title}."),
            _para(
                f"{safe_name} was on hold since {html.escape(hold_started_at.date().isoformat())}, and {why}."
            ),
        ]
        if billing_result:
            parts.append(_para(f"Billing status: {html.escape(billing_result)}."))
        parts.append(
            _para(
                "If you would like to rejoin, please contact the academy or add "
                f"{safe_name} back to the waitlist for {safe_title}."
            )
        )
        return "".join(parts)

    @staticmethod
    def _render_reminder_body(
        *,
        session: Session,
        student_name: str,
        hold_started_at: datetime,
        hold_return_on: date,
        hold_expires_at: datetime,
    ) -> str:
        safe_name = html.escape(student_name)
        safe_title = html.escape(session.title)
        return "".join(
            [
                _para(f"<strong>{safe_name}</strong> is still on hold for {safe_title}."),
                _para(f"Hold started: {html.escape(hold_started_at.date().isoformat())}."),
                _para(f"Expected return: {html.escape(hold_return_on.isoformat())}."),
                _para(
                    "The seat is being held for you, but it may be given to another "
                    f"family if the class is full — it must be used or returned by "
                    f"{html.escape(hold_expires_at.date().isoformat())}."
                ),
            ]
        )


def compose_hold_notifications(db: Any, settings: Any) -> HoldNotificationAdapter:
    """Convenience constructor mirroring ``compose_enrollment_notifiers``:
    builds every Mongo-backed collaborator itself so a caller need only pass
    ``db``/``settings``, the two things every composition entry point has."""
    from backend.v2.composition.digests import _build_email_sender
    from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
        MongoAudienceResolver,
    )
    from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
        MongoSessionRepository,
    )
    from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
        MongoStudentRepository,
    )

    return HoldNotificationAdapter(
        sessions=MongoSessionRepository(db),
        students=MongoStudentRepository(db),
        audiences=MongoAudienceResolver(db=db),
        sender=_build_email_sender(settings, db),
        notice_sends=MongoHoldNoticeSendRepository(db),
    )
