"""Get academy profile settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from backend.v2.contexts.identity.domain.legal_links import https_url_or_none
from backend.v2.contexts.identity.domain.public_page import PUBLIC_PAGE_FIELD, PublicPageSettings
from backend.v2.shared.comms.phone_country import DEFAULT_CALLING_CODE, calling_code_for_country
from backend.v2.shared.comms.sender_identity import resolve_reply_to

#: Every academy that predates the `sport` field (every academy today,
#: including BLNO) reads as badminton. No migration: this is a read-time
#: default, not a stored value, so existing docs are untouched.
DEFAULT_ACADEMY_SPORT = "badminton"


class AcademyRepo(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...
    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


#: Class defaults (Settings overhaul Phase 3 PR 9, Academy profile / Class
#: defaults card). These are filled at READ time, never migrated: an academy
#: doc with no ``default_class_size`` stored reads as 10 today and forever,
#: so BLNO (and every other pre-existing academy) sees exactly what the
#: create-class form already defaulted to before this card existed.
DEFAULT_CLASS_SIZE = 10
DEFAULT_CLASS_LENGTH_MINUTES = 45


@dataclass(frozen=True)
class GetAcademyOutput:
    academy_id: str
    display_name: str
    timezone: str | None
    contact_email: str | None = None
    contact_phone: str | None = None
    hours_text: str | None = None
    address: str | None = None
    logo_url: str | None = None
    brand_color: str | None = None
    currency: str = "USD"
    #: Outbound email display name / reply-to (L9a). ``None`` = not set.
    email_sender_name: str | None = None
    email_reply_to: str | None = None
    #: The reply-to a send actually uses (explicit, else support email) and
    #: where it came from: "reply_to" | "support_email" | None (#1014).
    effective_reply_to: str | None = None
    effective_reply_to_source: str | None = None
    #: Settings overhaul Phase 4 PR 13. ``privacy_notice_url`` is read from
    #: ``public_page.privacy_notice_url`` (the one stored copy).
    support_email: str | None = None
    terms_url: str | None = None
    refund_policy_url: str | None = None
    privacy_notice_url: str | None = None
    #: Calling code for bare national phone numbers (WhatsApp links). Read
    #: only, derived from ``country`` at read time; unset -> "1".
    phone_country_code: str = DEFAULT_CALLING_CODE
    #: Platform-set at bootstrap; read-only in the admin academy view.
    sport: str = DEFAULT_ACADEMY_SPORT
    #: Class defaults (Settings overhaul Phase 3 PR 9). Filled at read time;
    #: the create-class form and the class welcome email fallback both read
    #: these off the academy view.
    default_class_size: int = DEFAULT_CLASS_SIZE
    default_class_length_minutes: int = DEFAULT_CLASS_LENGTH_MINUTES
    default_venue_address: str | None = None
    default_parking_note: str | None = None
    default_what_to_bring: str | None = None
    default_arrival_minutes_before: int | None = None


def legal_and_support_fields(doc: dict[str, Any]) -> dict[str, Any]:
    """The Phase 4 PR 13 academy fields, read-time only (nothing backfilled)."""
    support = doc.get("support_email")
    return {
        "support_email": support.strip() or None if isinstance(support, str) else None,
        "terms_url": https_url_or_none(doc.get("terms_url")),
        "refund_policy_url": https_url_or_none(doc.get("refund_policy_url")),
        "privacy_notice_url": PublicPageSettings.from_stored(
            doc.get(PUBLIC_PAGE_FIELD)
        ).privacy_notice_url,
    }


class GetAcademyUseCase:
    def __init__(self, academy_repo: AcademyRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str) -> GetAcademyOutput:
        doc = await self._repo.find_by_id(academy_id)
        if not doc:
            doc = await self._repo.upsert_defaults(academy_id)
        effective_reply_to, effective_reply_to_source = resolve_reply_to(doc)
        return GetAcademyOutput(
            academy_id=str(doc.get("academy_id") or doc.get("_id", academy_id)),
            display_name=doc.get("display_name") or academy_id,
            # None, never "UTC": callers must be able to tell "unset" from
            # "genuinely UTC" so they can prompt instead of silently shifting.
            timezone=(str(doc.get("timezone")).strip() or None) if doc.get("timezone") else None,
            contact_email=doc.get("contact_email"),
            contact_phone=doc.get("contact_phone"),
            hours_text=doc.get("hours_text"),
            address=doc.get("address"),
            logo_url=doc.get("logo_url"),
            brand_color=doc.get("brand_color"),
            currency=str(doc.get("currency") or "USD"),
            email_sender_name=doc.get("email_sender_name") or None,
            email_reply_to=doc.get("email_reply_to") or None,
            effective_reply_to=effective_reply_to,
            effective_reply_to_source=effective_reply_to_source,
            **legal_and_support_fields(doc),
            phone_country_code=calling_code_for_country(doc.get("country")),
            sport=str(doc.get("sport") or DEFAULT_ACADEMY_SPORT),
            default_class_size=(
                int(doc["default_class_size"])
                if doc.get("default_class_size") is not None
                else DEFAULT_CLASS_SIZE
            ),
            default_class_length_minutes=(
                int(doc["default_class_length_minutes"])
                if doc.get("default_class_length_minutes") is not None
                else DEFAULT_CLASS_LENGTH_MINUTES
            ),
            default_venue_address=doc.get("default_venue_address") or None,
            default_parking_note=doc.get("default_parking_note") or None,
            default_what_to_bring=doc.get("default_what_to_bring") or None,
            default_arrival_minutes_before=(
                int(doc["default_arrival_minutes_before"])
                if doc.get("default_arrival_minutes_before") is not None
                else None
            ),
        )
