"""Admin BFF: family contacts and family details (People CRM spec §4, Phase 4b).

* ``GET/POST /admin/families/{parent_id}/contacts``
* ``PATCH/DELETE /admin/families/{parent_id}/contacts/{contact_id}``
* ``GET/PATCH /admin/families/{parent_id}/details``

Every route is ``require_persona("admin")``: a coach or parent gets the same
404 every wrong-persona call gets (docs/security-matrix.md). The academy is
the request's tenant; no body carries one (extra fields are refused).
``parent_id`` must be a family of that academy (404 otherwise), resolved to
its canonical id.

A contact's ``gets_notices`` adds their email to the family's notice audience
(``MongoAudienceResolver``); ``gets_invoices`` sends them a copy of each
invoice email (``composition/invoice_contact_copies.py``), never the pay
link. Both default to off.

This router is included by ``family_crm_routes.router``. Services are
composed on first use and kept on ``app.state.admin_family_contacts``
(``composition/family_contacts.py``). Domain errors (404, 409 duplicate
email, 422 validation with ``details.field``) are mapped by the registered
handler.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.v2.composition.family_contacts import compose_admin_family_contacts
from backend.v2.contexts.crm.application.use_cases.family_contacts import (
    MAX_ADDRESS_LEN,
    MAX_CONTACT_NAME_LEN,
    MAX_EMAIL_LEN,
    MAX_HEARD_ABOUT_US_LEN,
    MAX_PHONE_LEN,
    MAX_TAG_LEN,
    MAX_TAGS,
    ContactDraft,
    FamilyContact,
    FamilyDetails,
    contact_changes,
    details_changes,
)
from backend.v2.contexts.crm.application.use_cases.family_notes import Actor
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id

router = APIRouter(tags=["admin.families"])

# Raw caps sit above the domain caps so the domain's clearer, field-level
# message wins for "just over"; anything far over is refused by pydantic.
_NAME_CAP = MAX_CONTACT_NAME_LEN * 2
_EMAIL_CAP = MAX_EMAIL_LEN * 2
_PHONE_CAP = MAX_PHONE_LEN * 2
_ADDRESS_CAP = MAX_ADDRESS_LEN * 2
_HEARD_CAP = MAX_HEARD_ABOUT_US_LEN * 2
_TAG_CAP = MAX_TAG_LEN * 2
_TAGS_CAP = MAX_TAGS * 2

Relationship = Literal["parent", "guardian", "grandparent", "caregiver", "other"]
Channel = Literal["email", "phone", "sms", "whatsapp"]


def get_admin_family_contacts(request: Request) -> Any:
    state = request.app.state
    services = getattr(state, "admin_family_contacts", None)
    if services is not None:
        return services
    db = getattr(state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="family contacts are not configured")
    index = getattr(getattr(state, "admin_family_index", None), "index", None)
    services = compose_admin_family_contacts(db, cached_index=index)
    state.admin_family_contacts = services
    return services


def _academy_id(claims: AuthClaims) -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return claims.academy_id


def _actor(claims: AuthClaims) -> Actor:
    return Actor(user_id=claims.user_id, roles=tuple(claims.roles))


# ------------------------------------------------------------------ views


class FamilyContactView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_id: str
    parent_id: str
    name: str
    relationship: Relationship
    email: str | None
    phone: str | None
    gets_notices: bool
    gets_invoices: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class FamilyContactList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family_id: str
    contacts: list[FamilyContactView]


class FamilyDetailsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family_id: str
    address: str | None
    preferred_channel: Channel | None
    heard_about_us: str | None
    tags: list[str]
    updated_by: str | None
    updated_at: datetime | None


def _contact_view(row: FamilyContact) -> FamilyContactView:
    return FamilyContactView(
        contact_id=row.contact_id,
        parent_id=row.parent_id,
        name=row.name,
        relationship=row.relationship,
        email=row.email,
        phone=row.phone,
        gets_notices=row.gets_notices,
        gets_invoices=row.gets_invoices,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _details_view(row: FamilyDetails) -> FamilyDetailsView:
    return FamilyDetailsView(
        family_id=row.parent_id,
        address=row.address,
        preferred_channel=row.preferred_channel,
        heard_about_us=row.heard_about_us,
        tags=list(row.tags),
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


# ------------------------------------------------------------------ requests


class NewContact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=_NAME_CAP)
    relationship: str = Field(default="parent", max_length=40)
    email: str | None = Field(default=None, max_length=_EMAIL_CAP)
    phone: str | None = Field(default=None, max_length=_PHONE_CAP)
    # Off unless staff turn them on: never defaulted or inferred server-side.
    gets_notices: bool = False
    gets_invoices: bool = False


class ContactPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=_NAME_CAP)
    relationship: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=_EMAIL_CAP)
    phone: str | None = Field(default=None, max_length=_PHONE_CAP)
    gets_notices: bool | None = None
    gets_invoices: bool | None = None


class DetailsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str | None = Field(default=None, max_length=_ADDRESS_CAP)
    preferred_channel: str | None = Field(default=None, max_length=40)
    heard_about_us: str | None = Field(default=None, max_length=_HEARD_CAP)
    tags: list[str] | None = Field(default=None, max_length=_TAGS_CAP)


def _provided(payload: BaseModel) -> dict[str, object]:
    """Only the fields the caller sent (``null`` included, meaning clear)."""
    return {name: getattr(payload, name) for name in payload.model_fields_set}


# ------------------------------------------------------------------ contacts


@router.get("/families/{parent_id}/contacts", response_model=FamilyContactList)
async def list_family_contacts(
    parent_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_contacts),
) -> FamilyContactList:
    family_id, rows = await services.list.execute(
        academy_id=_academy_id(claims), parent_id=parent_id
    )
    return FamilyContactList(family_id=family_id, contacts=[_contact_view(r) for r in rows])


@router.post("/families/{parent_id}/contacts", response_model=FamilyContactView, status_code=201)
async def add_family_contact(
    parent_id: str,
    payload: NewContact,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_contacts),
) -> FamilyContactView:
    row = await services.add.execute(
        academy_id=_academy_id(claims),
        parent_id=parent_id,
        draft=ContactDraft(
            name=payload.name,
            relationship=payload.relationship,
            email=payload.email,
            phone=payload.phone,
            gets_notices=payload.gets_notices,
            gets_invoices=payload.gets_invoices,
        ),
        actor=_actor(claims),
    )
    return _contact_view(row)


@router.patch("/families/{parent_id}/contacts/{contact_id}", response_model=FamilyContactView)
async def update_family_contact(
    parent_id: str,
    contact_id: str,
    payload: ContactPatch,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_contacts),
) -> FamilyContactView:
    provided = _provided(payload)
    for switch in ("gets_notices", "gets_invoices", "name", "relationship"):
        if switch in provided and provided[switch] is None:
            raise HTTPException(status_code=422, detail=f"{switch} cannot be null")
    row = await services.update.execute(
        academy_id=_academy_id(claims),
        parent_id=parent_id,
        contact_id=contact_id,
        changes=contact_changes(provided),
        actor=_actor(claims),
    )
    return _contact_view(row)


@router.delete("/families/{parent_id}/contacts/{contact_id}", status_code=204)
async def delete_family_contact(
    parent_id: str,
    contact_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_contacts),
) -> Response:
    await services.delete.execute(
        academy_id=_academy_id(claims),
        parent_id=parent_id,
        contact_id=contact_id,
        actor=_actor(claims),
    )
    return Response(status_code=204)


# ------------------------------------------------------------------ details


@router.get("/families/{parent_id}/details", response_model=FamilyDetailsView)
async def get_family_details(
    parent_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_contacts),
) -> FamilyDetailsView:
    row = await services.get_details.execute(academy_id=_academy_id(claims), parent_id=parent_id)
    return _details_view(row)


@router.patch("/families/{parent_id}/details", response_model=FamilyDetailsView)
async def update_family_details(
    parent_id: str,
    payload: DetailsPatch,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_contacts),
) -> FamilyDetailsView:
    row = await services.update_details.execute(
        academy_id=_academy_id(claims),
        parent_id=parent_id,
        changes=details_changes(_provided(payload)),
        actor=_actor(claims),
    )
    return _details_view(row)
