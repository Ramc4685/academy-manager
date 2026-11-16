"""Trial emails for self-booked and decided trials (L9 A6-1, A6-2).

Four templated messages, each sent at most once through ``send_once`` over
the ``trial_nudge_sends`` claim (subject = the trial request):

* ``guest_booked``: a website guest booked a date on the public page; the
  date, time, place and what to bring.
* ``trial_decided``: staff approved (with the date) or declined a pending
  trial, for an account parent or a website guest.
* ``trial_date_cancelled``: the academy called off a guest's date; the trial
  is back in the queue and the academy will offer another.

Account parents are mailed through the gated user path of
``TrialNudgeEmailAdapter``; website guests through ``ProspectEmailer`` (the
contact's address, the prospect opt-out gate and unsubscribe footer). All are
TRANSACTIONAL replies to a request the family made.

DARK BY DEFAULT: every message here is sent only while the academy has
``public_page.self_book_trials`` on, so this deploy mails no family until the
owner has approved the copy and switched it on. Never raises: a failure is
logged and the claim is left retryable or released by ``send_once``.

Lives in composition because it spans enrollment (the trial), CRM (the guest
contact), identity (the academy) and communications (the send ports).
"""

from __future__ import annotations

import html
import logging
from datetime import datetime
from functools import partial
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from backend.v2.composition.prospect_email import ProspectEmailer
from backend.v2.composition.trial_nudges import TrialNudgeEmailAdapter, _para, _when
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.crm.domain.models import CrmContact
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.contexts.enrollment.domain.self_service import TrialRequest
from backend.v2.contexts.identity.domain.public_page import PUBLIC_PAGE_FIELD
from backend.v2.shared.comms.claimed_send import SendClaimRepository, SendResult, send_once
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.shared.time import ensure_utc
from backend.v2.shared.time.academy_timezone import academy_clock_timezone

logger = logging.getLogger(__name__)


class GuestContacts(Protocol):
    async def get(self, contact_id: str) -> CrmContact | None: ...


class OccurrenceLookup(Protocol):
    async def get(self, occurrence_id: str) -> SessionOccurrence | None: ...


def trial_emails_enabled(academy_doc: dict[str, Any]) -> bool:
    page = academy_doc.get(PUBLIC_PAGE_FIELD)
    return isinstance(page, dict) and page.get("self_book_trials") is True


