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

from typing import Protocol

from pydantic import BaseModel


class InviteEmailOutcome(BaseModel):
    """Outcome of a single reminder-email send attempt."""

    model_config = {"frozen": True}

    ok: bool
    failed_reason: str | None = None


class InviteEmailPort(Protocol):
    """Outbound email port, billing-local mirror of the identity context's port."""

    async def send_invite_email(
        self,
        *,
        user_id: str,
        email: str,
        display_name: str,
        subject: str,
        body: str,
    ) -> InviteEmailOutcome: ...


class ParentContact(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    email: str
    display_name: str


class ParentContactLookup(Protocol):
    async def get_parent_contact(self, parent_id: str, *, academy_id: str) -> ParentContact | None: ...


class CardSetupLinkPort(Protocol):
    """Builds the Stripe customer-portal URL where a parent adds a payment method."""

    async def create_card_setup_link(self, *, parent_id: str, academy_id: str, return_url: str) -> str: ...


class AcademyNameLookup(Protocol):
    async def get_academy_name(self, academy_id: str) -> str | None: ...


def _reminder_body(*, display_name: str, academy_name: str, setup_link: str) -> str:
    return f"""
<div style="font-family: -apple-system, 'Segoe UI', sans-serif; max-width: 520px; margin: 0 auto;">
  <h2 style="color: #0a0f1c;">Add a payment method for {academy_name}</h2>
  <p>Hi {display_name},</p>
  <p>Your account at <strong>{academy_name}</strong> is set up, but we don't have
  a payment method on file yet. Add one to keep your children's enrollment
  current.</p>
  <p style="margin: 24px 0;">
    <a href="{setup_link}"
       style="background: #2545d3; color: #ffffff; padding: 12px 20px;
              border-radius: 8px; text-decoration: none; font-weight: 600;">
      Add payment method
    </a>
  </p>
</div>
"""


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
