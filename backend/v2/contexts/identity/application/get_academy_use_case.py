"""Get academy profile settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol


class AcademyRepo(Protocol):
    async def find_by_id(self, academy_id: str) -> Optional[dict[str, Any]]: ...
    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GetAcademyOutput:
    academy_id: str
    display_name: str
    timezone: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    hours_text: Optional[str] = None
    address: Optional[str] = None
    logo_url: Optional[str] = None
    brand_color: Optional[str] = None


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
            timezone=doc.get("timezone") or "UTC",
            contact_email=doc.get("contact_email"),
            contact_phone=doc.get("contact_phone"),
            hours_text=doc.get("hours_text"),
            address=doc.get("address"),
            logo_url=doc.get("logo_url"),
            brand_color=doc.get("brand_color"),
        )
