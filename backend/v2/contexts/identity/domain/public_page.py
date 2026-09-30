"""Academy-level public page settings (public tenant page, Lane B1).

Stored as one subdocument, ``academies.public_page``. Nothing is backfilled:
an academy with no ``public_page`` key (every academy today) reads as the
defaults below, and a partial subdocument keeps the defaults for the keys it
does not carry. Reads therefore never depend on ``upsert_defaults``, whose
``$setOnInsert`` only reaches brand-new academies.

Defaults (owner decisions, brief section 0): page unpublished, price and
availability bands shown, prices per month, trials open, no privacy link.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal

from pydantic import (
    BaseModel,
    Field,
    StrictBool,
    StringConstraints,
    ValidationError,
    field_validator,
)

from backend.v2.shared.security.external_url import InvalidExternalUrl, validate_external_url

PricePeriodDefault = Literal["month", "class", "term"]
#: Look of the public page. ``floodlit`` is the original look (today's page).
PublicPageTheme = Literal["floodlit", "daylight", "showcase"]

#: At or below this many seats left a class shows "only N seats left". Equal
#: to the enrollment catalog's ``FEW_SEATS_THRESHOLD`` (pinned by a test), so
#: an academy that never touches the setting reads exactly as before.
DEFAULT_SEATS_LEFT_THRESHOLD: Final = 3
MAX_SEATS_LEFT_THRESHOLD: Final = 20

#: The subdocument key on the academy record.
PUBLIC_PAGE_FIELD: Final = "public_page"


#: Landing-page content limits (Settings overhaul Phase 6, content lane).
MAX_ABOUT_CHARS: Final = 1200
MAX_HIGHLIGHTS: Final = 6
MAX_HIGHLIGHT_CHARS: Final = 60
MAX_GALLERY_PHOTOS: Final = 12
MAX_CAPTION_CHARS: Final = 120
MAX_COACH_BIO_CHARS: Final = 280
MAX_FAQS: Final = 12
MAX_FAQ_QUESTION_CHARS: Final = 160
MAX_FAQ_ANSWER_CHARS: Final = 800
_MAX_URL_CHARS: Final = 2048


def _photo_url(value: object, *, label: str) -> str | None:
    """A photo rendered as an ``img src`` on a public page: http(s) only."""
    if value is None:
        return None
    try:
        checked = validate_external_url(str(value), field_label=label)
    except InvalidExternalUrl as exc:
        raise ValueError(exc.message) from exc
    if checked is not None and len(checked) > _MAX_URL_CHARS:
        raise ValueError(f"The {label} is too long.")
    return checked


class GalleryPhoto(BaseModel):
    """One gallery photo. The consent fields are internal: they are stamped by
    the server from the caller and never leave it (public DTO: url + caption)."""

    model_config = {"frozen": True, "extra": "ignore"}

    url: str
    caption: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=MAX_CAPTION_CHARS)
    ] = ""
    #: Parents or guardians of anyone shown agreed to publication. Required.
    consent_confirmed: Literal[True]
    consent_confirmed_by: str
    consent_confirmed_at: datetime

    @field_validator("consent_confirmed_at", mode="after")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        # Mongo hands datetimes back naive (UTC); keep them comparable.
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    @field_validator("url", mode="before")
    @classmethod
    def _http_url(cls, value: object) -> str:
        checked = _photo_url(value, label="photo link")
        if checked is None:
            raise ValueError("A gallery photo needs a link.")
        return checked


class CoachProfile(BaseModel):
    model_config = {"frozen": True, "extra": "ignore"}

    coach_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    photo_url: str | None = None
    bio: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=MAX_COACH_BIO_CHARS)
    ] = ""
    shown: StrictBool = True

    @field_validator("photo_url", mode="before")
    @classmethod
    def _http_url(cls, value: object) -> str | None:
        return _photo_url(value, label="coach photo link")


class Faq(BaseModel):
    model_config = {"frozen": True, "extra": "ignore"}

    question: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_FAQ_QUESTION_CHARS),
    ]
    answer: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_FAQ_ANSWER_CHARS),
    ]


class PublicPageSettings(BaseModel):
    model_config = {"frozen": True, "extra": "ignore"}

    published: bool = False
    show_price: bool = True
    show_availability: bool = True
    price_period_default: PricePeriodDefault = "month"
    trials_open: bool = True
    privacy_notice_url: str | None = None
    theme: PublicPageTheme = "floodlit"
    #: 0 never shows "only N seats left"; 1..20 shows it at or below N.
    seats_left_threshold: int = Field(
        default=DEFAULT_SEATS_LEFT_THRESHOLD, ge=0, le=MAX_SEATS_LEFT_THRESHOLD, strict=True
    )
    # Landing-page content. Every default is today's page: no photo, no about
    # text, no gallery, and empty ``faqs`` means "use the built-in questions".
    hero_photo_url: str | None = None
    about_text: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=MAX_ABOUT_CHARS)
    ] = ""
    highlights: list[
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_HIGHLIGHT_CHARS),
        ]
    ] = Field(default_factory=list, max_length=MAX_HIGHLIGHTS)
    gallery: list[GalleryPhoto] = Field(default_factory=list, max_length=MAX_GALLERY_PHOTOS)
    coach_profiles: list[CoachProfile] = Field(default_factory=list, max_length=50)
    faqs: list[Faq] = Field(default_factory=list, max_length=MAX_FAQS)

    @field_validator("hero_photo_url", mode="before")
    @classmethod
    def _hero_http_url(cls, value: object) -> str | None:
        return _photo_url(value, label="hero photo link")

    @field_validator("privacy_notice_url", mode="before")
    @classmethod
    def _http_link_only(cls, value: object) -> str | None:
        # Rendered as an href on a public page: http(s) only, never
        # javascript: or data:. Blank clears it.
        if value is None:
            return None
        try:
            return validate_external_url(str(value), field_label="privacy notice link")
        except InvalidExternalUrl as exc:
            raise ValueError(exc.message) from exc

    @classmethod
    def from_stored(cls, raw: object) -> PublicPageSettings:
        """Defaults merged under whatever the academy record carries.

        Tolerant by design: a stored key that no longer validates (a hand
        edit, a retired enum value) falls back to its default instead of
        failing the whole read, so one bad key cannot take the public page
        or the admin settings screen down.
        """
        if not isinstance(raw, Mapping):
            return cls()
        known = {k: raw[k] for k in cls.model_fields if k in raw}
        try:
            return cls(**known)
        except ValidationError:
            kept: dict[str, Any] = {}
            for key, value in known.items():
                try:
                    cls(**{key: value})
                except ValidationError:
                    continue
                kept[key] = value
            return cls(**kept)
