"""Trial nudges composition (AI strategy Phase 1, item 3).

Wires the three templated nudge jobs with their real collaborators:

* ``MongoTrialNudgeSendRepository``: the ``trial_nudge_sends`` claim, one row
  per ``(academy_id, subject_id, nudge_key)`` through ``claim_digest_send``
  (the one place the 2026-09-02 duplicate-send fix lives), the same shape as
  ``win_back_send_repo.py``. Here rather than in a context because it imports
  the communications context's claim helper for enrollment's and
  onboarding's use cases.
* ``TrialNudgeEmailAdapter``: the parent is a user, so each mail resolves the
  parent through the audience resolver and goes out through the gated
  ``EmailSendPort`` (bounce suppression and unsubscribe preferences apply as
  for every family-facing send), themed with the academy's brand.
* the academy's ``notifications.trial_nudges_enabled`` switch, read with a
  default of on by the same ``AcademyWinBackSwitch`` win-back uses.

Outside ``composition/admin.py`` for the wiring-line-budget reason
``win_back.py`` gives.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.v2.composition.prospect_email import academy_brand
from backend.v2.composition.win_back import AcademyWinBackSwitch
from backend.v2.contexts.communications.application.ports import (
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.models import (
    DigestSendStatus,
    SelectedRecipientsAudience,
)
from backend.v2.contexts.communications.infrastructure.digest_claim import claim_digest_send
from backend.v2.contexts.enrollment.application.use_cases.trial_nudges import (
    SendTrialNoShowFollowUps,
    SendTrialReminders,
)
from backend.v2.contexts.enrollment.domain.self_service import TrialRequest
from backend.v2.contexts.onboarding.application.use_cases.checkout_recovery import (
    SendCheckoutRecoveryNotices,
)
from backend.v2.contexts.onboarding.domain.models import Application
from backend.v2.shared.comms.claimed_send import SendResult
from backend.v2.shared.comms.email_theme import shell
from backend.v2.shared.comms.sender_identity import resolve_sender
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id
from backend.v2.shared.tenancy.academy_url import academy_frontend_url

logger = logging.getLogger(__name__)

#: The academy's "Trial nudges" switch (reminder, no-show, checkout recovery).
TRIAL_NUDGES_SWITCH_KEY = "trial_nudges_enabled"


class MongoTrialNudgeSendRepository(TenantScopedRepository):
    """``trial_nudge_sends``, unique on ``(academy_id, subject_id, digest_date)``
    (migration 0216). ``digest_date`` holds the nudge key: it is the field
    ``claim_digest_send`` matches on, and a nudge is per subject, not per day."""

    collection_name = "trial_nudge_sends"

    async def try_claim(
        self, *, academy_id: str, subject_id: str, nudge_key: str
    ) -> dict[str, Any] | None:
        doc = {
            "send_id": str(new_ulid()),
            "academy_id": academy_id,
            "subject_id": subject_id,
            "digest_date": nudge_key,
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
            recipient_field="subject_id",
            recipient_id=subject_id,
            digest_date=nudge_key,
        )

    async def mark_sent(self, academy_id: str, send_id: str) -> None:
        await self.collection.update_one(
            {"academy_id": academy_id, "send_id": send_id},
            {"$set": {"status": str(DigestSendStatus.SENT), "failed_reason": None}},
        )

    async def mark_failed(
        self, academy_id: str, send_id: str, reason: str, *, retryable: bool = True
    ) -> None:
        await self.collection.update_one(
            {"academy_id": academy_id, "send_id": send_id},
            {
                "$set": {
                    "status": str(DigestSendStatus.FAILED),
                    "failed_reason": reason,
                    "retryable": retryable,
                }
            },
        )


def _para(text: str) -> str:
    return f'<p style="margin:0 0 12px;">{text}</p>'


def _when(local_start: datetime) -> str:
    hour = local_start.hour % 12 or 12
    return f"{local_start:%A, %B} {local_start.day} at {hour}:{local_start:%M %p}"


class TrialNudgeEmailAdapter:
    """The three templated emails. Each reports ``"sent"``, ``"skipped"``
    (no address, or the recipient opted out: final) or ``"failed"`` (retry
    on a later tick). The academy document is read once per email."""

    def __init__(
        self,
        *,
        audiences: Any,
        academies: Any,
        students: Any,
        sessions: Any,
        sender: EmailSendPort,
        frontend_url: str | None,
    ) -> None:
        self._audiences = audiences
        self._academies = academies
        self._students = students
        self._sessions = sessions
        self._sender = sender
        self._frontend_url = frontend_url

    async def trial_reminder(self, *, trial: TrialRequest, local_start: datetime) -> SendResult:
        doc = await self._academy_doc()
        child = await self._child_name(trial)
        title, location = await self._session(trial.requested_session_id)
        where = f" at {html.escape(location)}" if location else ""
        return await self._send(
            doc,
            trial.parent_user_id,
            subject=f"Reminder: {child}'s free trial is tomorrow",
            inner_html="".join(
                [
                    _para(
                        f"The free trial for <strong>{html.escape(child)}</strong> in "
                        f"{html.escape(title)} is tomorrow, {_when(local_start)}{where}."
                    ),
                    _para(
                        "Please arrive a few minutes early so the coach can say hello. "
                        "Wear comfortable sports clothes and bring water."
                    ),
                    _para("If you can no longer make it, just reply to this email."),
                ]
            ),
            category=EmailCategory.TRANSACTIONAL,
        )

    async def trial_no_show(self, *, trial: TrialRequest) -> SendResult:
        doc = await self._academy_doc()
        child = await self._child_name(trial)
        title, _location = await self._session(trial.requested_session_id)
        requests_url = self._link(doc, "/parent/requests")
        return await self._send(
            doc,
            trial.parent_user_id,
            subject=f"We missed {child} at the trial",
            inner_html="".join(
                [
                    _para(
                        f"We missed <strong>{html.escape(child)}</strong> at the free trial "
                        f"in {html.escape(title)}."
                    ),
                    _para(
                        "Trials are free and there is no pressure. If you would like to "
                        "pick another date, reply to this email"
                        + (
                            f' or <a href="{html.escape(requests_url)}">request a new trial</a>.'
                            if requests_url
                            else "."
                        )
                    ),
                    _para("If this no longer applies, you can safely ignore this message."),
                ]
            ),
            category=EmailCategory.CAMPAIGN,
        )

    async def checkout_recovery(self, *, application: Application) -> SendResult:
        doc = await self._academy_doc()
        child = application.child_profile.first_name.strip() or "your child"
        title = ""
        if application.selected_session_id:
            title, _location = await self._session(application.selected_session_id)
        restart_url = self._link(doc, "/parent/onboarding")
        in_class = f" for {html.escape(title)}" if title else ""
        return await self._send(
            doc,
            application.parent_user_id,
            subject=f"Finish {child}'s registration",
            inner_html="".join(
                [
                    _para(
                        f"You started registering <strong>{html.escape(child)}</strong>"
                        f"{in_class}, but the registration was not completed."
                    ),
                    _para(
                        "No seat is held until it is finished. "
                        # Neither an expired checkout nor an expired draft can
                        # be resumed: the wizard starts a fresh registration.
                        + (
                            f'<a href="{html.escape(restart_url)}">Start the registration again</a>'
                            if restart_url
                            else "Sign in to start the registration again"
                        )
                        + " (it only takes a few minutes), or reply to this email if "
                        "something got in the way."
                    ),
                    _para("If this no longer applies, you can safely ignore this message."),
                ]
            ),
            category=EmailCategory.CAMPAIGN,
        )

    async def _academy_doc(self) -> dict[str, Any]:
        return await self._academies.find_by_id(current_academy_id()) or {}

    async def _child_name(self, trial: TrialRequest) -> str:
        if trial.student_id:
            students = await self._students.by_ids([trial.student_id])
            if students:
                return str(students[0].full_name)
        return (trial.prospective_child_name or "").strip() or "your child"

    async def _session(self, session_id: str) -> tuple[str, str]:
        session = await self._sessions.get(session_id)
        if session is None:
            return "class", ""
        return str(session.title), str(session.location or "")

    def _link(self, doc: dict[str, Any], path: str) -> str | None:
        base = academy_frontend_url(
            frontend_url=self._frontend_url, academy_slug=str(doc.get("slug") or "") or None
        )
        return f"{base}{path}" if base else None

    async def _send(
        self,
        doc: dict[str, Any],
        parent_user_id: str,
        *,
        subject: str,
        inner_html: str,
        category: EmailCategory,
    ) -> SendResult:
        recipient = await self._resolve_parent(parent_user_id)
        if recipient is None or not recipient.email:
            logger.info("trial_nudge_no_recipient", extra={"parent_id": parent_user_id})
            return "skipped"
        identity = resolve_sender(doc)
        outcome = await self._sender.send(
            recipient=recipient,
            subject=subject,
            body=shell(brand=academy_brand(doc), inner_html=inner_html),
            category=category,
            reply_to=identity.reply_to,
            sender_name=identity.sender_name,
        )
        if outcome.ok:
            return "sent"
        if outcome.suppressed:
            return "skipped"
        logger.warning(
            "trial_nudge_send_failed",
            extra={"parent_id": parent_user_id, "reason": outcome.failed_reason},
        )
        return "failed"

    async def _resolve_parent(self, parent_id: str) -> ResolvedRecipient | None:
        resolved = await self._audiences.resolve_selected_audience(
            SelectedRecipientsAudience(user_ids=(parent_id,))
        )
        return resolved[0] if resolved else None


@dataclass
class TrialNudgesComposition:
    send_trial_reminders: SendTrialReminders
    send_trial_no_show_follow_ups: SendTrialNoShowFollowUps
    send_checkout_recovery_notices: SendCheckoutRecoveryNotices


def compose_trial_nudges(db: Any, settings: Any) -> TrialNudgesComposition:
    from backend.v2.composition.digests import _build_email_sender
    from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
        MongoAudienceResolver,
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
    from backend.v2.contexts.enrollment.infrastructure.mongo_trial_request_repo import (
        MongoTrialRequestRepository,
    )
    from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
        MongoAcademyRepository,
    )
    from backend.v2.contexts.onboarding.infrastructure.mongo_application_repo import (
        MongoApplicationRepository,
    )

    academies = MongoAcademyRepository(db)
    notifier = TrialNudgeEmailAdapter(
        audiences=MongoAudienceResolver(db=db),
        academies=academies,
        students=MongoStudentRepository(db),
        sessions=MongoSessionRepository(db),
        sender=_build_email_sender(settings, db),
        frontend_url=getattr(settings, "frontend_url", None),
    )
    trials = MongoTrialRequestRepository(db)
    send_repo = MongoTrialNudgeSendRepository(db)
    switch = AcademyWinBackSwitch(academies, key=TRIAL_NUDGES_SWITCH_KEY)
    return TrialNudgesComposition(
        send_trial_reminders=SendTrialReminders(
            trials=trials,
            occurrences=MongoSessionOccurrenceRepository(db),
            send_repo=send_repo,
            notifier=notifier,
            switch=switch,
        ),
        send_trial_no_show_follow_ups=SendTrialNoShowFollowUps(
            trials=trials, send_repo=send_repo, notifier=notifier, switch=switch
        ),
        send_checkout_recovery_notices=SendCheckoutRecoveryNotices(
            applications=MongoApplicationRepository(db),
            send_repo=send_repo,
            notifier=notifier,
            switch=switch,
        ),
    )
