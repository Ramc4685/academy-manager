"""Admin BFF: programs and per-class public-page fields (public tenant page, Lane B1).

* ``GET  /admin/programs`` (``?include_archived=true`` for archived too)
* ``POST /admin/programs``
* ``PATCH /admin/programs/{program_id}``
* ``POST /admin/programs/{program_id}/archive``
* ``GET  /admin/class-public-profiles``: every class's public fields
* ``PUT  /admin/sessions/{session_id}/program``: assign or clear (``null``)
* ``PATCH /admin/sessions/{session_id}/public-fields``: publish switch,
  price period, coach display, description, level, age band
* ``GET  /admin/academy/public-page``: the academy's page settings,
  defaults merged in (Lane B5)
* ``PATCH /admin/academy/public-page``: partial update; only sent keys
  change (Lane B5)

All ``require_persona("admin")``: none moves money. Tenant from the request's
tenant scope, never from the body; another academy's program or class is a
404. Services at ``app.state.admin_public_page``
(``composition/public_page_admin.py``). The academy-level settings routes
use the caller's ``academy_id`` claim, exactly like the other academy
settings (``academy_routes.py``); an unknown key, a coerced boolean or a
non-http(s) privacy link is a 422 ``Identity.InvalidPublicPageSettings``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from backend.v2.contexts.enrollment.application.use_cases.programs import (
    AgeBand,
    ArchiveProgram,
    AssignClassToProgram,
    ClassPublicProfile,
    CoachDisplay,
    CreateProgram,
    CreateProgramCommand,
    ListClassPublicProfiles,
    ListPrograms,
    PricePeriod,
    Program,
    SetClassPublicFields,
    UpdateProgram,
)
from backend.v2.contexts.identity.application.public_page_settings import (
    GetPublicPageAddress,
    GetPublicPageSettings,
    PublicPageSettings,
    UpdatePublicPageSettings,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona


class AdminPublicPageServices(Protocol):
    create_program: CreateProgram
    update_program: UpdateProgram
    archive_program: ArchiveProgram
    list_programs: ListPrograms
    assign_class_to_program: AssignClassToProgram
    set_class_public_fields: SetClassPublicFields
    list_class_public_profiles: ListClassPublicProfiles
    get_public_page_settings: GetPublicPageSettings
    update_public_page_settings: UpdatePublicPageSettings
    get_public_page_address: GetPublicPageAddress


def get_admin_public_page(request: Request) -> AdminPublicPageServices:
    services: AdminPublicPageServices = request.app.state.admin_public_page
    return services


# --- views -----------------------------------------------------------------


class AgeBandBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_age: int | None = Field(default=None, ge=0, le=99)
    max_age: int | None = Field(default=None, ge=0, le=99)


class ProgramView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_id: str
    name: str
    public_description: str | None = None
    level: str | None = None
    age_band: AgeBandBody | None = None
    sort_order: int
    archived: bool
    created_at: datetime
    updated_at: datetime


class ProgramList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    programs: list[ProgramView]


class CreateProgramRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    public_description: str | None = Field(default=None, max_length=500)
    level: str | None = Field(default=None, max_length=40)
    age_band: AgeBandBody | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)


class UpdateProgramRequest(BaseModel):
    """Partial: only the keys sent are changed. ``null`` clears an optional
    text field or the age band."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    public_description: str | None = Field(default=None, max_length=500)
    level: str | None = Field(default=None, max_length=40)
    age_band: AgeBandBody | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)
    archived: StrictBool | None = None


class AssignClassProgramRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Required key; ``null`` takes the class out of its program.
    program_id: str | None = Field(max_length=64)


class ClassPublicFieldsRequest(BaseModel):
    """Partial: only the keys sent are changed. ``null`` resets
    ``price_period`` to the academy default and clears the text fields and
    the age band."""

    model_config = ConfigDict(extra="forbid")

    published: StrictBool | None = None
    price_period: PricePeriod | None = None
    coach_display: CoachDisplay | None = None
    public_description: str | None = Field(default=None, max_length=500)
    level: str | None = Field(default=None, max_length=40)
    age_band: AgeBandBody | None = None


class ClassPublicProfileView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    #: Admin label only (the class title); never a public-page field.
    title: str | None = None
    #: ``scheduled`` / ``cancelled`` / ``completed``; the public page never
    #: lists cancelled or completed classes whatever their switch says.
    status: str | None = None
    program_id: str | None = None
    published: bool
    #: ``null`` = the academy's default price period.
    price_period: PricePeriod | None = None
    coach_display: CoachDisplay
    public_description: str | None = None
    level: str | None = None
    age_band: AgeBandBody | None = None


class ClassPublicProfileList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classes: list[ClassPublicProfileView]


def _age_band_view(band: AgeBand | None) -> AgeBandBody | None:
    return None if band is None else AgeBandBody(min_age=band.min_age, max_age=band.max_age)


def _program_view(program: Program) -> ProgramView:
    return ProgramView(
        program_id=program.program_id,
        name=program.name,
        public_description=program.public_description,
        level=program.level,
        age_band=_age_band_view(program.age_band),
        sort_order=program.sort_order,
        archived=program.archived,
        created_at=program.created_at,
        updated_at=program.updated_at,
    )


