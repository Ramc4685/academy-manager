"""Composition for B3, the AI-drafted reply on the pipeline card (paid).

Wiring plus the small adapters that span contexts, attached at
``app.state.ai_pipeline`` and read by ``interfaces/admin/ai_pipeline_routes.py``:

* ``CrmInquirySource``: the lead's own message, the stored child age and the
  requested class title. By type it carries no name, email, phone or notes,
  so the model cannot see them (``test_ai_pipeline_reply`` pins it).
* ``PublicPageReplyContext``: what the academy already shows a stranger
  (``ListPublicCatalog``, prices only when the page shows them), the
  trials-open line and the public page URL.
* ``ProspectReplyEmailer``: the approved text through the SAME prospect send
  path the inquiry acknowledgement uses (``prospect_email.py``: opt-out
  gate, bounce suppression, CAN-SPAM footer), as TRANSACTIONAL.
* ``LeadOrFamilyDirectory``: lets ``LogFamilyContact`` log the send on the
  linked family, or on the lead's ``crm_contact:<id>`` pseudo id when the
  lead has no account yet.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, replace
from typing import Any

from backend.v2.composition.ai import AiComposition
from backend.v2.composition.families_crm import family_directory
from backend.v2.composition.prospect_email import ProspectEmailer
from backend.v2.composition.public_page_read import compose_public_page_read
from backend.v2.contexts.ai.application.use_cases.draft_pipeline_reply import (
    MAX_CLASS_LINES,
    DraftPipelineReply,
    InquiryFacts,
    ReplyContext,
)
from backend.v2.contexts.communications.application.ports import SendOutcome
from backend.v2.contexts.communications.application.prospect_recipient import (
    prospect_contact_id,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.infrastructure.mongo_prospect_opt_out_repo import (
    GATE_UNAVAILABLE,
)
from backend.v2.contexts.crm.application.family_messages import LogFamilyContact
from backend.v2.contexts.crm.application.ports import FamilyDirectory, FamilyRef
from backend.v2.contexts.crm.application.use_cases.send_pipeline_reply import SendPipelineReply
from backend.v2.contexts.crm.domain.models import CrmContact
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.contexts.crm.infrastructure.mongo_family_contact_log_repo import (
    MongoFamilyContactLogRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.public_catalog import (
    ListPublicCatalog,
    PublicClassView,
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
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.tenancy.academy_url import academy_frontend_url

TRIAL_OFFER_LINE = "Free trial classes are open; the academy confirms a date and time."


class CrmInquirySource:
    def __init__(self, contacts: Any, sessions: Any) -> None:
        self._contacts = contacts
        self._sessions = sessions

    async def inquiry_facts(self, contact_id: str) -> InquiryFacts | None:
        contact = await self._contacts.get(contact_id)
        if contact is None:
            return None
        interest = None
        if contact.requested_session_id:
            session = await self._sessions.get(contact.requested_session_id)
            interest = str(session.title) if session else None
        return InquiryFacts(
            inquiry_message=contact.message,
            child_ages=(contact.child_age,) if contact.child_age else (),
            interest=interest,
        )


def class_line(view: PublicClassView, *, program: str | None, currency: str) -> str:
    name = f"{program}: {view.title}" if program else view.title
    when = " ".join(
        part
        for part in (
            ", ".join(view.days_of_week),
            f"{view.start_time}-{view.end_time}" if view.start_time and view.end_time else "",
        )
        if part
    )
    line = f"{name} ({when})" if when else name
    if view.price is not None:
        line += f"; {currency} {view.price.amount_cents / 100:.2f} per {view.price.period}"
    return line


class PublicPageReplyContext:
    def __init__(
        self,
        academies: Any,
        profile: GetPublicAcademyProfile,
        catalog: ListPublicCatalog,
        frontend_url: str | None,
    ) -> None:
        self._academies = academies
        self._profile = profile
        self._catalog = catalog
        self._frontend_url = frontend_url

    async def reply_context(self) -> ReplyContext:
        academy_id = current_academy_id()
        profile = await self._profile.execute(academy_id)
        if profile is None:
            return ReplyContext("Your academy", None, None, ())
        settings = profile.settings
        catalog = await self._catalog.execute(
            academy_id,
            price_period_default=settings.price_period_default,
            show_price=settings.show_price,
            show_availability=False,
        )
        lines = [
            class_line(view, program=program.name, currency=profile.currency)
            for program in catalog.programs
            for view in program.classes
        ] + [
            class_line(view, program=None, currency=profile.currency)
            for view in catalog.ungrouped_classes
        ]
        url = None
        if settings.published:
            doc = await self._academies.find_by_id(academy_id) or {}
            url = (
                academy_frontend_url(
                    frontend_url=self._frontend_url, academy_slug=str(doc.get("slug") or "") or None
                )
                or None
            )
        return ReplyContext(
            academy_name=profile.name,
            public_page_url=url,
            trial_offer=TRIAL_OFFER_LINE if settings.trials_open else None,
            class_context=tuple(lines[:MAX_CLASS_LINES]),
        )


class UserFirstNames:
    def __init__(self, users: Any) -> None:
        self._users = users

    async def first_name(self, user_id: str) -> str | None:
        user = await self._users.get_by_id(user_id)
        name = (getattr(user, "display_name", None) or "").split()
        return name[0] if name else None


class ProspectReplyEmailer:
    """Plain text from the staff member, as escaped paragraphs inside the
    branded shell with the lead-facing unsubscribe footer."""

    def __init__(self, prospects: ProspectEmailer, academies: Any) -> None:
        self._prospects = prospects
        self._academies = academies

    async def send_reply(self, *, contact: CrmContact, subject: str, body: str) -> SendOutcome:
        doc = await self._academies.find_by_id(current_academy_id()) or {}
        inner = "".join(
            f'<p style="margin:0 0 12px;white-space:pre-wrap;">{html.escape(part.strip())}</p>'
            for part in body.split("\n\n")
            if part.strip()
        )
        outcome = await self._prospects.send(
            contact=contact,
            academy_doc=doc,
            subject=subject,
            inner_html=inner,
            # A staff answer to the lead's own request, under the form's tick.
            category=EmailCategory.TRANSACTIONAL,
        )
        # The opt-out store being down is a retryable failure, not an opt-out.
        if outcome.suppressed and outcome.failed_reason == GATE_UNAVAILABLE:
            return replace(outcome, suppressed=False)
        return outcome


@dataclass(frozen=True)
class _LeadRef:
    family_id: str
    parent_name: str | None


class LeadOrFamilyDirectory:
    def __init__(self, contacts: Any, families: FamilyDirectory) -> None:
        self._contacts = contacts
        self._families = families

    async def find(self, academy_id: str, family_id: str) -> FamilyRef | None:
        contact_id = prospect_contact_id(family_id)
        if contact_id is None:
            return await self._families.find(academy_id, family_id)
        contact = await self._contacts.get(contact_id)
        return _LeadRef(family_id, contact.name) if contact else None

    async def names(self, academy_id: str) -> Any:
        return await self._families.names(academy_id)


@dataclass(frozen=True)
class AiPipelineComposition:
    draft_reply: DraftPipelineReply
    send_reply: SendPipelineReply


def compose_ai_pipeline(db: Any, settings: Any, *, ai: AiComposition) -> AiPipelineComposition:
    from backend.v2.composition.digests import (
        _build_email_sender,
        compose_unsubscribe_link_builder,
    )

    academies = MongoAcademyRepository(db)
    contacts = MongoCrmContactRepository(db)
    public_page = compose_public_page_read(db)
    return AiPipelineComposition(
        draft_reply=DraftPipelineReply(
            llm=ai.llm,
            record_ai_call=ai.record_ai_call,
            entitlement=ai.entitlement,
            inquiries=CrmInquirySource(contacts, MongoSessionRepository(db)),
            context=PublicPageReplyContext(
                academies,
                public_page.get_academy_profile,
                public_page.list_catalog,
                getattr(settings, "frontend_url", None),
            ),
            staff=UserFirstNames(MongoUserRepository(db)),
        ),
        send_reply=SendPipelineReply(
            contacts,
            ProspectReplyEmailer(
                ProspectEmailer(
                    sender=_build_email_sender(settings, db),
                    unsubscribe_links=compose_unsubscribe_link_builder(settings),
                ),
                academies,
            ),
            LogFamilyContact(
                MongoFamilyContactLogRepository(db),
                LeadOrFamilyDirectory(contacts, family_directory(db)),
            ),
        ),
    )
