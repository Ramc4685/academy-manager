"""Programs and per-class public-page fields (public tenant page, Lane B1).

A **program** groups existing classes (``sessions``) for the public page:
"Juniors, beginner, ages 6 to 9". It is tenant-scoped and owned by the
Enrollment context because Enrollment is the sole writer of ``sessions``
(data-ownership.md) and a class's program is a field on the session.

A class's **public profile** is the handful of fields the public page may
show about it. They live flat on the session document, are written only by
targeted ``$set``/``$unset`` (never through ``Session`` round-trips), and are
all optional so no data migration is needed:

* ``published`` absent means ``False``: every existing class stays private
  until an admin switches it on (owner decision, brief section 0).
* ``price_period`` absent means "use the academy default"
  (``public_page.price_period_default``, itself ``"month"`` by default), so
  the effective default is per month either way.
* ``coach_display`` absent means ``"full_name"`` (industry standard, brief
  section 0); ``"first_name"`` and ``"hidden"`` are the hide options.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal, get_args

from pydantic import BaseModel, Field, field_validator, model_validator

PricePeriod = Literal["month", "class", "term"]
CoachDisplay = Literal["full_name", "first_name", "hidden"]

PRICE_PERIODS: Final[tuple[str, ...]] = get_args(PricePeriod)
COACH_DISPLAY_OPTIONS: Final[tuple[str, ...]] = get_args(CoachDisplay)
DEFAULT_PRICE_PERIOD: Final[PricePeriod] = "month"
DEFAULT_COACH_DISPLAY: Final[CoachDisplay] = "full_name"

MAX_PROGRAM_NAME_LEN: Final = 80
MAX_PUBLIC_DESCRIPTION_LEN: Final = 500
MAX_LEVEL_LEN: Final = 40
MAX_AGE: Final = 99
MAX_SORT_ORDER: Final = 10_000


def _clean_optional_text(value: object) -> str | None:
    """Blank reads as unset: the UI clears a field by sending ``""``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class AgeBand(BaseModel):
    """Inclusive age span. ``max_age=None`` means "and up" (adult classes)."""

    model_config = {"frozen": True}

    min_age: int | None = Field(default=None, ge=0, le=MAX_AGE)
    max_age: int | None = Field(default=None, ge=0, le=MAX_AGE)

    @model_validator(mode="after")
    def _ordered(self) -> AgeBand:
        if self.min_age is None and self.max_age is None:
            raise ValueError("an age band needs a minimum or a maximum age")
        if self.min_age is not None and self.max_age is not None:
            if self.min_age > self.max_age:
                raise ValueError("min_age must not be above max_age")
        return self


class Program(BaseModel):
    """A public grouping of classes: name, level, ages, description, order."""

    model_config = {"frozen": True}

    program_id: str
    academy_id: str
    name: str = Field(min_length=1, max_length=MAX_PROGRAM_NAME_LEN)
    public_description: str | None = Field(default=None, max_length=MAX_PUBLIC_DESCRIPTION_LEN)
    level: str | None = Field(default=None, max_length=MAX_LEVEL_LEN)
    age_band: AgeBand | None = None
    sort_order: int = Field(default=0, ge=0, le=MAX_SORT_ORDER)
    #: Archived programs are hidden from the public page and the admin list
    #: (unless asked for); their classes keep the id and read as ungrouped.
    archived: bool = False
    created_at: datetime
    updated_at: datetime

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("public_description", "level", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> str | None:
        return _clean_optional_text(value)


class ClassPublicProfile(BaseModel):
    """The public-page fields of one class (a ``sessions`` row).

    Defaults are the answer for a legacy document that has never been
    touched: private, coach shown in full, price period from the academy.
    """

    model_config = {"frozen": True}

    session_id: str
    #: The class title and status, carried for the admin list only (the
    #: public read builds its own DTO and never copies these through).
    title: str | None = None
    status: str | None = None
    program_id: str | None = None
    published: bool = False
    #: None = follow the academy's ``public_page.price_period_default``.
    price_period: PricePeriod | None = None
    coach_display: CoachDisplay = DEFAULT_COACH_DISPLAY
    public_description: str | None = Field(default=None, max_length=MAX_PUBLIC_DESCRIPTION_LEN)
    level: str | None = Field(default=None, max_length=MAX_LEVEL_LEN)
    age_band: AgeBand | None = None

    @field_validator("public_description", "level", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> str | None:
        return _clean_optional_text(value)

    def effective_price_period(
        self, academy_default: PricePeriod = DEFAULT_PRICE_PERIOD
    ) -> PricePeriod:
        """The period shown next to this class's price on the public page."""
        return self.price_period or academy_default
