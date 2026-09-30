"""Update academy profile settings."""

from __future__ import annotations

from typing import Any, Protocol

# Re-exported so the admin views validate legal links through the
# application layer (interfaces never import a context domain directly).
from backend.v2.contexts.identity.domain.legal_links import (
    validate_https_url as validate_https_url,
)
from backend.v2.contexts.identity.domain.public_page import PUBLIC_PAGE_FIELD
from backend.v2.shared.comms.phone_country import calling_code_for_country
from backend.v2.shared.comms.sender_identity import resolve_reply_to

from .get_academy_use_case import (
    DEFAULT_CLASS_LENGTH_MINUTES,
    DEFAULT_CLASS_SIZE,
    GetAcademyOutput,
    legal_and_support_fields,
)


class AcademyWriteRepo(Protocol):
    async def update_by_id(
        self, academy_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None: ...
    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


class UpdateAcademyUseCase:
    def __init__(self, academy_repo: AcademyWriteRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str, fields: dict[str, Any]) -> GetAcademyOutput:
        fields = dict(fields)
        if "privacy_notice_url" in fields:
            # The privacy link has ONE stored copy, the public page setting
            # the CRM consent stamp and the trial form read. Academy profile
            # writes that same key; there is no ``academies.privacy_notice_url``.
            fields[f"{PUBLIC_PAGE_FIELD}.privacy_notice_url"] = (
                fields.pop("privacy_notice_url") or None
            )
        if not fields:
            # No changes — ensure doc exists and return current state.
            doc = await self._repo.upsert_defaults(academy_id)
        else:
            doc = await self._repo.update_by_id(academy_id, fields)
        if not doc:
            raise LookupError(f"academy {academy_id} not found")
        effective_reply_to, effective_reply_to_source = resolve_reply_to(doc)
        return GetAcademyOutput(
            academy_id=str(doc.get("academy_id") or doc.get("_id", academy_id)),
            display_name=doc.get("display_name") or academy_id,
            timezone=doc.get("timezone") or "UTC",
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
            default_coach_contact_policy=doc.get("default_coach_contact_policy") or None,
            default_arrival_minutes_before=(
                int(doc["default_arrival_minutes_before"])
                if doc.get("default_arrival_minutes_before") is not None
                else None
            ),
        )
