"""B3: send a staff-approved reply to a pipeline lead and log it.

The human approval of an AI draft, and just as valid for a reply typed by
hand (it works with AI off). The email goes through the prospect send path
(``composition/prospect_email.py``: lead opt-out gate, bounce suppression,
CAN-SPAM footer), behind the ``ReplyEmailer`` protocol here, then the send is
logged on the family contact log through ``LogFamilyContact`` (channel email,
the staff member as author, subject and body as the note). A lead with no
email or a suppressed address is refused with 409 and nothing is sent.
"""

from __future__ import annotations

from typing import Protocol

from backend.v2.contexts.crm.application.family_messages import FamilyContactLog, LogFamilyContact
from backend.v2.contexts.crm.application.ports import CrmContactRepository
from backend.v2.contexts.crm.application.use_cases.family_notes import Actor
from backend.v2.contexts.crm.domain.errors import (
    ContactNotFound,
    PipelineReplyNotSendable,
    PipelineReplySendFailed,
)
from backend.v2.contexts.crm.domain.models import CrmContact

#: A lead with no account logs under the same pseudo id the send path uses
#: (``communications/application/prospect_recipient.py``, README "Prospect sends").
LEAD_LOG_PREFIX = "crm_contact:"


class ReplyOutcome(Protocol):
    @property
    def ok(self) -> bool: ...

    @property
    def suppressed(self) -> bool: ...

    @property
    def failed_reason(self) -> str | None: ...


class ReplyEmailer(Protocol):
    async def send_reply(self, *, contact: CrmContact, subject: str, body: str) -> ReplyOutcome: ...


def contact_log_parent_id(contact: CrmContact) -> str:
    """The family the reply is logged on: the linked family when the lead has
    one, else the lead's own pseudo id."""
    return (
        contact.linked_family_id
        or contact.converted_parent_id
        or f"{LEAD_LOG_PREFIX}{contact.contact_id}"
    )


class SendPipelineReply:
    def __init__(
        self, contacts: CrmContactRepository, emailer: ReplyEmailer, log: LogFamilyContact
    ) -> None:
        self._contacts = contacts
        self._emailer = emailer
        self._log = log

    async def execute(
        self, *, academy_id: str, contact_id: str, subject: str, body: str, actor: Actor
    ) -> FamilyContactLog:
        contact = await self._contacts.get(contact_id)
        if contact is None:
            raise ContactNotFound("contact not found", contact_id=contact_id)
        if not contact.email:
            raise PipelineReplyNotSendable("This lead has no email address.", reason="no_email")
        outcome = await self._emailer.send_reply(contact=contact, subject=subject, body=body)
        if outcome.suppressed:
            raise PipelineReplyNotSendable(
                "This address opted out or bounced, so the academy cannot email it.",
                reason="suppressed",
            )
        if not outcome.ok:
            raise PipelineReplySendFailed(
                "The reply could not be sent. Try again.", reason=outcome.failed_reason
            )
        return await self._log.execute(
            academy_id=academy_id,
            parent_id=contact_log_parent_id(contact),
            channel="email",
            status="logged",
            note=f"Subject: {subject}\n\n{body}",
            actor=actor,
        )
