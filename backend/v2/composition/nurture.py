"""Lead nurture sequence composition (AI strategy Phase 3, C1).

Wires ``SendNurtureSteps`` (the daily ``send_nurture_steps`` job) and
``ManageNurtureSequence`` (the admin editor) with:

* ``AcademyNurtureSettings``: the sequence on the academy document under
  ``crm_nurture`` (``enabled`` default off, ``enabled_at``, ``steps``), read
  and written for the academy named, never another tenant's document;
* ``MongoNurtureSendRepository``: ``nurture_sends``, one claim per
  ``(academy_id, subject_id = contact_id, digest_date = "nurture:day_<n>")``
  through ``claim_digest_send``, unique index from migration 0225. Each row
  carries ``channel: "email"`` so C2's SMS steps are a new channel value, not
  a new key;
* ``NurtureEmailAdapter``: renders the owner's step and sends it through
  ``ProspectEmailer`` (``crm_contact:<id>`` recipient, ``ProspectOptOutGate``,
  bounce suppression, unsubscribe footer) as ``EmailCategory.CAMPAIGN``;
* the opt-out store and the family contact log as the stop lookups.

Here rather than in the CRM context because it spans CRM, identity (the
academy document), enrollment (the class and its seat band) and
communications (the send path, the claim helper) at once.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.v2.composition.prospect_email import ProspectEmailer, academy_brand
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.models import DigestSendStatus
from backend.v2.contexts.communications.infrastructure.digest_claim import claim_digest_send
from backend.v2.contexts.communications.infrastructure.mongo_prospect_opt_out_repo import (
    GATE_UNAVAILABLE,
    MongoProspectOptOutRepository,
)
from backend.v2.contexts.crm.application.use_cases.nurture_sequence import (
    ManageNurtureSequence,
    SendNurtureSteps,
)
from backend.v2.contexts.crm.domain.models import CrmContact
from backend.v2.contexts.crm.domain.nurture import (
    NurtureSequence,
    NurtureStep,
    render_html,
    render_subject,
    seat_band_text,
)
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.contexts.crm.infrastructure.mongo_family_contact_log_repo import (
    MongoFamilyContactLogRepository,
)
from backend.v2.contexts.enrollment.domain.public_catalog import seat_band
from backend.v2.contexts.identity.domain.public_page import PUBLIC_PAGE_FIELD, PublicPageSettings
from backend.v2.shared.comms.claimed_send import SendResult
from backend.v2.shared.comms.sender_identity import resolve_sender
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository
from backend.v2.shared.tenancy.academy_url import academy_frontend_url

logger = logging.getLogger(__name__)

#: The academy document field. A separate "nurture" consent tick on the
#: public form (an open owner decision) would change only which consent
#: ``stop_reason`` reads, not this.
NURTURE_FIELD = "crm_nurture"
NURTURE_CHANNEL = "email"
#: The editor's example class, shown only in the preview.
EXAMPLE_CLASS = "Junior Beginners"


class AcademyNurtureSettings:
    def __init__(self, academies: Any) -> None:
        self._academies = academies

    async def get(self, academy_id: str) -> NurtureSequence:
        doc = await self._academies.find_by_id(academy_id)
        stored = (doc or {}).get(NURTURE_FIELD) if isinstance(doc, dict) else None
        if not isinstance(stored, dict):
            return NurtureSequence()
        steps = tuple(
            NurtureStep(
                day=int(s.get("day") or 0),
                subject=str(s.get("subject") or ""),
                body=str(s.get("body") or ""),
            )
            for s in stored.get("steps") or ()
            if isinstance(s, dict)
        )
        enabled_at = stored.get("enabled_at")
        if isinstance(enabled_at, datetime) and enabled_at.tzinfo is None:
            enabled_at = enabled_at.replace(tzinfo=UTC)  # BSON reads back naive (#706)
        return NurtureSequence(
            enabled=stored.get("enabled") is True,
            enabled_at=enabled_at if isinstance(enabled_at, datetime) else None,
            steps=steps,
        )

    async def save(
        self, academy_id: str, sequence: NurtureSequence, *, user_id: str, at: datetime
    ) -> None:
        updated = await self._academies.update_by_id(
            academy_id,
            {
                NURTURE_FIELD: {
                    "enabled": sequence.enabled,
                    "enabled_at": sequence.enabled_at,
                    "steps": [
                        {"day": s.day, "subject": s.subject, "body": s.body} for s in sequence.steps
                    ],
                    "updated_by": user_id,
                    "updated_at": at,
                }
            },
        )
        if updated is None:
            raise LookupError(f"no academy document for {academy_id}")


class MongoNurtureSendRepository(TenantScopedRepository):
    """``nurture_sends``, unique on ``(academy_id, subject_id, digest_date)``
    (migration 0225); ``digest_date`` holds the step key, the field
    ``claim_digest_send`` matches on."""

    collection_name = "nurture_sends"

    async def try_claim(
        self, *, academy_id: str, subject_id: str, nudge_key: str
    ) -> dict[str, Any] | None:
        doc = {
            "send_id": str(new_ulid()),
            "academy_id": academy_id,
            "subject_id": subject_id,
            "digest_date": nudge_key,
            "channel": NURTURE_CHANNEL,
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


class ContactLogConversations:
    """A logged contact on the lead (a staff reply from the pipeline, a call,
    a WhatsApp handoff) means a person is talking to them: the sequence stops."""

    def __init__(self, log: Any) -> None:
        self._log = log

    async def has_logged_contact(self, parent_id: str) -> bool:
        return bool(await self._log.list_for_family(parent_id, limit=1))


class NurtureEmailAdapter:
    def __init__(
        self,
        *,
        academies: Any,
        sessions: Any,
        prospects: ProspectEmailer,
        frontend_url: str | None,
    ) -> None:
        self._academies = academies
        self._sessions = sessions
        self._prospects = prospects
        self._frontend_url = frontend_url

    async def example_values(self, academy_id: str) -> dict[str, str]:
        doc = await self._academies.find_by_id(academy_id) or {}
        return await self._values(doc, None)

    async def send_step(self, *, contact: CrmContact, step: NurtureStep) -> SendResult:
        doc = await self._academies.find_by_id(contact.academy_id) or {}
        values = await self._values(doc, contact)
        outcome = await self._prospects.send(
            contact=contact,
            academy_doc=doc,
            subject=render_subject(step.subject, values),
            inner_html=render_html(step.body, values),
            # Marketing under the lead's own consent.marketing tick, so the
            # unsubscribe footer and the opt-out gate apply.
            category=EmailCategory.CAMPAIGN,
            reply_to=resolve_sender(doc).reply_to,
        )
        if outcome.ok:
            return "sent"
        if outcome.suppressed and outcome.failed_reason != GATE_UNAVAILABLE:
            return "skipped"
        if outcome.failed_reason == "no_email":
            return "skipped"
        logger.warning(
            "nurture_step_send_failed",
            extra={"contact_id": contact.contact_id, "reason": outcome.failed_reason},
        )
        return "failed"

    async def _values(self, doc: dict[str, Any], contact: CrmContact | None) -> dict[str, str]:
        link = academy_frontend_url(
            frontend_url=self._frontend_url, academy_slug=str(doc.get("slug") or "") or None
        )
        if contact is None:
            class_title, band = EXAMPLE_CLASS, seat_band_text("few", 3)
        else:
            class_title, band = await self._class_and_band(doc, contact.requested_session_id)
        return {
            "academy_name": academy_brand(doc).academy_name,
            "class": class_title,
            "seat_band": band,
            "booking_link": f"{link}/" if link else "",
        }

    async def _class_and_band(self, doc: dict[str, Any], session_id: str | None) -> tuple[str, str]:
        if not session_id:
            return "our classes", seat_band_text(None)
        rows = await self._sessions.available_for_public_catalog()
        row = next((r for r in rows if r.profile.session_id == session_id), None)
        if row is None or row.profile.published is not True:
            return "our classes", seat_band_text(None)
        page = PublicPageSettings.from_stored(doc.get(PUBLIC_PAGE_FIELD))
        band, left = seat_band(row.capacity, row.occupied_seats, page.seats_left_threshold)
        if band == "few" and not page.show_availability:
            band, left = "open", None  # the academy hides seat counts publicly
        return str(row.title), seat_band_text(band, left)


@dataclass(frozen=True)
class NurtureComposition:
    send_steps: SendNurtureSteps
    manage: ManageNurtureSequence


def compose_nurture(db: Any, settings: Any) -> NurtureComposition:
    """``_build_email_sender`` is the one construction site that hands dev and
    CI the stub port and production the gated Resend one."""
    from backend.v2.composition.digests import (
        _build_email_sender,
        compose_unsubscribe_link_builder,
    )
    from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
        MongoSessionRepository,
    )
    from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
        MongoAcademyRepository,
    )

    academies = MongoAcademyRepository(db)
    store = AcademyNurtureSettings(academies)
    notifier = NurtureEmailAdapter(
        academies=academies,
        sessions=MongoSessionRepository(db),
        prospects=ProspectEmailer(
            sender=_build_email_sender(settings, db),
            unsubscribe_links=compose_unsubscribe_link_builder(settings),
        ),
        frontend_url=getattr(settings, "frontend_url", None),
    )
    return NurtureComposition(
        send_steps=SendNurtureSteps(
            settings=store,
            contacts=MongoCrmContactRepository(db),
            opt_outs=MongoProspectOptOutRepository(db),
            conversations=ContactLogConversations(MongoFamilyContactLogRepository(db)),
            send_repo=MongoNurtureSendRepository(db),
            notifier=notifier,
        ),
        manage=ManageNurtureSequence(store, notifier),
    )
