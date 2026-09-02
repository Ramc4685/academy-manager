"""Add-card reminder for parents who have a login account but no saved card.

No new Stripe flow: this reuses the Stripe customer portal
(``CreateCustomerPortalSession`` in ``parent_billing.py``) that already lets a
parent add/manage a payment method — the portal works at the parent level
(unlike the per-enrollment autopay setup checkout), which fits a reminder
that isn't scoped to any one child.

Mirrors the identity context's login-invite email shape (see
``send_login_invite.py``) but keeps its own local port/outcome types so this
context does not import identity directly.
"""

from __future__ import annotations

from html import escape
from urllib.parse import urlsplit

from backend.v2.contexts.billing.application.ports import (
    AcademyNameLookup,
    CardSetupLinkPort,
    InviteEmailOutcome,
    InviteEmailPort,
    ParentContactLookup,
)
from backend.v2.shared.comms.email_theme import INK, EmailBrand, button, shell


def _reminder_body(*, display_name: str, academy_name: str, setup_link: str) -> str:
    safe_display_name = escape(display_name)
    safe_academy_name = escape(academy_name)
    inner = (
        f'<h2 style="color:{INK};font-size:20px;margin:0 0 12px;">'
        f"Add a payment method for {safe_academy_name}</h2>"
        f"<p>Hi {safe_display_name},</p>"
        f"<p>Your account at <strong>{safe_academy_name}</strong> is set up, but we don't have "
        f"a payment method on file yet. Add one to keep your children's enrollment current.</p>"
        f'<p style="margin:24px 0;">{button("Add payment method", setup_link)}</p>'
    )
    return shell(brand=EmailBrand(academy_name=academy_name), inner_html=inner)


class SendAddCardReminder:
    def __init__(
        self,
        *,
        contacts: ParentContactLookup,
        links: CardSetupLinkPort,
        sender: InviteEmailPort,
        academies: AcademyNameLookup,
        return_url: str,
    ) -> None:
        self._contacts = contacts
        self._links = links
        self._sender = sender
        self._academies = academies
        self._return_url = return_url

    async def execute(self, *, academy_id: str, parent_id: str) -> InviteEmailOutcome:
        contact = await self._contacts.get_parent_contact(parent_id, academy_id=academy_id)
        if contact is None:
            return InviteEmailOutcome(ok=False, failed_reason="parent_not_found")

        setup_link = await self._links.create_card_setup_link(
            parent_id=parent_id, academy_id=academy_id, return_url=self._return_url
        )
        expected = urlsplit(self._return_url)
        actual = urlsplit(setup_link)
        if (
            actual.scheme not in {"http", "https"}
            or not actual.netloc
            or (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc)
        ):
            return InviteEmailOutcome(ok=False, failed_reason="card_setup_link_unavailable")
        academy_name = await self._academies.get_academy_name(academy_id) or "your academy"

        return await self._sender.send_invite_email(
            user_id=contact.parent_id,
            email=contact.email,
            display_name=contact.display_name,
            subject=f"Add a payment method for {academy_name}",
            body=_reminder_body(
                display_name=contact.display_name,
                academy_name=academy_name,
                setup_link=setup_link,
            ),
        )
