"""Allow-listed response shapes for the anonymous public page.

Every field a stranger can receive is declared here and nowhere else. No
email, phone, internal id (academy, session, program, coach, student,
parent, user), notes, exact capacity or enrolled count may ever be added:
``tests/structural/test_public_page_dto_no_leak.py`` walks these models
recursively and fails on such a field name.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel


class PublicAgeBandDto(BaseModel):
    min_age: int | None = None
    max_age: int | None = None


class PublicPriceDto(BaseModel):
    amount_cents: int
    #: "month" | "class" | "term": shown next to every price.
    period: str


class PublicSeatsDto(BaseModel):
    #: "open" | "few" | "waitlist" (full, join waitlist). A band, never a count.
    band: str
    #: Only for "few" (3 or fewer left); null otherwise.
    seats_left: int | None = None


class PublicClassDto(BaseModel):
    #: Opaque id; not the internal class id and not reversible to it.
    public_id: str
    title: str
    description: str | None = None
    level: str | None = None
    age_band: PublicAgeBandDto | None = None
    days_of_week: list[str] = []
    start_time: str | None = None
    end_time: str | None = None
    timezone: str | None = None
    #: Date of a one-off class; null for a weekly class.
    starts_on: date | None = None
    location: str | None = None
    venue_address: str | None = None
    coach_name: str | None = None
    #: Null when the academy hides prices or the class has no price.
    price: PublicPriceDto | None = None
    #: Null when the academy hides availability.
    seats: PublicSeatsDto | None = None


class PublicProgramDto(BaseModel):
    public_id: str
    name: str
    description: str | None = None
    level: str | None = None
    age_band: PublicAgeBandDto | None = None
    classes: list[PublicClassDto]


class PublicBrandDto(BaseModel):
    name: str
    logo_url: str | None = None
    #: The academy's own colour, or null when it set none.
    brand_color: str | None = None
    #: Paint buttons and fills with this (the brand colour, nudged only when
    #: needed so ``brand_on_color`` on it clears WCAG AA 4.5:1).
    brand_fill: str
    #: Text colour on ``brand_fill``.
    brand_on_color: str


class PublicVenueDto(BaseModel):
    address: str | None = None
    hours_text: str | None = None


class PublicAcademyDto(PublicBrandDto):
    venue: PublicVenueDto
    timezone: str | None = None
    currency: str


class PublicPageFlagsDto(BaseModel):
    trials_open: bool
    show_price: bool
    show_availability: bool
    price_period_default: str
    privacy_notice_url: str | None = None


class PublicAcademyPageDto(BaseModel):
    state: Literal["published"] = "published"
    academy: PublicAcademyDto
    page: PublicPageFlagsDto
    programs: list[PublicProgramDto]
    #: Published classes that belong to no (active) program.
    ungrouped_classes: list[PublicClassDto]


class PublicAcademyNotPublishedDto(BaseModel):
    """The page exists but the owner has not switched it on: branding only."""

    state: Literal["not_published"] = "not_published"
    academy: PublicBrandDto


class PublicTrialRequestAckDto(BaseModel):
    """The ONE answer to an accepted trial request (Lane B4).

    Identical for a new inquiry, a repeat of one already on file and a
    honeypot hit, so the form cannot be used to learn who has already asked
    (brief section 5). Carries nothing about the stored row.
    """

    state: Literal["received"] = "received"


class PublicTrialFormRequest(BaseModel):
    """What the anonymous trial form may send (Lane B4). Request-only.

    Deliberately absent: any academy, tenant or slug (the host decides), the
    child's name (brief section 5: not collected), ``created_by`` and any
    referrer. Unknown keys are ignored, never stored. Loose types on purpose:
    the route validates and answers with per-field messages, never with the
    submitted values echoed back.
    """

    model_config = {"extra": "ignore"}

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    #: Free text as typed ("9", "5 to 8"); a number is accepted too.
    player_age: str | int | None = None
    #: A class ``public_id`` from the page, or blank for "not sure".
    class_id: str | None = None
    message: str | None = None
    #: Must be true: consent to be contacted about THIS request.
    contact_about_request: bool = False
    #: News and offers; off unless ticked.
    marketing_opt_in: bool = False
    #: Honeypot. Hidden from people and assistive technology; a bot fills it.
    website: str | None = None


#: Every model the public persona can serialise, for the no-leak test.
PUBLIC_RESPONSE_MODELS: tuple[type[BaseModel], ...] = (
    PublicAcademyPageDto,
    PublicAcademyNotPublishedDto,
    PublicTrialRequestAckDto,
)

#: Every request body the public persona accepts, for the no-leak test's
#: request allow-list (these fields are what a stranger may submit).
PUBLIC_REQUEST_MODELS: tuple[type[BaseModel], ...] = (PublicTrialFormRequest,)
