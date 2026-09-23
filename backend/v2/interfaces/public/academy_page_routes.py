"""``GET /api/v2/public/academy``: the academy's public page data (Lane B2).

Order of decisions, each before the next can run:

1. **Tenant from the host.** ``TenancyMiddleware`` resolved it from the
   request host and left it on ``request.state.resolved_academy_id``; this
   route takes no tenant, academy or slug input at all. No tenant for the
   host, or no academy record for it, is a plain 404 (identical body). In
   production ``single_academy`` mode the middleware resolves every host to
   ``PRIMARY_ACADEMY_ID``, so the live academy's page works on its own host
   with no tenancy-mode change.
2. **Published switch.** Off: ``state: "not_published"`` with the academy's
   name and branding only; no venue, classes, prices or page switches.
3. **Published:** profile, venue, page switches and the published programs
   and classes, allow-listed through ``dtos.py``.

Cacheable for 60 s per host (``Vary: Host``). Rate limited per client IP in
``shared/http/rate_limit.py``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from backend.v2.composition.public_page_read import PublicPageRead
from backend.v2.contexts.enrollment.application.use_cases.public_catalog import (
    PublicCatalog,
    PublicClassView,
)
from backend.v2.contexts.identity.application.public_academy_profile import (
    PublicAcademyProfile,
)
from backend.v2.interfaces.public.dtos import (
    PublicAcademyDto,
    PublicAcademyNotPublishedDto,
    PublicAcademyPageDto,
    PublicAgeBandDto,
    PublicBrandDto,
    PublicClassDto,
    PublicPageFlagsDto,
    PublicPriceDto,
    PublicProgramDto,
    PublicSeatsDto,
    PublicVenueDto,
)
from backend.v2.shared.tenancy.context import tenant_scope

router = APIRouter()

#: Path the rate limiter keys on (``shared/http/rate_limit.py``).
PUBLIC_ACADEMY_PATH = "/api/v2/public/academy"
CACHE_CONTROL = "public, max-age=60"
_NOT_FOUND_BODY = {"detail": "Not found"}


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content=_NOT_FOUND_BODY, headers={"Vary": "Host"})


@router.get(
    "/academy",
    response_model=PublicAcademyPageDto | PublicAcademyNotPublishedDto,
    responses={404: {"description": "No academy serves this host."}},
)
async def get_public_academy_page(request: Request, response: Response) -> Any:
    academy_id = getattr(request.state, "resolved_academy_id", None)
    if not academy_id:
        return _not_found()
    public_page: PublicPageRead = request.app.state.public_page
    with tenant_scope(str(academy_id)):
        profile = await public_page.get_academy_profile.execute(str(academy_id))
        if profile is None:
            return _not_found()
        response.headers["Cache-Control"] = CACHE_CONTROL
        response.headers["Vary"] = "Host"
        settings = profile.settings
        if not settings.published:
            return PublicAcademyNotPublishedDto(academy=_brand(profile))
        catalog = await public_page.list_catalog.execute(
            str(academy_id),
            price_period_default=settings.price_period_default,
            show_price=settings.show_price,
            show_availability=settings.show_availability,
        )
    return _page(profile, catalog)


def _brand(profile: PublicAcademyProfile) -> PublicBrandDto:
    return PublicBrandDto(
        name=profile.name,
        logo_url=profile.logo_url,
        brand_color=profile.brand_color,
        brand_fill=profile.brand_fill,
        brand_on_color=profile.brand_on_color,
    )


def _page(profile: PublicAcademyProfile, catalog: PublicCatalog) -> PublicAcademyPageDto:
    settings = profile.settings
    return PublicAcademyPageDto(
        academy=PublicAcademyDto(
            **_brand(profile).model_dump(),
            venue=PublicVenueDto(address=profile.address, hours_text=profile.hours_text),
            timezone=profile.timezone,
            currency=profile.currency,
        ),
        page=PublicPageFlagsDto(
            trials_open=settings.trials_open,
            show_price=settings.show_price,
            show_availability=settings.show_availability,
            price_period_default=settings.price_period_default,
            privacy_notice_url=settings.privacy_notice_url,
        ),
        programs=[
            PublicProgramDto(
                public_id=program.public_id,
                name=program.name,
                description=program.description,
                level=program.level,
                age_band=_age_band(program.age_band),
                classes=[_class(view) for view in program.classes],
            )
            for program in catalog.programs
        ],
        ungrouped_classes=[_class(view) for view in catalog.ungrouped_classes],
    )


def _age_band(band: Any) -> PublicAgeBandDto | None:
    if band is None:
        return None
    return PublicAgeBandDto(min_age=band.min_age, max_age=band.max_age)


def _class(view: PublicClassView) -> PublicClassDto:
    return PublicClassDto(
        public_id=view.public_id,
        title=view.title,
        description=view.description,
        level=view.level,
        age_band=_age_band(view.age_band),
        days_of_week=list(view.days_of_week),
        start_time=view.start_time,
        end_time=view.end_time,
        timezone=view.timezone,
        starts_on=view.starts_on,
        location=view.location,
        venue_address=view.venue_address,
        coach_name=view.coach_name,
        price=(
            PublicPriceDto(amount_cents=view.price.amount_cents, period=view.price.period)
            if view.price
            else None
        ),
        seats=(
            PublicSeatsDto(band=view.seats.band, seats_left=view.seats.seats_left)
            if view.seats
            else None
        ),
    )
