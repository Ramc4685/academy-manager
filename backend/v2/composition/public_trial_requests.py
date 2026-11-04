"""Composition for the anonymous public trial request (public tenant page, Lane B4).

Wiring for ``POST /api/v2/public/trial-requests`` plus the one adapter it
needs that spans contexts: the academy notification email. Zero lines in
``composition/admin.py`` (at its line budget). Attached at
``app.state.public_trial_requests`` by ``main.py`` and read by
``interfaces/public/trial_request_routes.py``.

The notification lives here, not in a context, for the same reason
``registration_decision_email.py`` does: it needs CRM (the contact),
identity (the academy's name and colour) and communications (owner
recipients, the gated send port) at once, and no bounded context may import
another.

**It never runs on the response path.** The route hands it to FastAPI's
``BackgroundTasks`` for every accepted submission, new, repeated or honeypot
alike, and the adapter itself decides whether anything is sent (only for a
newly created contact). The HTTP response is therefore the same bytes and the
same work whether or not the inquiry was already on file, and a mail outage
can never fail or slow a submission.

The same task also sends the family ONE acknowledgement (AI strategy Phase 1
#2) through the prospect send path in ``composition/prospect_email.py``:
class named, seat available or waitlisted, what happens next. It is a
TRANSACTIONAL reply to their own request under the mandatory
``contact_about_request`` tick, claimed once per contact on the row itself
and at most once per inbox per academy per UTC day (the form takes any address
unverified, so a stranger's inbox must not be fillable from here; ``+tag`` and
Gmail-dot variants count as the same inbox).
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Protocol

from backend.v2.composition.prospect_email import ProspectEmailer, academy_brand
from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.models import AcademyAudience, AudienceRole
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    MongoAudienceResolver,
)
from backend.v2.contexts.crm.application.use_cases.create_contact import CreateContact
from backend.v2.contexts.crm.application.use_cases.submit_website_inquiry import (
    SubmitWebsiteInquiry,
)
from backend.v2.contexts.crm.domain.models import CrmContact, canonical_mailbox
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.contexts.crm.infrastructure.mongo_inquiry_ack_throttle_repo import (
    MongoInquiryAckThrottleRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.public_class_choice import (
    ResolvePublicClassChoice,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.identity.application.public_academy_profile import (
    GetPublicAcademyProfile,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.comms.email_theme import EmailBrand, shell
from backend.v2.shared.comms.sender_identity import resolve_sender
from backend.v2.shared.tenancy.context import tenant_scope

logger = logging.getLogger(__name__)

#: Who hears about a website lead: the academy's owners (roadmap decision:
#: owner, billing, front desk; the owner runs the pipeline until the CRM
#: screens ship). An academy with no owner address falls back to its public
#: contact email (brief section 5, "a lead must still reach a human").
_RECIPIENT_ROLE: Final[AudienceRole] = "owner"

#: Most acknowledgements one academy sends in any hour, whatever the inboxes:
#: a bot cycling fresh addresses through the form cannot turn the academy's
#: sender name into a spam cannon. Far above a real academy's inquiry rate.
_ACK_ACADEMY_HOURLY_CAP: Final = 20


class AcademyLookup(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...


class AcknowledgementClaims(Protocol):
    async def try_claim_acknowledgement(self, contact_id: str, *, at: datetime) -> bool: ...

    async def release_acknowledgement(self, contact_id: str) -> None: ...


class InboxAcknowledgementClaims(Protocol):
    async def try_claim(self, mailbox: str, *, at: datetime) -> bool: ...

    async def release(self, mailbox: str, *, at: datetime) -> None: ...

    async def count_since(self, since: datetime) -> int: ...


def _row(label: str, value: str | None) -> str:
    shown = html.escape(value) if value else '<span style="color:#64748b;">Not given</span>'
    return (
        '<tr><td style="padding:6px 12px 6px 0;color:#64748b;vertical-align:top;'
        f'white-space:nowrap;">{html.escape(label)}</td>'
        f'<td style="padding:6px 0;vertical-align:top;">{shown}</td></tr>'
    )


def render_trial_request_alert(
    *,
    brand: EmailBrand,
    contact: CrmContact,
    class_title: str | None,
) -> tuple[str, str]:
    """Subject and themed HTML body for the academy's new-lead email.

    Every value is caller-supplied text from an anonymous form, so each one is
    HTML-escaped and none is ever placed in a link or an attribute.
    """
    is_trial = contact.pipeline_status == "trial"
    kind = "trial request" if is_trial else "inquiry"
    subject = f"New {kind} from {contact.name}"
    message_html = (
        '<p style="margin:16px 0 4px;font-weight:600;">Their message</p>'
        '<p style="margin:0;white-space:pre-wrap;">'
        f"{html.escape(contact.message)}</p>"
        if contact.message
        else ""
    )
    marketing = "Yes" if contact.consent.marketing else "No"
    inner = "".join(
        [
            f'<h2 style="margin:0 0 12px;">{html.escape(subject)}</h2>',
            '<p style="margin:0 0 14px;">',
            (
                "Someone asked for a free trial on your public page."
                if is_trial
                else "Someone asked to hear from you on your public page."
            ),
            " Reply to this email to answer them directly.</p>",
            '<table role="presentation" style="border-collapse:collapse;font-size:14px;">',
            _row("Name", contact.name),
            _row("Email", contact.email),
            _row("Phone", contact.phone_digits),
            _row("Player's age", contact.child_age),
            _row("Class", class_title or ("Not sure yet" if is_trial else None)),
            _row("News and offers", marketing),
            "</table>",
            message_html,
            '<p style="margin:18px 0 0;font-size:13px;color:#64748b;">'
            "They agreed to be contacted about this request. Nothing is booked or "
            "charged until you confirm a date with them.</p>",
        ]
    )
    return subject, shell(brand=brand, inner_html=inner)


def render_inquiry_acknowledgement(
    *,
    academy_name: str,
    contact: CrmContact,
    class_title: str | None,
    can_reply: bool,
) -> tuple[str, str]:
    """Subject and inner HTML of the family's acknowledgement.

    Trial (a seat is there): the academy will confirm a date. Lead: the
    chosen class is full (waitlist) or nothing is open yet (we will tell you).
    Nothing the submitter typed appears in it: the form takes any address
    unverified, so the greeting carries no name a stranger could be made to
    read. The class title and academy name are the academy's own, escaped.
    """
    is_trial = contact.pipeline_status == "trial"
    safe_academy = html.escape(academy_name)
    safe_class = html.escape(class_title) if class_title else None
    if is_trial:
        subject = f"Your free trial request at {academy_name}"
        asked = (
            f"Thanks for asking for a free trial in <strong>{safe_class}</strong>."
            if safe_class
            else "Thanks for asking for a free trial."
        )
        status = (
            "A seat is available. The academy will be in touch to confirm a date and "
            "time; nothing is booked or charged until then."
        )
    else:
        subject = f"Your inquiry at {academy_name}"
        asked = (
            f"Thanks for asking about <strong>{safe_class}</strong>."
            if safe_class
            else f"Thanks for getting in touch with {safe_academy}."
        )
        status = (
            f"{safe_class} is full right now, so you are on the waitlist. The academy "
            "will tell you as soon as a seat opens."
            if safe_class
            else "Classes are not taking new players right now. The academy will tell "
            "you as soon as they open."
        )
    reply = " Reply to this email if you have a question." if can_reply else ""
    inner = "".join(
        [
            '<h2 style="margin:0 0 12px;">Hello,</h2>',
            f'<p style="margin:0 0 14px;">{asked}</p>',
            f'<p style="margin:0 0 14px;">{status}{reply}</p>',
            '<p style="margin:18px 0 0;font-size:13px;color:#64748b;">'
            f"You are getting this one email because you asked {safe_academy} to "
            "contact you about this request.</p>",
        ]
    )
    return subject, inner


class TrialRequestOwnerEmail:
    """Emails the academy's owners about a NEW website contact, once, and
    acknowledges the family once (``render_inquiry_acknowledgement``)."""

    def __init__(
        self,
        *,
        academies: AcademyLookup,
        audiences: AudienceResolver,
        sender: EmailSendPort,
        contacts: AcknowledgementClaims,
        inboxes: InboxAcknowledgementClaims,
        prospects: ProspectEmailer,
    ) -> None:
        self._academies = academies
        self._audiences = audiences
        self._sender = sender
        self._contacts = contacts
        self._inboxes = inboxes
        self._prospects = prospects

    async def notify(
        self,
        *,
        academy_id: str,
        contact: CrmContact | None,
        created: bool,
        class_title: str | None,
    ) -> None:
        """Background task body. Never raises; a no-op unless ``created``.

        Called for every accepted submission so the response path is uniform;
        a repeat (``created=False``) or a honeypot hit (``contact=None``) ends
        here without a read or a send.
        """
        if contact is None or not created:
            return
        try:
            with tenant_scope(academy_id):
                await self._send_all(contact, class_title)
        except Exception:
            logger.exception(
                "public.trial_request_alert_failed",
                extra={"contact_id": contact.contact_id},
            )

    async def _send_all(self, contact: CrmContact, class_title: str | None) -> None:
        doc = await self._academies.find_by_id(contact.academy_id) or {}
        brand = academy_brand(doc)
        subject, body = render_trial_request_alert(
            brand=brand, contact=contact, class_title=class_title
        )
        identity = resolve_sender(doc)
        sender_name = identity.sender_name
        for recipient in await self._recipients(doc):
            outcome = await self._sender.send(
                recipient=recipient,
                subject=subject,
                body=body,
                # Staff reply to the family, so reply-to stays the family's
                # address; only the display name follows the academy (L9a).
                reply_to=contact.email,
                # TRANSACTIONAL: the record of a request someone made to this
                # academy; it must reach a human and carries no unsubscribe.
                category=EmailCategory.TRANSACTIONAL,
                sender_name=sender_name,
            )
            if not outcome.ok and not outcome.suppressed:
                logger.warning(
                    "public.trial_request_alert_send_failed",
                    extra={"contact_id": contact.contact_id, "reason": outcome.failed_reason},
                )
        # The owner alert is the message that must land, so it went first;
        # whatever the acknowledgement raises is logged by notify() after it.
        # Replies go only to the academy's configured reply-to: an owner's
        # own address is never shown to an anonymous submitter.
        await self._acknowledge(contact, doc, brand.academy_name, class_title, identity.reply_to)

    async def _acknowledge(
        self,
        contact: CrmContact,
        doc: dict[str, Any],
        academy_name: str,
        class_title: str | None,
        reply_to: str | None,
    ) -> None:
        mailbox = canonical_mailbox(contact.email)
        if not contact.consent.contact_about_request or not mailbox:
            return
        now = datetime.now(UTC)
        # shortcut: count-then-claim is not atomic, so concurrent tasks can
        # overshoot the hourly cap by a few; make it a counter doc if that matters.
        if await self._inboxes.count_since(now - timedelta(hours=1)) >= _ACK_ACADEMY_HOURLY_CAP:
            logger.warning(
                "public.trial_request_ack_academy_capped",
                extra={"contact_id": contact.contact_id},
            )
            return
        # A different child name files a new contact for the same address, and
        # victim+1@ or v.i.c.t.i.m@gmail.com are new addresses for the same
        # inbox, so the per-contact claim alone would let a resubmitter fill a
        # stranger's inbox from the academy's name. One insert under a unique
        # (academy, canonical inbox, UTC day) index: exactly one task wins.
        if not await self._inboxes.try_claim(mailbox, at=now):
            logger.info("public.trial_request_ack_capped", extra={"contact_id": contact.contact_id})
            return
        # Claim on the contact row: a second run for the same contact finds the
        # claim taken and sends nothing. A hard provider failure gives both
        # claims back, so the row says truthfully that no email went out.
        # shortcut: nothing re-sends a released claim yet; add a sweep when the
        # logs show misses.
        if not await self._contacts.try_claim_acknowledgement(contact.contact_id, at=now):
            await self._inboxes.release(mailbox, at=now)
            return
        subject, inner = render_inquiry_acknowledgement(
            academy_name=academy_name,
            contact=contact,
            class_title=class_title,
            can_reply=reply_to is not None,
        )
        settled = False
        try:
            outcome = await self._prospects.send(
                contact=contact,
                academy_doc=doc,
                subject=subject,
                inner_html=inner,
                # TRANSACTIONAL: the reply to a request this family made, under
                # the consent tick the form requires. Nothing here is marketing.
                category=EmailCategory.TRANSACTIONAL,
                reply_to=reply_to,
            )
            # A gate refusal is terminal (retrying re-hits the gate), so it
            # keeps the claim; only a provider failure releases it.
            settled = outcome.ok or outcome.suppressed
            if not settled:
                logger.warning(
                    "public.trial_request_ack_send_failed",
                    extra={"contact_id": contact.contact_id, "reason": outcome.failed_reason},
                )
        finally:
            if not settled:
                await self._contacts.release_acknowledgement(contact.contact_id)
                await self._inboxes.release(mailbox, at=now)

    async def _recipients(self, academy_doc: dict[str, Any]) -> list[ResolvedRecipient]:
        found = await self._audiences.resolve_academy_audience(
            AcademyAudience(role=_RECIPIENT_ROLE)
        )
        seen: set[str] = set()
        unique: list[ResolvedRecipient] = []
        for recipient in found:
            email = (recipient.email or "").strip().lower()
            if not email or email in seen:
                continue
            seen.add(email)
            unique.append(recipient)
        if unique:
            return unique
        fallback = str(academy_doc.get("contact_email") or "").strip()
        if not fallback:
            logger.warning("public.trial_request_alert_no_recipient")
            return []
        return [
            ResolvedRecipient(
                user_id=f"academy-contact:{academy_doc.get('academy_id') or ''}",
                email=fallback,
                display_name=None,
            )
        ]


@dataclass(frozen=True)
class PublicTrialRequests:
    get_academy_profile: GetPublicAcademyProfile
    resolve_class_choice: ResolvePublicClassChoice
    submit_inquiry: SubmitWebsiteInquiry
    notifier: TrialRequestOwnerEmail


def compose_public_trial_requests(db: Any, settings: Any) -> PublicTrialRequests:
    """``_build_email_sender`` is the one construction site that hands dev and
    CI the stub port and production the gated Resend one."""
    from backend.v2.composition.digests import (
        _build_email_sender,
        compose_unsubscribe_link_builder,
    )

    academies = MongoAcademyRepository(db)
    contacts = MongoCrmContactRepository(db)
    sender = _build_email_sender(settings, db)
    return PublicTrialRequests(
        get_academy_profile=GetPublicAcademyProfile(academies),
        resolve_class_choice=ResolvePublicClassChoice(MongoSessionRepository(db)),
        submit_inquiry=SubmitWebsiteInquiry(CreateContact(contacts)),
        notifier=TrialRequestOwnerEmail(
            academies=academies,
            audiences=MongoAudienceResolver(db=db),
            sender=sender,
            contacts=contacts,
            inboxes=MongoInquiryAckThrottleRepository(db),
            prospects=ProspectEmailer(
                sender=sender,
                unsubscribe_links=compose_unsubscribe_link_builder(settings),
            ),
        ),
    )