def _profile_view(profile: ClassPublicProfile) -> ClassPublicProfileView:
    return ClassPublicProfileView(
        session_id=profile.session_id,
        title=profile.title,
        status=profile.status,
        program_id=profile.program_id,
        published=profile.published,
        price_period=profile.price_period,
        coach_display=profile.coach_display,
        public_description=profile.public_description,
        level=profile.level,
        age_band=_age_band_view(profile.age_band),
    )


class PublicPageSettingsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    published: bool
    show_price: bool
    show_availability: bool
    price_period_default: PricePeriod
    trials_open: bool
    privacy_notice_url: str | None = None
    #: ``https://<host>/`` of the academy's own domain for the "View page"
    #: link; ``null`` when the academy has no domain on record. Read-only.
    public_url: str | None = None


class UpdatePublicPageSettingsRequest(BaseModel):
    """Partial: only the keys sent are changed. ``null`` (or blank) clears
    the privacy notice link. Switches must be real booleans."""

    model_config = ConfigDict(extra="forbid")

    published: StrictBool | None = None
    show_price: StrictBool | None = None
    show_availability: StrictBool | None = None
    price_period_default: PricePeriod | None = None
    trials_open: StrictBool | None = None
    privacy_notice_url: str | None = Field(default=None, max_length=2048)


def _settings_view(settings: PublicPageSettings, public_url: str | None) -> PublicPageSettingsView:
    return PublicPageSettingsView(**settings.model_dump(), public_url=public_url)


def _changes(body: BaseModel) -> dict[str, Any]:
    """The keys the caller actually sent, nested models as plain dicts."""
    return body.model_dump(exclude_unset=True)


# --- routes ----------------------------------------------------------------

router = APIRouter(tags=["admin.public-page"])


@router.get("/programs", response_model=ProgramList)
async def list_programs(
    include_archived: bool = Query(default=False),
    _claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminPublicPageServices = Depends(get_admin_public_page),
) -> ProgramList:
    rows = await services.list_programs.execute(include_archived=include_archived)
    return ProgramList(programs=[_program_view(row) for row in rows])


@router.post("/programs", response_model=ProgramView, status_code=status.HTTP_201_CREATED)
async def create_program(
    body: CreateProgramRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminPublicPageServices = Depends(get_admin_public_page),
) -> ProgramView:
    fields = body.model_dump()
    row = await services.create_program.execute(CreateProgramCommand(**fields))
    return _program_view(row)


@router.patch("/programs/{program_id}", response_model=ProgramView)
async def update_program(
    program_id: str,
    body: UpdateProgramRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminPublicPageServices = Depends(get_admin_public_page),
) -> ProgramView:
    row = await services.update_program.execute(program_id, _changes(body))
    return _program_view(row)


@router.post("/programs/{program_id}/archive", response_model=ProgramView)
async def archive_program(
    program_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminPublicPageServices = Depends(get_admin_public_page),
) -> ProgramView:
    row = await services.archive_program.execute(program_id)
    return _program_view(row)


@router.get("/class-public-profiles", response_model=ClassPublicProfileList)
async def list_class_public_profiles(
    _claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminPublicPageServices = Depends(get_admin_public_page),
) -> ClassPublicProfileList:
    rows = await services.list_class_public_profiles.execute()
    return ClassPublicProfileList(classes=[_profile_view(row) for row in rows])


@router.put("/sessions/{session_id}/program", response_model=ClassPublicProfileView)
async def assign_class_to_program(
    session_id: str,
    body: AssignClassProgramRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminPublicPageServices = Depends(get_admin_public_page),
) -> ClassPublicProfileView:
    row = await services.assign_class_to_program.execute(session_id, body.program_id)
    return _profile_view(row)


@router.patch("/sessions/{session_id}/public-fields", response_model=ClassPublicProfileView)
async def set_class_public_fields(
    session_id: str,
    body: ClassPublicFieldsRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminPublicPageServices = Depends(get_admin_public_page),
) -> ClassPublicProfileView:
    row = await services.set_class_public_fields.execute(session_id, _changes(body))
    return _profile_view(row)


@router.get("/academy/public-page", response_model=PublicPageSettingsView)
async def get_public_page_settings(
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminPublicPageServices = Depends(get_admin_public_page),
) -> PublicPageSettingsView:
    settings = await services.get_public_page_settings.execute(claims.academy_id)
    address = await services.get_public_page_address.execute(claims.academy_id)
    return _settings_view(settings, address)


@router.patch("/academy/public-page", response_model=PublicPageSettingsView)
async def update_public_page_settings(
    body: UpdatePublicPageSettingsRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminPublicPageServices = Depends(get_admin_public_page),
) -> PublicPageSettingsView:
    # ``null`` only clears the privacy link: a switch or the price period sent
    # as null fails the use case's own validation (422), never "reset".
    settings = await services.update_public_page_settings.execute(claims.academy_id, _changes(body))
    address = await services.get_public_page_address.execute(claims.academy_id)
    return _settings_view(settings, address)
