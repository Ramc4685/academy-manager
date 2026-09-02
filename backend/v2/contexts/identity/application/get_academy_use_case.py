"""Get academy profile settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class AcademyRepo(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...
    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


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


class GetAcademyUseCase:
    def __init__(self, academy_repo: AcademyRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str) -> GetAcademyOutput:
        doc = await self._repo.find_by_id(academy_id)
        if not doc:
            doc = await self._repo.upsert_defaults(academy_id)
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
        )
