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
from typing import Any, Final, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

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
