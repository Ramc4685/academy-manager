"""The prospect send path: email a ``crm_contacts`` row that is not a user.

Reused by every lead-facing message (inquiry acknowledgement first, trial
nudges next). ``ProspectEmailer.send`` is the one function to call; it owns
everything a prospect send needs and a user send already has elsewhere:

* a ``ResolvedRecipient`` under the stable ``crm_contact:<id>`` pseudo id, so
  the existing ``GatedEmailSendPort`` still applies provider bounce
  suppression by address;
* the email-keyed opt-out gate (``ProspectOptOutGate``, in the same seam);
* the CAN-SPAM footer with a lead-facing unsubscribe link to the backend
  page ``GET /api/v2/unsubscribe/prospect`` (the token is the same HMAC
  scheme as the user link, minted for the pseudo id). With no link to mint
  (no secret or frontend URL) nothing is sent: the account-preferences
  fallback footer means nothing to someone without an account;
* sender identity: platform From address under the academy's display name,
  replies to the academy (``resolve_sender``).

Consent: a prospect ticked ``contact_about_request``; that covers replies to
their own request (TRANSACTIONAL) and nothing marketing. Callers pass
``category`` explicitly so a future nurture send cannot inherit it.

Lives in composition because it spans CRM (the contact), identity (the
academy document) and communications (the send port) at once.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from backend.v2.contexts.communications.application.ports import (
    EmailSendPort,
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.application.prospect_recipient import (
    prospect_contact_id,
    prospect_recipient_id,
)
from backend.v2.contexts.communications.application.unsubscribe_footer import (
    render_unsubscribe_footer,
)
from backend.v2.contexts.communications.application.unsubscribe_token import (
    UnsubscribeLinkBuilder,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.infrastructure.mongo_prospect_opt_out_repo import (
    MongoProspectOptOutRepository,
)
from backend.v2.contexts.crm.domain.models import CrmContact
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.shared.comms.email_theme import EmailBrand, shell
from backend.v2.shared.comms.sender_identity import resolve_sender
from backend.v2.shared.tenancy.context import tenant_scope

logger = logging.getLogger(__name__)

PROSPECT_UNSUBSCRIBE_PATH = "/api/v2/unsubscribe/prospect"


class ProspectOptOuts(Protocol):
    async def opt_out(self, *, email: str, recipient_id: str, source: str = "link") -> None: ...


class ContactLookup(Protocol):
    async def get(self, contact_id: str) -> CrmContact | None: ...


def academy_brand(academy_doc: dict[str, Any]) -> EmailBrand:
    return EmailBrand(
        academy_name=str(academy_doc.get("display_name") or academy_doc.get("name") or "")
        or "Your academy",
        brand_color=academy_doc.get("brand_color"),
        logo_url=academy_doc.get("logo_url"),
    )


@dataclass(frozen=True)
class ProspectEmailer:
    """Sends one themed, footered, gated email to a prospect.

    Must be called inside ``tenant_scope`` of the contact's academy (the
    opt-out gate reads a tenant-scoped collection).
    """

    sender: EmailSendPort
    unsubscribe_links: UnsubscribeLinkBuilder

    async def send(
        self,
        *,
        contact: CrmContact,
        academy_doc: dict[str, Any],
        subject: str,
        inner_html: str,
        category: EmailCategory,
        reply_to: str | None = None,
    ) -> SendOutcome:
        if not contact.email:
            return SendOutcome(ok=False, provider_message_id=None, failed_reason="no_email")
        recipient_id = prospect_recipient_id(contact.contact_id)
        unsubscribe_url = self.unsubscribe_links.build(
            academy_id=contact.academy_id,
            user_id=recipient_id,
            academy_slug=str(academy_doc.get("slug") or "") or None,
            path=PROSPECT_UNSUBSCRIBE_PATH,
        )
        if unsubscribe_url is None:
            # The shared fallback footer points at account preferences, which a
            # prospect does not have; never mail a stranger without a working
            # opt-out (no unsubscribe secret or frontend URL configured).
            return SendOutcome(
                ok=False, provider_message_id=None, failed_reason="no_unsubscribe_link"
            )
        identity = resolve_sender(academy_doc)
        return await self.sender.send(
            recipient=ResolvedRecipient(
                user_id=recipient_id, email=contact.email, display_name=contact.name
            ),
            subject=subject,
            body=shell(
                brand=academy_brand(academy_doc),
                inner_html=inner_html,
                footer_html=render_unsubscribe_footer(unsubscribe_url),
            ),
            reply_to=reply_to or identity.reply_to,
            category=category,
            sender_name=identity.sender_name,
        )


@dataclass(frozen=True)
class UnsubscribeProspect:
    """Record a prospect's opt-out from the token's pseudo id.

    The token carries only ``crm_contact:<id>``; the address it stands for is
    read from the contact row under the token's academy, so an opt-out is
    always stored against the email the academy actually holds.
    """

    contacts: ContactLookup
    opt_outs: ProspectOptOuts

    async def execute(self, *, academy_id: str, recipient_id: str) -> bool:
        contact_id = prospect_contact_id(recipient_id)
        if contact_id is None:
            return False
        with tenant_scope(academy_id):
            contact = await self.contacts.get(contact_id)
            if contact is None or not contact.email:
                return False
            await self.opt_outs.opt_out(email=contact.email, recipient_id=recipient_id)
        return True


def compose_unsubscribe_prospect(db: Any) -> UnsubscribeProspect:
    return UnsubscribeProspect(
        contacts=MongoCrmContactRepository(db),
        opt_outs=MongoProspectOptOutRepository(db),
    )
