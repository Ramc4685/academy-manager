"""Admin BFF: the family Messages tab (People CRM spec §4, Phase 6; roadmap L4c).

* ``GET /admin/families/{parent_id}/messages``: one newest-first thread of the
  emails the app sent this family (campaigns, the parent digest,
  absence-notice confirmations, invoice copies to family contacts) with their
  delivery status, and the contacts staff logged by hand.
* ``POST /admin/families/{parent_id}/messages/log``: log a WhatsApp, SMS or
  email sent from the staff member's own app (``status: not_logged`` when the
  "Did you send it?" prompt was dismissed), a call, or a talk in person.
* ``PATCH /admin/families/{parent_id}/messages/log/{log_id}``: complete a
  ``not_logged`` handoff (the staff member who logged it, or an owner).

Nothing here sends a message: the app never sends SMS or WhatsApp (a later
phase). ``require_persona("admin")`` (a coach or parent gets the
wrong-persona 404); another academy's family, or no family, is a 404. No
route here returns money, so every staff tier sees the same thread.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from backend.v2.contexts.crm.application.family_messages import (
    MAX_CONTACT_LOG_NOTE_LEN,
    FamilyContactLog,
    MessageEntry,
    contact_log_entry,
)
from backend.v2.contexts.crm.application.use_cases.family_notes import Actor
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id

router = APIRouter(tags=["admin.families"])

# A little above the domain cap so the domain's clearer message wins.
_NOTE_CAP = MAX_CONTACT_LOG_NOTE_LEN * 2

Channel = Literal["email", "whatsapp", "sms", "call", "in_person"]


def get_family_messages(request: Request) -> Any:
    services = getattr(request.app.state, "admin_family_index", None)
    messages = getattr(services, "messages", None) if services is not None else None
    if messages is None:
        raise HTTPException(status_code=503, detail="family messages are not configured")
    return messages


def _academy_id(claims: AuthClaims) -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return claims.academy_id


def _actor(claims: AuthClaims) -> Actor:
    return Actor(user_id=claims.user_id, roles=tuple(claims.roles))


class FamilyMessageView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str
    at: datetime
    channel: Channel
    source: Literal["campaign", "digest", "absence_notice", "invoice_copy", "staff_log"]
    status: Literal["queued", "sent", "opened", "failed", "logged", "not_logged"]
    summary: str
    detail: str | None = None
    recipient: str | None = None
    author_user_id: str | None = None
    failed_reason: str | None = None
    log_id: str | None = None
    can_complete: bool


class FamilyMessagesView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family_id: str
    entries: list[FamilyMessageView]
    warnings: list[str]


class LogContactBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Channel
    status: Literal["logged", "not_logged"] = "logged"
    note: str | None = Field(default=None, max_length=_NOTE_CAP)


class CompleteContactLogBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["logged"] = "logged"
    note: str | None = Field(default=None, max_length=_NOTE_CAP)


def _can_complete(entry: MessageEntry, claims: AuthClaims) -> bool:
    if entry.status != "not_logged":
        return False
    return entry.author_user_id == claims.user_id or "owner" in set(claims.roles)


def _view(entry: MessageEntry, claims: AuthClaims) -> FamilyMessageView:
    return FamilyMessageView(
        entry_id=entry.entry_id,
        at=entry.at,
        channel=entry.channel,
        source=entry.source,
        status=entry.status,
        summary=entry.summary,
        detail=entry.detail,
        recipient=entry.recipient,
        author_user_id=entry.author_user_id,
        failed_reason=entry.failed_reason,
        log_id=entry.log_id,
        can_complete=_can_complete(entry, claims),
    )


def _log_view(row: FamilyContactLog, claims: AuthClaims) -> FamilyMessageView:
    return _view(contact_log_entry(row), claims)


@router.get("/families/{parent_id}/messages", response_model=FamilyMessagesView)
async def family_messages(
    parent_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    messages: Any = Depends(get_family_messages),
) -> FamilyMessagesView:
    """The family's Messages thread, newest first (at most 200 rows)."""
    page = await messages.thread.execute(academy_id=_academy_id(claims), parent_id=parent_id)
    return FamilyMessagesView(
        family_id=page.family_id,
        entries=[_view(e, claims) for e in page.entries],
        warnings=page.warnings,
    )


@router.post(
    "/families/{parent_id}/messages/log",
    response_model=FamilyMessageView,
    status_code=status.HTTP_201_CREATED,
)
async def log_family_contact(
    parent_id: str,
    body: LogContactBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    messages: Any = Depends(get_family_messages),
) -> FamilyMessageView:
    """Log a contact made outside the app. Sends nothing."""
    row = await messages.log.execute(
        academy_id=_academy_id(claims),
        parent_id=parent_id,
        channel=body.channel,
        status=body.status,
        note=body.note,
        actor=_actor(claims),
    )
    return _log_view(row, claims)


@router.patch("/families/{parent_id}/messages/log/{log_id}", response_model=FamilyMessageView)
async def complete_family_contact_log(
    parent_id: str,
    log_id: str,
    body: CompleteContactLogBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    messages: Any = Depends(get_family_messages),
) -> FamilyMessageView:
    """ "Yes, I sent it": a ``not_logged`` handoff becomes ``logged``."""
    row = await messages.complete.execute(
        academy_id=_academy_id(claims),
        parent_id=parent_id,
        log_id=log_id,
        note=body.note,
        actor=_actor(claims),
    )
    return _log_view(row, claims)
