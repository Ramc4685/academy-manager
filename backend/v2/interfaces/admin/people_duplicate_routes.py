"""Admin BFF: the People CRM duplicate warning (spec §4 "Real forms", Phase 4c).

``POST /admin/people/duplicate-check`` with ``{email?, phone?, name?}``
answers ``{matches: [...]}``, at most five, each
``{kind, display_name, email_masked, phone_masked, link, matched_on}``.

* ``require_persona("admin")``: a coach or parent gets the same 404 every
  wrong-persona call gets (docs/security-matrix.md).
* Tenant-scoped: the academy is the request's tenant; the body carries none
  (extra fields are refused), and every lookup stays inside it.
* A warning, never a gate: the forms call this on blur and let staff
  continue whatever it answers. Empty or unusable input answers no matches.
* Contact details come back masked (``jo***@example.test``, ``•••-2030``);
  the link opens the record, where the full details already live.
* Rate-limited per client by ``InMemoryRateLimitMiddleware``
  (``_PATH_LIMIT_OVERRIDES``).

Services are composed on first use and kept on
``app.state.admin_people_duplicates`` (``composition/people_duplicates.py``).
This router is included by ``family_crm_routes.router``.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.v2.composition.people_duplicates import compose_admin_people_duplicates
from backend.v2.contexts.crm.application.use_cases.find_possible_duplicates import (
    DuplicateCheckQuery,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id

router = APIRouter(tags=["admin.people"])

#: Raw caps, a little above the stored caps (email 254, phone 40, name 120).
_EMAIL_CAP = 320
_PHONE_CAP = 64
_NAME_CAP = 240


def get_admin_people_duplicates(request: Request) -> Any:
    state = request.app.state
    services = getattr(state, "admin_people_duplicates", None)
    if services is not None:
        return services
    db = getattr(state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="duplicate check is not configured")
    index = getattr(getattr(state, "admin_family_index", None), "index", None)
    services = compose_admin_people_duplicates(db, cached_index=index)
    state.admin_people_duplicates = services
    return services


def _academy_id(claims: AuthClaims) -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return claims.academy_id


class DuplicateCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(default=None, max_length=_EMAIL_CAP)
    phone: str | None = Field(default=None, max_length=_PHONE_CAP)
    name: str | None = Field(default=None, max_length=_NAME_CAP)


class DuplicateMatchView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["family", "family_contact", "user", "inquiry"]
    display_name: str
    email_masked: str | None = None
    phone_masked: str | None = None
    link: str | None = None
    matched_on: list[Literal["email", "phone", "name"]]


class DuplicateCheckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matches: list[DuplicateMatchView]


@router.post("/people/duplicate-check", response_model=DuplicateCheckResponse)
async def check_possible_duplicates(
    body: DuplicateCheckRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_people_duplicates),
) -> DuplicateCheckResponse:
    matches = await services.find.execute(
        _academy_id(claims),
        DuplicateCheckQuery(email=body.email, phone=body.phone, name=body.name),
    )
    return DuplicateCheckResponse(
        matches=[
            DuplicateMatchView(
                kind=match.kind,
                display_name=match.display_name,
                email_masked=match.email_masked,
                phone_masked=match.phone_masked,
                link=match.link,
                matched_on=list(match.matched_on),
            )
            for match in matches
        ]
    )