class TrialEmails(TrialNudgeEmailAdapter):
    def __init__(
        self,
        *,
        contacts: GuestContacts,
        occurrences: OccurrenceLookup,
        prospects: ProspectEmailer,
        send_repo: SendClaimRepository,
        **adapter: Any,
    ) -> None:
        super().__init__(**adapter)
        self._contacts = contacts
        self._occurrences = occurrences
        self._prospects = prospects
        self._send_repo = send_repo

    # --- public entry points (background tasks; never raise) ---------------

    async def guest_booked(self, trial: TrialRequest) -> None:
        await self._once(trial, f"trial_booked:{trial.assigned_occurrence_id}", self._booked)

    async def trial_decided(self, trial: TrialRequest) -> None:
        if trial.status == "approved" and trial.assigned_occurrence_id:
            key = f"trial_approved:{trial.assigned_occurrence_id}"
            await self._once(trial, key, self._approved)
        elif trial.status == "denied":
            await self._once(trial, "trial_denied", self._denied)

    async def trial_date_cancelled(
        self, *, trials: list[TrialRequest], start_at: datetime, reason: str
    ) -> None:
        for trial in trials:
            key = f"trial_date_cancelled:{start_at.isoformat()}"
            await self._once(trial, key, partial(self._cancelled, start_at=start_at))

    # --- templates ----------------------------------------------------------

    async def _booked(self, trial: TrialRequest, doc: dict[str, Any]) -> SendResult:
        when, where = await self._when_where(trial, doc)
        title, _location = await self._session(trial.requested_session_id)
        return await self._send_to(
            trial,
            doc,
            subject=f"Your free trial is booked: {title}",
            inner_html="".join(
                [
                    _para(
                        f"Your free trial in <strong>{html.escape(title)}</strong> is booked "
                        f"for {when}{where}."
                    ),
                    _para(
                        "Please arrive a few minutes early so the coach can say hello. "
                        "Wear comfortable sports clothes and bring water."
                    ),
                    _para("If you can no longer make it, just reply to this email."),
                ]
            ),
        )

    async def _approved(self, trial: TrialRequest, doc: dict[str, Any]) -> SendResult:
        when, where = await self._when_where(trial, doc)
        title, _location = await self._session(trial.requested_session_id)
        return await self._send_to(
            trial,
            doc,
            subject=f"Your free trial is confirmed: {title}",
            inner_html="".join(
                [
                    _para(
                        f"Good news: your free trial in <strong>{html.escape(title)}</strong> "
                        f"is confirmed for {when}{where}."
                    ),
                    _para("Wear comfortable sports clothes and bring water."),
                    _para("If you can no longer make it, just reply to this email."),
                ]
            ),
        )

    async def _denied(self, trial: TrialRequest, doc: dict[str, Any]) -> SendResult:
        title, _location = await self._session(trial.requested_session_id)
        reason = (trial.denial_reason or "").strip()
        return await self._send_to(
            trial,
            doc,
            subject=f"About your free trial request: {title}",
            inner_html="".join(
                [
                    _para(
                        "Thank you for asking for a free trial in "
                        f"<strong>{html.escape(title)}</strong>. We are not able to offer "
                        "that trial."
                    ),
                    _para(f"The academy said: {html.escape(reason)}") if reason else "",
                    _para("Reply to this email and we will help you find another class."),
                ]
            ),
        )

    async def _cancelled(
        self, trial: TrialRequest, doc: dict[str, Any], *, start_at: datetime
    ) -> SendResult:
        title, _location = await self._session(trial.requested_session_id)
        when = _when(ensure_utc(start_at).astimezone(_zone(doc)))
        return await self._send_to(
            trial,
            doc,
            subject=f"Your free trial on {when} is cancelled",
            inner_html="".join(
                [
                    _para(
                        f"Sorry: the academy had to call off {html.escape(title)} on {when}, "
                        "so your free trial cannot go ahead that day."
                    ),
                    _para(
                        "Your request is still with the academy, and they will offer you "
                        "another date. You can also reply to this email."
                    ),
                ]
            ),
        )

    # --- plumbing -----------------------------------------------------------

    async def _once(self, trial: TrialRequest, key: str, render: Any) -> None:
        try:
            # Background tasks run outside the request's tenant scope.
            with tenant_scope(trial.academy_id):
                doc = await self._academy_doc()
                if not trial_emails_enabled(doc):
                    return
                await send_once(
                    self._send_repo,
                    academy_id=trial.academy_id,
                    subject_id=trial.request_id,
                    nudge_key=key,
                    send=partial(render, trial, doc),
                )
        except Exception:
            logger.exception(
                "trial_email_failed", extra={"request_id": trial.request_id, "key": key}
            )

    async def _when_where(self, trial: TrialRequest, doc: dict[str, Any]) -> tuple[str, str]:
        occurrence = (
            await self._occurrences.get(trial.assigned_occurrence_id)
            if trial.assigned_occurrence_id
            else None
        )
        when = (
            _when(ensure_utc(occurrence.start_at).astimezone(_zone(doc)))
            if occurrence
            else "the date the academy confirms"
        )
        _title, location = await self._session(trial.requested_session_id)
        place = location or str(doc.get("address") or "")
        return when, (f" at {html.escape(place)}" if place else "")

    async def _send_to(
        self, trial: TrialRequest, doc: dict[str, Any], *, subject: str, inner_html: str
    ) -> SendResult:
        if trial.parent_user_id:
            return await self._send(
                doc,
                trial.parent_user_id,
                subject=subject,
                inner_html=inner_html,
                category=EmailCategory.TRANSACTIONAL,
            )
        contact = await self._contacts.get(trial.contact_id or "")
        if contact is None or not contact.email:
            return "skipped"
        outcome = await self._prospects.send(
            contact=contact,
            academy_doc=doc,
            subject=subject,
            inner_html=inner_html,
            category=EmailCategory.TRANSACTIONAL,
        )
        if outcome.ok:
            return "sent"
        if outcome.suppressed or outcome.failed_reason in ("no_email", "no_unsubscribe_link"):
            return "skipped"
        logger.warning(
            "trial_guest_email_failed",
            extra={"request_id": trial.request_id, "reason": outcome.failed_reason},
        )
        return "failed"


def _zone(doc: dict[str, Any]) -> ZoneInfo:
    return ZoneInfo(academy_clock_timezone(doc.get("timezone")))


def compose_trial_emails(db: Any, settings: Any) -> TrialEmails:
    from backend.v2.composition.digests import (
        _build_email_sender,
        compose_unsubscribe_link_builder,
    )
    from backend.v2.composition.trial_nudges import MongoTrialNudgeSendRepository
    from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
        MongoAudienceResolver,
    )
    from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
        MongoCrmContactRepository,
    )
    from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
        MongoSessionOccurrenceRepository,
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
    from backend.v2.contexts.identity.infrastructure.mongo_membership_repo import (
        MongoMembershipRepository,
    )
    from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository

    sender = _build_email_sender(settings, db)
    return TrialEmails(
        contacts=MongoCrmContactRepository(db),
        occurrences=MongoSessionOccurrenceRepository(db),
        prospects=ProspectEmailer(
            sender=sender, unsubscribe_links=compose_unsubscribe_link_builder(settings)
        ),
        send_repo=MongoTrialNudgeSendRepository(db),
        audiences=MongoAudienceResolver(db=db),
        memberships=MongoMembershipRepository(db),
        users=MongoUserRepository(db),
        academies=MongoAcademyRepository(db),
        students=MongoStudentRepository(db),
        sessions=MongoSessionRepository(db),
        sender=sender,
        frontend_url=getattr(settings, "frontend_url", None),
    )
